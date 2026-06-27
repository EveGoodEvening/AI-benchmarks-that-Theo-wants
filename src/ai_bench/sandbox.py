"""Hermetic sandbox backend, sandboxed command dispatcher, and repo-state
snapshot (chunk C07).

This module owns the enforced execution boundary for tool-proficiency
benchmarks.  It implements the :class:`ai_bench.models.CommandDispatcher`
contract frozen by C05 so the runner can plug it in without editing
``models.py`` or ``run_records.py``.

Two backends share one boundary contract:

* ``bwrap`` — the primary Linux namespace backend (user + mount + network
  namespaces, private mount table rooted at the sandbox dir, empty network
  namespace).  Used when ``bwrap`` is present and the host is Linux.
* ``in-process`` — the fallback allowlisted operation dispatcher used when
  ``bwrap`` is unavailable or the host is non-Linux.  It runs NO shell and NO
  arbitrary subprocess: only a vetted set of git/file operations implemented
  in-process against the sandbox root.

A plain temp working tree plus ``cwd``/env cleanup is explicitly NOT an
accepted sandbox; temp directories here are storage *inside* the boundary,
never the boundary mechanism.  The in-process backend enforces the same
working-directory/path/host-boundary confinement as the namespace backend.

The active backend is exposed via :func:`default_backend_id` and recorded in
the run-record environment hash by the runner.

C07.3 hardening (network denial, env/credential stripping, timeouts/resource
limits) is enforced inside :meth:`InProcessSandboxDispatcher.dispatch` so
every boundary violation is recorded in the run-record transcript with the
``sandbox_boundary_violation`` flag and a reason.
"""

from __future__ import annotations

import hashlib
import os
import resource
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from ai_bench import types as T
from ai_bench.models import CommandDispatcher, SandboxHandle, ToolActionRequest

__all__ = [
    "SandboxError",
    "BoundaryViolation",
    "SandboxConfig",
    "InProcessSandboxDispatcher",
    "BwrapSandboxDispatcher",
    "default_backend_id",
    "select_dispatcher",
    "host_tree_hash",
    "repo_state_snapshot",
    "sanitize_env",
    "ALLOWED_COMMANDS",
    "DEFAULT_ENV_ALLOWLIST",
    "CREDENTIAL_ENV_PREFIXES",
]


class SandboxError(Exception):
    """Base error for sandbox backend / dispatcher infrastructure failures."""


class BoundaryViolation(SandboxError):
    """A tool action attempted to breach the sandbox boundary.

    Raised when a violation should abort the action; recorded violations that
    fail closed (exit non-zero) without raising are returned as transcript
    rows with ``sandbox_boundary_violation=True``.
    """


# C07.1: the vetted operation allowlist for the in-process backend.  No shell,
# no arbitrary subprocess.  Each entry is implemented as an in-process handler.
ALLOWED_COMMANDS: frozenset[str] = frozenset(
    {"git", "file.write", "file.read", "file.mkdir", "file.remove", "file.list"}
)

# C07.3: minimal env allowlist for git/file operations.  Everything else is
# stripped.  HOME is rewritten to point inside the sandbox by the dispatcher.
DEFAULT_ENV_ALLOWLIST: frozenset[str] = frozenset(
    {"PATH", "HOME", "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL",
     "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "LANG", "LC_ALL"}
)

# C07.3: credential/token prefixes that are always stripped even if an
# override tries to re-introduce them.  Cloud-provider env is denied outright.
CREDENTIAL_ENV_PREFIXES: tuple[str, ...] = (
    "AWS_", "GCP_", "GOOGLE_", "AZURE_", "ARM_", "DIGITALOCEAN_",
    "SSH_", "GITHUB_", "GH_", "GITLAB_", "TF_VAR_", "TOKEN", "SECRET",
    "CREDENTIAL", "PASSWORD", "API_KEY", "PRIVATE_KEY",
)

# C07.3: host credential/config paths that must not be visible inside the
# sandbox.  The in-process backend never mounts the host home, but we also
# reject any tool action that tries to read these locations explicitly.
_HOST_CREDENTIAL_PATHS: tuple[str, ...] = (
    ".gitconfig", ".ssh", ".aws", ".git-credentials", ".config/gh",
    ".netrc",
)

# Default per-command timeout (ms) for the in-process backend.
DEFAULT_TIMEOUT_MS = 10_000

# C07.3: process-count cap for the in-process backend.  The in-process
# backend does not spawn subprocesses for file ops; for git it spawns at most
# one child per action.  This cap is enforced for the bwrap backend's
# subprocess dispatch and documents the policy.
MAX_PROCESSES = 1
# C07 review: strict git safe-subcommand/option allowlist for the in-process
# and bwrap backends.  The dispatcher MUST NOT forward arbitrary argv to the
# host git: a vetted subcommand set plus a vetted option set is enforced
# before git is ever invoked.  This blocks ``-c`` config injection, alias
# expansion, hooks/pagers/external helpers, and network-capable forms.
#
# Subcommands that can reach the network or spawn external helpers are
# excluded entirely; network forms are also rejected explicitly below.
_SAFE_GIT_SUBCOMMANDS: frozenset[str] = frozenset(
    {
        # inspection (read-only)
        "status", "log", "show", "diff", "blame", "shortlog", "describe",
        "rev-parse", "rev-list", "ls-files", "ls-tree", "ls-remote",
        "cat-file", "merge-base", "name-rev", "reflog", "for-each-ref",
        "symbolic-ref", "show-ref", "config", "var",
        # local mutation (no network)
        "init", "add", "rm", "mv", "commit", "restore", "stash",
        "branch", "checkout", "switch", "tag", "reset", "clean",
        "merge", "rebase", "cherry-pick", "revert", "am",
    }
)

# ``ls-remote`` is in the inspection set above for parse-friendliness but is
# network-capable, so it is removed from the *executable* set and rejected as
# a network form below.
_NETWORK_GIT_SUBCOMMANDS: frozenset[str] = frozenset(
    {"fetch", "pull", "push", "clone", "ls-remote", "subtree",
     "daemon", "http-fetch", "http-push", "remote", "request-pull",
     "send-pack", "receive-pack", "upload-pack", "upload-archive",
     "archive"}
)

# Subcommands that are safe to execute (safe set minus network forms).
_EXECUTABLE_GIT_SUBCOMMANDS: frozenset[str] = _SAFE_GIT_SUBCOMMANDS - _NETWORK_GIT_SUBCOMMANDS

# Options that are ALWAYS rejected regardless of subcommand.  These enable
# config injection (``-c``), alias expansion (``-c alias.x=...`` or via
# ``core.alias``), external hooks/pagers/helpers, or shell escapes.
_FORBIDDEN_GIT_OPTIONS: frozenset[str] = frozenset(
    {
        "-c", "--config-env",
        # alias / external command execution
        "--exec", "--exec-path",
        # hooks / external helpers
        "--no-hooks", "--hooks-path",
        # pagers / external programs
        "--pager", "--no-pager",
        # external diff/merge tools spawn arbitrary programs
        "--ext-diff", "--no-ext-diff",
        # gitk / git-gui style external helpers
        "--git-dir", "--work-tree",
    }
)

# Per-subcommand option allowlist.  Only these options may follow the
# subcommand; anything else is rejected.  An entry of ``"*"`` means any
# option is allowed for that subcommand (used only for read-only inspection
# subcommands whose options cannot reach the network or spawn helpers).
_GIT_SUBCOMMAND_OPTIONS: dict[str, frozenset[str]] = {
    "status": frozenset({"--short", "--porcelain", "--branch", "-s", "-b",
                         "--long", "--null", "-z", "--ahead-behind",
                         "--no-ahead-behind", "--untracked-files", "-u",
                         "--ignored", "--ignored=traditional", "--column",
                         "--no-column", "--find-renames", "-M", "--renames",
                         "--no-renames"}),
    "log": frozenset({"--oneline", "--pretty", "--format", "--abbrev-commit",
                      "--no-abbrev", "--max-count", "-n", "--skip",
                      "--since", "--until", "--author", "--grep",
                      "--all", "--branches", "--tags", "--remotes",
                      "--no-remotes", "--topo-order", "--date-order",
                      "--reverse", "--no-merges", "--merges", "--first-parent",
                      "--stat", "--shortstat", "--name-only", "--name-status",
                      "--numstat", "--patch", "-p", "--no-patch",
                      "--show-signature", "--graph", "--decorate",
                      "--source", "--mailmap", "--no-mailmap", "-z"}),
    "show": frozenset({"--stat", "--shortstat", "--name-only", "--name-status",
                       "--numstat", "--patch", "-p", "--no-patch",
                       "--pretty", "--format", "--abbrev-commit",
                       "--no-abbrev", "--oneline", "--source", "-z"}),
    "diff": frozenset({"--stat", "--shortstat", "--name-only", "--name-status",
                       "--numstat", "--patch", "-p", "--no-patch",
                       "--cached", "--staged", "--no-index", "--quiet", "-q",
                       "--exit-code", "--find-renames", "-M", "--no-renames",
                       "--abbrev", "--no-abbrev", "--raw", "--text", "-a",
                       "--ignore-space-change", "--ignore-all-space",
                       "--ignore-blank-lines", "--word-diff", "--color",
                       "--no-color", "--word-diff-regex", "-z"}),
    "blame": frozenset({"--porcelain", "--line-porcelain", "--incremental",
                        "--root", "--show-stats", "-L", "--before", "--after",
                        "--reverse", "--abbrev", "--no-abbrev", "-w", "-C",
                        "-M", "--color-by-age", "--color-lines", "-t", "-s",
                        "-e", "--show-email", "--show-name", "--show-number",
                        "-n", "-l", "--minimal", "-c", "--cc"}),
    "shortlog": frozenset({"-s", "-n", "--numbered", "--summary",
                           "--email", "-e", "--group", "--no-merges",
                           "--all", "--branches", "--tags", "--remotes"}),
    "describe": frozenset({"--tags", "--all", "--contains", "--abbrev",
                           "--candidates", "--debug", "--long", "--always",
                           "--first-parent", "--dirty", "--broken"}),
    "rev-parse": frozenset({"--short", "--verify", "--quiet", "-q",
                            "--git-dir", "--show-toplevel", "--is-inside-work-tree",
                            "--is-inside-git-dir", "--is-bare-repository",
                            "--show-prefix", "--show-cdup", "--absolute-git-dir",
                            "--abbrev-ref", "--symbolic-full-name",
                            "--default", "--revs-only", "--no-revs",
                            "--flags", "--no-flags", "--sq", "--sq-quote",
                            "--git-path", "--show-superproject-working-tree"}),
    "rev-list": frozenset({"--count", "--all", "--branches", "--tags",
                           "--remotes", "--max-count", "-n", "--skip",
                           "--since", "--until", "--author", "--grep",
                           "--no-merges", "--merges", "--first-parent",
                           "--topo-order", "--date-order", "--reverse",
                           "--objects", "--objects-edge", "--quiet", "-q"}),
    "ls-files": frozenset({"--cached", "--modified", "--deleted", "--others",
                           "--ignored", "--stage", "--unmerged", "-u", "-z",
                           "--exclude-standard", "--full-name", "--abbrev",
                           "--no-abbrev", "--error-unmatch", "--exclude",
                           "--exclude-from", "-x", "-X", "-i", "-k", "-m",
                           "-d", "-o", "-c", "--debug"}),
    "ls-tree": frozenset({"-d", "-r", "-t", "-l", "--long", "--name-only",
                          "--name-status", "-z", "--abbrev", "--full-name",
                          "--full-tree", "--object-only"}),
    "cat-file": frozenset({"-t", "-s", "-e", "-p", "--batch", "--batch-check",
                           "--batch-all-objects", "--text", "--textconv",
                           "--filters", "--path", "--buffer", "-z"}),
    "merge-base": frozenset({"-a", "--all", "--is-ancestor", "--independent",
                             "--fork-point", "--octopus"}),
    "name-rev": frozenset({"--tags", "--all", "--name-only", "--stdin",
                           "--refs", "--no-undefined", "--always", "--undefined"}),
    "reflog": frozenset({"show", "expire", "delete", "exists", "--all",
                         "--upstream", "--rewrite", "--no-rewrite",
                         "--expire", "--expire-unreachable", "--dry-run",
                         "-n", "--pretty", "--format", "--oneline"}),
    "for-each-ref": frozenset({"--count", "--format", "--python", "--shell",
                               "--perl", "--tcl", "--points-at", "--merged",
                               "--no-merged", "--contains", "--no-contains",
                               "--sort", "--all", "--exclude", "--stdin",
                               "--debug"}),
    "symbolic-ref": frozenset({"-d", "--delete", "-q", "--quiet", "--short",
                               "-m", "--message", "--ref"}),
    "show-ref": frozenset({"--head", "--tags", "--heads", "--verify", "-s",
                           "--hash", "--abbrev", "--dereference", "-d", "-q",
                           "--quiet", "--all", "--exclude-existing"}),
    "config": frozenset({"--file", "-f", "--global", "--local", "--system",
                         "--list", "-l", "--get", "--get-all", "--get-regexp",
                         "--get-urlmatch", "--add", "--unset", "--unset-all",
                         "--replace-all", "--rename-section", "--remove-section",
                         "-e", "--edit", "--null", "-z", "--name-only",
                         "--includes", "--no-includes", "--bool", "--int",
                         "--bool-or-int", "--path", "--type", "--show-origin",
                         "--show-scope", "--default", "--get-revpath"}),
    "var": frozenset({"-l", "--list"}),
    "init": frozenset({"-q", "--quiet", "--bare", "--template", "--shared",
                       "-b", "--initial-branch", "--separate-git-dir",
                       "--object-format"}),
    "add": frozenset({"-A", "--all", "-u", "--update", "-f", "--force",
                      "-i", "--interactive", "-p", "--patch", "-N",
                      "--intent-to-add", "-n", "--dry-run", "--renormalize",
                      "-v", "--verbose", "--ignore-removal", "--no-ignore-removal",
                      "--chmod", "-z"}),
    "rm": frozenset({"-f", "--force", "-r", "--cached", "-n", "--dry-run",
                     "-q", "--quiet", "--ignore-unmatch", "-v", "--verbose", "-z"}),
    "mv": frozenset({"-f", "--force", "-k", "-n", "--dry-run", "-v", "--verbose",
                     "--sparse", "--pathspec-from-file"}),
    "commit": frozenset({"-m", "--message", "-a", "--all", "-q", "--quiet",
                         "-v", "--verbose", "--amend", "--no-edit", "-e",
                         "--edit", "--allow-empty", "--allow-empty-message",
                         "--no-verify", "--verify", "-s", "--signoff",
                         "--no-signoff", "--author", "--date", "--cleanup",
                         "--no-status", "--status", "-z", "--no-verify",
                         "--reset-author", "--trailer", "-F", "--file",
                         "-C", "--reuse-message", "-c", "--reedit-message",
                         "--no-post-rewrite", "--post-rewrite"}),
    "restore": frozenset({"-s", "--source", "-W", "--worktree", "-S",
                          "--staged", "-p", "--patch", "--ours", "--theirs",
                          "-m", "--merge", "--conflict", "--ignore-unmerged",
                          "--no-ignore-unmerged", "--ignore-skip-worktree-bits",
                          "--overlay", "--no-overlay", "-q", "--quiet",
                          "--progress", "--no-progress", "-z"}),
    "stash": frozenset({"push", "pop", "apply", "drop", "list", "show",
                        "branch", "clear", "create", "store", "save",
                        "--keep-index", "--no-keep-index", "--include-untracked",
                        "-u", "--all", "-p", "--patch", "-q", "--quiet",
                        "-m", "--message", "--staged", "-S", "-n",
                        "--no-index", "--index"}),
    "branch": frozenset({"-d", "--delete", "-D", "--list", "-m", "--move",
                         "-c", "--copy", "-r", "--remotes", "-a", "--all",
                         "-v", "--verbose", "-q", "--quiet", "-f", "--force",
                         "--set-upstream-to", "--unset-upstream", "-u",
                         "--set-upstream", "--track", "--no-track",
                         "--contains", "--no-contains", "--merged",
                         "--no-merged", "--points-at", "--column",
                         "--no-column", "-t", "--edit-description",
                         "--abbrev", "--no-abbrev", "-i", "--ignore-case",
                         "--sort", "--format", "--show-current", "-z"}),
    "checkout": frozenset({"-b", "--branch", "-B", "-q", "--quiet", "-f",
                           "--force", "--track", "--no-track", "--detach",
                           "--orphan", "-m", "--merge", "-p", "--patch",
                           "--ours", "--theirs", "--conflict", "--no-progress",
                           "--progress", "-t", "--theirs", "--ours", "--no-write-tree",
                           "--write-tree", "--recurse-submodules",
                           "--no-recurse-submodules", "--overlay",
                           "--no-overlay", "--pathspec-from-file", "-z"}),
    "switch": frozenset({"-c", "--create", "-C", "--force-create", "-d",
                         "--detach", "-q", "--quiet", "--track", "--no-track",
                         "-m", "--merge", "--guess", "--no-guess", "-t",
                         "--discard-changes", "--recurse-submodules",
                         "--no-recurse-submodules", "--orphan", "-z"}),
    "tag": frozenset({"-l", "--list", "-d", "--delete", "-v", "--verify",
                      "-a", "--annotate", "-s", "--sign", "-f", "--force",
                      "-m", "--message", "-F", "--file", "-e", "--edit",
                      "-u", "--local-user", "-n", "--column", "--no-column",
                      "--contains", "--no-contains", "--merged", "--no-merged",
                      "--points-at", "--sort", "--format", "--cleanup",
                      "--create-reflog", "-z"}),
    "reset": frozenset({"--soft", "--mixed", "--hard", "--merge", "--keep",
                        "-q", "--quiet", "-p", "--patch", "-N",
                        "--intent-to-add", "--pathspec-from-file", "-z"}),
    "clean": frozenset({"-d", "-f", "--force", "-i", "--interactive", "-n",
                        "--dry-run", "-q", "--quiet", "-x", "-X", "-e",
                        "--exclude", "--dry-run", "--no-recursive",
                        "--recursive", "-z"}),
    "merge": frozenset({"-q", "--quiet", "-v", "--verbose", "--no-ff",
                        "--ff", "--ff-only", "--no-commit", "--commit",
                        "--edit", "-e", "--no-edit", "--no-stat", "--stat",
                        "-s", "--strategy", "-X", "--strategy-option",
                        "-m", "--message", "-F", "--file", "--rerere-autoupdate",
                        "--no-rerere-autoupdate", "--abort", "--continue",
                        "--no-verify", "--verify", "--no-progress", "--progress",
                        "-z"}),
    "rebase": frozenset({"-i", "--interactive", "--onto", "--continue",
                         "--abort", "--skip", "--quit", "--edit-todo",
                         "--show-current-patch", "-q", "--quiet", "-v",
                         "--verbose", "--stat", "--no-stat", "--autostash",
                         "--no-autostash", "--no-ff", "--ff", "--no-verify",
                         "--verify", "-m", "--merge", "--no-keep-empty",
                         "--keep-empty", "--root", "-x", "--exec",
                         "--strategy", "-s", "--strategy-option", "-X",
                         "--rerere-autoupdate", "--no-rerere-autoupdate",
                         "--gpg-sign", "--no-gpg-sign", "-z"}),
    "cherry-pick": frozenset({"-e", "--edit", "--no-commit", "-n", "-s",
                              "--signoff", "-x", "--ff", "--no-ff",
                              "--continue", "--abort", "--quit", "--skip",
                              "--allow-empty", "--allow-empty-message",
                              "--keep-redundant-commits", "--strategy", "-s",
                              "--strategy-option", "-X", "-m", "--mainline",
                              "--gpg-sign", "--no-gpg-sign", "-z"}),
    "revert": frozenset({"-e", "--edit", "--no-edit", "--no-commit", "-n",
                         "-s", "--signoff", "--continue", "--abort",
                         "--quit", "--skip", "--strategy", "-s",
                         "--strategy-option", "-X", "-m", "--mainline",
                         "--gpg-sign", "--no-gpg-sign", "-z"}),
    "am": frozenset({"-s", "--signoff", "-3", "--3way", "--keep", "--no-keep",
                     "-q", "--quiet", "-v", "--verbose", "-c", "--scissors",
                     "--no-scissors", "--utf8", "--no-utf8", "--no-utf8",
                     "--ignore-space-change", "--ignore-whitespace",
                     "--whitespace", "--abort", "--continue", "-r", "--resolved",
                     "--skip", "--show-current-patch", "--committer-date-is-author-date",
                     "--ignore-date", "--ignore-date", "--gpg-sign", "--no-gpg-sign",
                     "-z"}),
}


def _validate_git_argv(argv: tuple[str, ...]) -> str | None:
    """Validate a git argv against the strict safe allowlist.

    Returns a violation reason string if the argv is rejected, else ``None``.
    The check runs BEFORE git is invoked so no arbitrary argv is ever passed
    to the host git binary.  Rejected classes:

    * global git options before the subcommand (``-c``, ``--config-env``,
      ``--git-dir``, ``--work-tree``, ``--exec``, hooks/pagers, etc.) which
      enable config injection, alias expansion, or external helpers;
    * subcommands outside the executable safe set (network forms, helpers,
      plumbing that spawns external programs);
    * options after the subcommand that are not in the per-subcommand
      allowlist (this catches ``-c`` after a subcommand too, plus any option
      that could enable a pager/external helper);
    * explicit URL / ``git@`` / ``ssh://`` arguments (network targets).

    This is the single chokepoint used by both the in-process and bwrap
    backends, so the two cannot drift.
    """
    if not argv:
        return "git requires a subcommand"
    # Walk leading global options until we hit the subcommand.  Any global
    # option is rejected: the allowlist permits NO pre-subcommand options.
    idx = 0
    while idx < len(argv) and argv[idx].startswith("-"):
        opt = argv[idx]
        if opt in _FORBIDDEN_GIT_OPTIONS:
            return (
                f"git global option {opt!r} is forbidden: it enables config "
                "injection, alias expansion, or external helpers"
            )
        return (
            f"git global option {opt!r} is not allowed; the sandbox permits "
            "no options before the git subcommand"
        )
    sub = argv[idx]
    rest = argv[idx + 1:]
    # Subcommand allowlist.
    if sub in _NETWORK_GIT_SUBCOMMANDS:
        return (
            f"git {sub} denied: outbound network access is not allowed "
            "in the sandbox"
        )
    if sub not in _EXECUTABLE_GIT_SUBCOMMANDS:
        return (
            f"git subcommand {sub!r} is not in the sandbox safe-subcommand "
            "allowlist"
        )
    # Reject any explicit URL / network target in the remaining args.
    for arg in rest:
        if "://" in arg or arg.startswith("git@") or arg.startswith("ssh://"):
            return (
                f"git network target {arg!r} denied: outbound network "
                "access is not allowed in the sandbox"
            )
    # Per-subcommand option allowlist.  Positional args (non-dash-prefixed)
    # are permitted and confined by the path checks elsewhere; options must
    # be in the allowlist and must not be a forbidden option.
    allowed_opts = _GIT_SUBCOMMAND_OPTIONS.get(sub)
    if allowed_opts is None:
        return (
            f"git subcommand {sub!r} has no option allowlist defined; "
            "refusing to run with unvetted options"
        )
    for arg in rest:
        if not arg.startswith("-"):
            continue
        # Reject ``--option=value`` by checking the ``--option`` stem against
        # the forbidden set and the allowlist.
        stem = arg.split("=", 1)[0]
        if stem in _FORBIDDEN_GIT_OPTIONS or arg in _FORBIDDEN_GIT_OPTIONS:
            return (
                f"git option {arg!r} is forbidden: it enables config "
                "injection, alias expansion, or external helpers"
            )
        if stem not in allowed_opts and arg not in allowed_opts:
            return (
                f"git option {arg!r} is not in the allowlist for "
                f"subcommand {sub!r}"
            )
    return None


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------


def _bwrap_available() -> bool:
    """Return True iff the ``bwrap`` namespace backend can be used.

    The namespace backend requires Linux + a ``bwrap`` binary on PATH.  This
    is checked explicitly (not silently) so backend selection is testable.
    """
    if sys.platform != "linux" and not sys.platform.startswith("linux"):
        return False
    return shutil.which("bwrap") is not None


def default_backend_id() -> str:
    """Return the backend id that :func:`select_dispatcher` will choose.

    Exposed so the runner and tests can record/predict the active backend
    without constructing a dispatcher.  ``bwrap`` when available, else
    ``in-process``.
    """
    return "bwrap" if _bwrap_available() else "in-process"


def select_dispatcher(
    *,
    backend: str | None = None,
    config: "SandboxConfig | None" = None,
) -> CommandDispatcher:
    """Select and return an enforced sandbox dispatcher.

    ``backend`` may be ``"bwrap"``, ``"in-process"``, or ``None`` (auto: prefer
    ``bwrap``, fall back to in-process).  The returned dispatcher implements
    the C05 :class:`CommandDispatcher` contract with path/network/env/time
    confinement and the same transcript-row return shape.
    """
    cfg = config or SandboxConfig()
    chosen = backend or default_backend_id()
    if chosen == "bwrap":
        if not _bwrap_available():
            raise SandboxError(
                "bwrap backend requested but unavailable (requires Linux + bwrap)"
            )
        return BwrapSandboxDispatcher(cfg)
    if chosen == "in-process":
        return InProcessSandboxDispatcher(cfg)
    raise SandboxError(f"unknown sandbox backend {chosen!r}")


# ---------------------------------------------------------------------------
# Sandbox config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SandboxConfig:
    """Security policy for an enforced sandbox dispatcher.

    Defaults implement the C07.3 hardening posture: outbound network denied,
    env cleared to a minimal allowlist with HOME rewritten into the sandbox,
    credentials stripped, per-command timeouts and resource limits applied.
    """

    allowed_commands: frozenset[str] = ALLOWED_COMMANDS
    env_allowlist: frozenset[str] = DEFAULT_ENV_ALLOWLIST
    credential_env_prefixes: tuple[str, ...] = CREDENTIAL_ENV_PREFIXES
    default_timeout_ms: int = DEFAULT_TIMEOUT_MS
    max_processes: int = MAX_PROCESSES
    deny_network: bool = True
    strip_credentials: bool = True
    # CPU seconds limit per dispatched action (C07.3 resource limit).
    cpu_seconds: int = 5
    # Max file bytes a single file.write may produce (C07.3 disk limit).
    max_file_bytes: int = 8 * 1024 * 1024


# ---------------------------------------------------------------------------
# Path confinement
# ---------------------------------------------------------------------------


def _resolve_sandbox_path(root: Path, cwd: str, target: str) -> Path:
    """Resolve ``target`` relative to ``root/cwd`` and confine it to ``root``.

    Absolute paths, drive letters, and symlink escapes outside ``root`` are
    rejected with :class:`BoundaryViolation`.  ``cwd`` is itself confined
    first.  The returned path is the resolved real path if it exists, else
    the lexically-confined path.
    """
    if not target:
        raise BoundaryViolation("empty path is not allowed")
    # Reject absolute paths and drive letters outright: the sandbox root is
    # the only root.
    p = Path(target)
    if p.is_absolute() or (len(target) >= 2 and target[1] == ":"):
        raise BoundaryViolation(
            f"absolute path {target!r} is outside the sandbox root"
        )
    # Confine cwd first.
    cwd_path = _confine_relative(root, cwd)
    candidate = (cwd_path / target)
    confined = _confine_lexical(root, candidate)
    return confined


def _confine_relative(root: Path, rel: str) -> Path:
    if not rel:
        return root
    p = Path(rel)
    if p.is_absolute():
        raise BoundaryViolation(
            f"absolute cwd {rel!r} is outside the sandbox root"
        )
    return _confine_lexical(root, root / rel)


def _confine_lexical(root: Path, candidate: Path) -> Path:
    """Lexically confine ``candidate`` to ``root`` without following symlinks.

    Resolves ``..`` and ``.`` components against ``root`` and rejects any path
    that escapes.  Symlink escapes are checked separately at access time.
    """
    root_resolved = root.resolve()
    # Build the path from root, then normalize lexically (no symlink follow).
    parts: list[str] = []
    # candidate may already be under root; make it relative if possible.
    try:
        rel = candidate.relative_to(root) if candidate != root else Path(".")
        for part in rel.parts:
            parts.append(part)
    except ValueError:
        # candidate was constructed as root / something; recompute from str.
        s = str(candidate)
        rs = str(root_resolved)
        if not s.startswith(rs):
            raise BoundaryViolation(
                f"path {candidate} escapes the sandbox root {root}"
            ) from None
        rest = s[len(rs):].lstrip("/\\")
        for part in rest.split("/"):
            if part:
                parts.append(part)

    out = root_resolved
    for part in parts:
        if part in ("", "."):
            continue
        if part == "..":
            if out == root_resolved:
                raise BoundaryViolation(
                    f"path {candidate} escapes the sandbox root via '..'"
                )
            out = out.parent
            continue
        out = out / part
    return out


def _check_symlink_escape(root: Path, path: Path) -> None:
    """Reject ``path`` or any ancestor of it that resolves outside ``root``.

    A write to ``link/notes.md`` where ``link`` is a symlink to ``/etc`` would
    otherwise escape the sandbox even though ``notes.md`` does not yet exist
    (the old check returned early for non-existent paths).  We walk every
    existing ancestor of ``path`` and reject any symlink whose resolved target
    is outside ``root``; this catches ancestor-escape before any file or
    directory is created/written through the symlink.
    """
    root_resolved = root.resolve()
    # If path is the root itself, there are no ancestors under root to walk.
    if path == root_resolved:
        return
    # Check the path itself if it exists or is a symlink.
    if path.exists() or path.is_symlink():
        try:
            path.resolve().relative_to(root_resolved)
        except ValueError:
            raise BoundaryViolation(
                f"symlink {path} resolves outside the sandbox root"
            ) from None
    # Walk ancestors that are strictly under ``root_resolved``: a symlinked
    # directory ancestor inside the sandbox can redirect a write of a
    # not-yet-existing path outside the sandbox.  We stop at ``root_resolved``
    # and never check it or anything above it (those are the boundary, not
    # escapes).  ``path`` itself is already checked above.
    ancestor = path.parent
    while ancestor != ancestor.parent:
        if ancestor == root_resolved:
            return
        # If the ancestor is not lexically under root, stop: the confinement
        # was already enforced by _confine_lexical, and we must not flag the
        # root's own parent as an escape.
        try:
            ancestor.relative_to(root_resolved)
        except ValueError:
            return
        if ancestor.exists() or ancestor.is_symlink():
            try:
                ancestor.resolve().relative_to(root_resolved)
            except ValueError:
                raise BoundaryViolation(
                    f"symlink ancestor {ancestor} of {path} resolves outside "
                    "the sandbox root"
                ) from None
        ancestor = ancestor.parent


# ---------------------------------------------------------------------------
# Environment sanitization (C07.3)
# ---------------------------------------------------------------------------


def sanitize_env(
    base: Mapping[str, str],
    *,
    sandbox_root: Path,
    config: SandboxConfig,
    overrides: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return a sanitized env for a sandboxed action.

    Starts empty, copies only allowlisted keys from ``base``, rewrites HOME
    to point inside the sandbox, applies ``overrides`` for allowlisted keys,
    and strips any credential-prefixed override.  Credential/cloud/SSH env is
    never present in the returned env.
    """
    out: dict[str, str] = {}
    for key in config.env_allowlist:
        if key in base:
            out[key] = str(base[key])
    # HOME always points inside the sandbox, regardless of base.
    out["HOME"] = str(sandbox_root)
    # A minimal PATH is required for git; keep the inherited PATH only if it
    # was allowlisted through.  We always ensure /usr/bin:/bin is available so
    # git is resolvable without exposing host-specific paths via env.
    out["PATH"] = base.get("PATH", "/usr/bin:/bin")
    # Safe git identity defaults so git operations do not need host config.
    out.setdefault("GIT_AUTHOR_NAME", "ai-bench-sandbox")
    out.setdefault("GIT_AUTHOR_EMAIL", "sandbox@ai-bench.local")
    out.setdefault("GIT_COMMITTER_NAME", "ai-bench-sandbox")
    out.setdefault("GIT_COMMITTER_EMAIL", "sandbox@ai-bench.local")
    # Prevent git from reading host config files.
    out["GIT_CONFIG_NOSYSTEM"] = "1"
    out["GIT_CONFIG_GLOBAL"] = str(sandbox_root / ".gitconfig")
    out["GIT_TERMINAL_PROMPT"] = "0"

    if overrides:
        for key, value in overrides.items():
            if _is_credential_env(key):
                # Credential override is dropped silently; the violation is
                # recorded by the dispatcher caller, which sees the rejected
                # key in the returned env's absence.
                continue
            if key in config.env_allowlist:
                out[key] = str(value)
            # Non-allowlisted, non-credential overrides are dropped.
    return out


def _is_credential_env(key: str) -> bool:
    upper = key.upper()
    for prefix in CREDENTIAL_ENV_PREFIXES:
        if upper.startswith(prefix):
            return True
    return False


def _credential_override_violations(
    overrides: Mapping[str, str], config: SandboxConfig
) -> list[str]:
    """Return the credential env keys in ``overrides`` that were stripped."""
    bad: list[str] = []
    for key in overrides:
        if _is_credential_env(key):
            bad.append(key)
    return bad


# ---------------------------------------------------------------------------
# Host-tree hash (no-host-mutation assertion)
# ---------------------------------------------------------------------------


def host_tree_hash(root: Path) -> str:
    """Return a deterministic sha256 over the file tree at ``root``.

    Walks ``root`` and hashes relative path + file contents + mode bits.  Used
    by C07.1/C07.2 no-host-mutation assertions: the host repo hash must be
    byte-identical before and after a sandboxed run.  Symlinks are hashed by
    their link target string (not followed) so a symlink-only change is still
    detected.
    """
    h = hashlib.sha256()
    if not root.exists():
        return f"sha256:{h.hexdigest()}"
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(dirnames + filenames):
            entry = Path(dirpath, name)
            try:
                rel = entry.relative_to(root).as_posix()
            except ValueError:  # pragma: no cover - defensive
                continue
            h.update(rel.encode("utf-8"))
            h.update(b"\x00")
            try:
                st = entry.lstat()
            except OSError:  # pragma: no cover - defensive
                h.update(b"missing\x00")
                continue
            h.update(str(st.st_mode).encode("ascii"))
            h.update(b"\x00")
            if entry.is_symlink():
                h.update(os.readlink(entry).encode("utf-8"))
                h.update(b"\x00")
            elif entry.is_file():
                with entry.open("rb") as fh:
                    for chunk in iter(lambda: fh.read(65536), b""):
                        h.update(chunk)
                h.update(b"\x00")
    return f"sha256:{h.hexdigest()}"


# ---------------------------------------------------------------------------
# Repo-state snapshot (C07.2)
# ---------------------------------------------------------------------------


def repo_state_snapshot(root: Path) -> T.RepoState:
    """Materialize the final repo-state snapshot from the sandbox ``root``.

    Captures file tree, ``git status --porcelain``, branches, commit
    summaries, and the working-tree diff against HEAD.  Safe to call on a
    non-git directory: git fields are empty.  Git is invoked with the sandbox
    root as cwd and a sanitized env so the snapshot itself does not touch host
    config or network.
    """
    file_tree = _file_tree(root)
    git_status = ""
    branches: tuple[str, ...] = ()
    commits: tuple[Mapping[str, str], ...] = ()
    diff = ""
    if (root / ".git").exists():
        env = _snapshot_env(root)
        git_status = _git_text(root, env, "status", "--porcelain")
        branches = tuple(
            _git_lines(root, env, "for-each-ref", "--format=%(refname:short)",
                       "refs/heads")
        ) or ("main",)
        commits = _git_commits(root, env)
        diff = _git_text(root, env, "diff", "HEAD", "--no-color") or _git_text(
            root, env, "diff", "--cached", "--no-color"
        )
    else:
        branches = ("main",)
    return T.RepoState(
        file_tree=file_tree,
        git_status=git_status,
        branches=branches,
        commits=commits,
        diff=diff,
    )


def _file_tree(root: Path) -> tuple[str, ...]:
    paths: list[str] = []
    if not root.exists():
        return ()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for name in filenames:
            p = Path(dirpath, name)
            try:
                paths.append(p.relative_to(root).as_posix())
            except ValueError:  # pragma: no cover
                continue
    return tuple(sorted(paths))


def _snapshot_env(root: Path) -> dict[str, str]:
    cfg = SandboxConfig()
    return sanitize_env(
        os.environ, sandbox_root=root, config=cfg
    )


def _git_text(root: Path, env: Mapping[str, str], *args: str) -> str:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=root,
            env=dict(env),
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (subprocess.SubprocessError, OSError):
        return ""
    return proc.stdout


def _git_lines(root: Path, env: Mapping[str, str], *args: str) -> list[str]:
    text = _git_text(root, env, *args)
    return [line for line in text.splitlines() if line.strip()]


def _git_commits(root: Path, env: Mapping[str, str]) -> tuple[Mapping[str, str], ...]:
    text = _git_text(root, env, "log", "--pretty=%H%x1f%s", "-n", "20")
    out: list[Mapping[str, str]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        if "\x1f" in line:
            sha, subject = line.split("\x1f", 1)
        else:
            sha, subject = line, ""
        if len(sha) >= 7:
            out.append({"sha": sha[:7], "subject": subject})
    return tuple(out)


# ---------------------------------------------------------------------------
# In-process allowlisted dispatcher (C07.1 + C07.3)
# ---------------------------------------------------------------------------


@dataclass
class _ViolationRecord:
    """Internal record of a boundary violation for transcript capture."""

    reason: str


class InProcessSandboxDispatcher:
    """Enforced in-process allowlisted operation dispatcher.

    This is NOT a plain temp working tree.  It runs no shell and no arbitrary
    subprocess: only the vetted operations in :data:`ALLOWED_COMMANDS` are
    implemented, each confined to the sandbox root.  Path escapes, network
    access, credential access, and resource-limit breaches fail closed and
    are recorded in the transcript with ``sandbox_boundary_violation=True``.

    Used as the fallback when ``bwrap`` is unavailable or the host is
    non-Linux; also the default backend in environments without ``bwrap``.
    """

    backend_id = "in-process"

    def __init__(self, config: SandboxConfig | None = None) -> None:
        self.config = config or SandboxConfig()

    def dispatch(
        self,
        action: ToolActionRequest,
        *,
        sandbox: SandboxHandle,
    ) -> T.ToolAction:
        """Run one allowlisted action under confinement and return a transcript row."""
        start = time.monotonic()
        cwd = action.cwd or "."
        argv = tuple(str(a) for a in action.argv)
        env_overrides = {str(k): str(v) for k, v in action.env_overrides.items()}

        violation = self._check_command_allowed(action.command)
        if violation is not None:
            return self._violation_row(
                action, cwd, argv, env_overrides, violation, start
            )

        # C07.3: credential env overrides are stripped and recorded.
        cred_keys = _credential_override_violations(env_overrides, self.config)
        if cred_keys:
            reason = (
                "credential env overrides stripped: " + ", ".join(sorted(cred_keys))
            )
            return self._violation_row(
                action, cwd, argv, env_overrides, _ViolationRecord(reason), start
            )

        # C07.3: per-command timeout.
        timeout_ms = action.timeout_ms or sandbox.default_timeout_ms or self.config.default_timeout_ms

        try:
            handler = self._handler_for(action.command)
            exit_code, stdout, stderr = self._run_handler(
                handler, action, sandbox, argv, cwd, env_overrides, timeout_ms
            )
        except BoundaryViolation as exc:
            return self._violation_row(
                action, cwd, argv, env_overrides,
                _ViolationRecord(str(exc)), start,
            )
        except subprocess.TimeoutExpired:
            return self._timeout_row(action, cwd, argv, env_overrides, start)
        except Exception as exc:  # pragma: no cover - defensive
            return self._error_row(action, cwd, argv, env_overrides, str(exc), start)

        wall = int((time.monotonic() - start) * 1000)
        return T.ToolAction(
            command=action.command,
            argv=argv,
            cwd=cwd,
            env_overrides=self._surviving_env(env_overrides),
            stdin=action.stdin,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            wall_clock_ms=wall,
            timeout=False,
            sandbox_boundary_violation=False,
            violation_reason=None,
        )

    def snapshot(
        self,
        *,
        sandbox: SandboxHandle,
        transcript: Sequence[T.ToolAction],
    ) -> T.RepoState:
        """Materialize the final repo-state snapshot from the sandbox root."""
        del transcript
        return repo_state_snapshot(sandbox.root)

    # --- handlers -----------------------------------------------------------

    def _handler_for(self, command: str) -> Any:
        if command == "git":
            return self._handle_git
        if command == "file.write":
            return self._handle_file_write
        if command == "file.read":
            return self._handle_file_read
        if command == "file.mkdir":
            return self._handle_file_mkdir
        if command == "file.remove":
            return self._handle_file_remove
        if command == "file.list":
            return self._handle_file_list
        raise BoundaryViolation(f"command {command!r} is not allowlisted")

    def _check_command_allowed(self, command: str) -> _ViolationRecord | None:
        if not command:
            return _ViolationRecord("tool action command must be non-empty")
        if command not in self.config.allowed_commands:
            return _ViolationRecord(
                f"command {command!r} is not in the sandbox allowlist "
                f"(allowed: {sorted(self.config.allowed_commands)})"
            )
        return None

    def _run_handler(
        self,
        handler: Any,
        action: ToolActionRequest,
        sandbox: SandboxHandle,
        argv: tuple[str, ...],
        cwd: str,
        env_overrides: Mapping[str, str],
        timeout_ms: int,
    ) -> tuple[int, str, str]:
        # C07.3: apply CPU resource limit for the duration of the action.
        prev_cpu = resource.getrlimit(resource.RLIMIT_CPU)
        try:
            resource.setrlimit(
                resource.RLIMIT_CPU,
                (self.config.cpu_seconds, prev_cpu[1]),
            )
            return handler(action, sandbox, argv, cwd, env_overrides, timeout_ms)
        finally:
            resource.setrlimit(resource.RLIMIT_CPU, prev_cpu)

    # --- git ----------------------------------------------------------------

    def _handle_git(
        self,
        action: ToolActionRequest,
        sandbox: SandboxHandle,
        argv: tuple[str, ...],
        cwd: str,
        env_overrides: Mapping[str, str],
        timeout_ms: int,
    ) -> tuple[int, str, str]:
        # C07 review: validate the full argv against the strict safe
        # subcommand/option allowlist BEFORE invoking host git.  This is the
        # single chokepoint that prevents arbitrary argv (``-c`` config
        # injection, alias expansion, hooks/pagers/external helpers, network
        # forms) from reaching the host git binary.
        violation = _validate_git_argv(argv)
        if violation is not None:
            raise BoundaryViolation(violation)
        sub = argv[0]
        rest = argv[1:]

        # Confine cwd.
        cwd_path = _confine_relative(sandbox.root, cwd)
        _check_symlink_escape(sandbox.root, cwd_path)

        env = sanitize_env(
            os.environ,
            sandbox_root=sandbox.root,
            config=self.config,
            overrides=env_overrides,
        )
        # C07.3: ensure no host credential/config paths leak via args.
        self._reject_credential_path_args(rest, sandbox.root)

        timeout_s = max(1, timeout_ms / 1000.0)
        try:
            proc = subprocess.run(
                ["git", sub, *rest],
                cwd=cwd_path,
                env=env,
                input=action.stdin,
                capture_output=True,
                text=True,
                timeout=timeout_s,
            )
        except subprocess.TimeoutExpired:
            raise
        except FileNotFoundError:
            return 127, "", "git executable not found"
        return proc.returncode, proc.stdout, proc.stderr

    # --- file operations ----------------------------------------------------

    def _handle_file_write(
        self,
        action: ToolActionRequest,
        sandbox: SandboxHandle,
        argv: tuple[str, ...],
        cwd: str,
        env_overrides: Mapping[str, str],
        timeout_ms: int,
    ) -> tuple[int, str, str]:
        del env_overrides, timeout_ms
        if len(argv) < 2:
            return 1, "", "file.write requires <path> <content>"
        target = argv[0]
        content = argv[1]
        if len(content.encode("utf-8")) > self.config.max_file_bytes:
            return 1, "", (
                f"file.write exceeds max file bytes ({self.config.max_file_bytes})"
            )
        path = _resolve_sandbox_path(sandbox.root, cwd, target)
        _check_symlink_escape(sandbox.root, path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return 0, f"wrote {target}\n", ""

    def _handle_file_read(
        self,
        action: ToolActionRequest,
        sandbox: SandboxHandle,
        argv: tuple[str, ...],
        cwd: str,
        env_overrides: Mapping[str, str],
        timeout_ms: int,
    ) -> tuple[int, str, str]:
        del action, env_overrides, timeout_ms
        if not argv:
            return 1, "", "file.read requires <path>"
        path = _resolve_sandbox_path(sandbox.root, cwd, argv[0])
        _check_symlink_escape(sandbox.root, path)
        if not path.is_file():
            return 1, "", f"no such file: {argv[0]}"
        return 0, path.read_text(encoding="utf-8"), ""

    def _handle_file_mkdir(
        self,
        action: ToolActionRequest,
        sandbox: SandboxHandle,
        argv: tuple[str, ...],
        cwd: str,
        env_overrides: Mapping[str, str],
        timeout_ms: int,
    ) -> tuple[int, str, str]:
        del action, env_overrides, timeout_ms
        if not argv:
            return 1, "", "file.mkdir requires <path>"
        path = _resolve_sandbox_path(sandbox.root, cwd, argv[0])
        _check_symlink_escape(sandbox.root, path)
        path.mkdir(parents=True, exist_ok=True)
        return 0, f"mkdir {argv[0]}\n", ""

    def _handle_file_remove(
        self,
        action: ToolActionRequest,
        sandbox: SandboxHandle,
        argv: tuple[str, ...],
        cwd: str,
        env_overrides: Mapping[str, str],
        timeout_ms: int,
    ) -> tuple[int, str, str]:
        del action, env_overrides, timeout_ms
        if not argv:
            return 1, "", "file.remove requires <path>"
        path = _resolve_sandbox_path(sandbox.root, cwd, argv[0])
        _check_symlink_escape(sandbox.root, path)
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        elif path.exists() or path.is_symlink():
            path.unlink()
        else:
            return 1, "", f"no such path: {argv[0]}"
        return 0, f"removed {argv[0]}\n", ""

    def _handle_file_list(
        self,
        action: ToolActionRequest,
        sandbox: SandboxHandle,
        argv: tuple[str, ...],
        cwd: str,
        env_overrides: Mapping[str, str],
        timeout_ms: int,
    ) -> tuple[int, str, str]:
        del action, env_overrides, timeout_ms
        rel = argv[0] if argv else "."
        path = _resolve_sandbox_path(sandbox.root, cwd, rel)
        _check_symlink_escape(sandbox.root, path)
        if not path.is_dir():
            return 1, "", f"no such directory: {rel}"
        entries = sorted(p.name for p in path.iterdir())
        return 0, "\n".join(entries) + ("\n" if entries else ""), ""

    # --- helpers ------------------------------------------------------------

    def _reject_credential_path_args(self, args: Sequence[str], root: Path) -> None:
        """Reject explicit references to host credential paths in git args."""
        root_resolved = root.resolve()
        for arg in args:
            if arg.startswith("-"):
                continue
            # Reject well-known host credential file references.
            for cred in _HOST_CREDENTIAL_PATHS:
                if (
                    arg == cred
                    or arg.endswith("/" + cred)
                    or arg == "~/" + cred
                    or arg.startswith("~/" + cred + "/")
                    or arg.startswith(cred + "/")
                ):
                    raise BoundaryViolation(
                        f"git argument {arg!r} references a host credential "
                        f"path {cred!r}; credential access is not allowed"
                    )
            # Reject absolute paths outside the sandbox.
            p = Path(arg)
            if p.is_absolute():
                try:
                    p.resolve().relative_to(root_resolved)
                except ValueError:
                    raise BoundaryViolation(
                        f"git argument {arg!r} is an absolute path outside "
                        "the sandbox root"
                    ) from None

    def _surviving_env(self, overrides: Mapping[str, str]) -> dict[str, str]:
        """Return only the allowlisted, non-credential overrides that survive."""
        out: dict[str, str] = {}
        for key, value in overrides.items():
            if _is_credential_env(key):
                continue
            if key in self.config.env_allowlist:
                out[key] = str(value)
        return out

    def _violation_row(
        self,
        action: ToolActionRequest,
        cwd: str,
        argv: tuple[str, ...],
        env_overrides: Mapping[str, str],
        violation: _ViolationRecord,
        start: float,
    ) -> T.ToolAction:
        wall = int((time.monotonic() - start) * 1000)
        return T.ToolAction(
            command=action.command,
            argv=argv,
            cwd=cwd,
            env_overrides={},
            stdin=action.stdin,
            exit_code=126,
            stdout="",
            stderr=violation.reason,
            wall_clock_ms=wall,
            timeout=False,
            sandbox_boundary_violation=True,
            violation_reason=violation.reason,
        )

    def _timeout_row(
        self,
        action: ToolActionRequest,
        cwd: str,
        argv: tuple[str, ...],
        env_overrides: Mapping[str, str],
        start: float,
    ) -> T.ToolAction:
        wall = int((time.monotonic() - start) * 1000)
        reason = f"action exceeded timeout and was killed"
        return T.ToolAction(
            command=action.command,
            argv=argv,
            cwd=cwd,
            env_overrides={},
            stdin=action.stdin,
            exit_code=137,
            stdout="",
            stderr=reason,
            wall_clock_ms=wall,
            timeout=True,
            sandbox_boundary_violation=True,
            violation_reason=reason,
        )

    def _error_row(
        self,
        action: ToolActionRequest,
        cwd: str,
        argv: tuple[str, ...],
        env_overrides: Mapping[str, str],
        reason: str,
        start: float,
    ) -> T.ToolAction:
        wall = int((time.monotonic() - start) * 1000)
        return T.ToolAction(
            command=action.command,
            argv=argv,
            cwd=cwd,
            env_overrides={},
            stdin=action.stdin,
            exit_code=1,
            stdout="",
            stderr=reason,
            wall_clock_ms=wall,
            timeout=False,
            sandbox_boundary_violation=False,
            violation_reason=None,
        )


# ---------------------------------------------------------------------------
# Bubblewrap namespace backend (C07.1 primary; used when available)
# ---------------------------------------------------------------------------


class BwrapSandboxDispatcher:
    """Bubblewrap namespace backend dispatcher.

    Used when ``bwrap`` is available on Linux.  Each git action is run inside
    a ``bwrap`` invocation with a private mount table rooted at the sandbox
    dir, an empty network namespace (loopback only), and a seccomp filter.
    File operations are still handled in-process (they never need a
    subprocess); only git is dispatched through ``bwrap`` to get namespace
    isolation.  The boundary contract (path confinement, network denial,
    credential stripping, timeouts) is identical to the in-process backend.

    When ``bwrap`` is not available, :func:`select_dispatcher` never returns
    this class; tests that need it should skip when ``bwrap`` is absent.
    """

    backend_id = "bwrap"

    def __init__(self, config: SandboxConfig | None = None) -> None:
        if not _bwrap_available():
            raise SandboxError("bwrap backend requires Linux + bwrap on PATH")
        self.config = config or SandboxConfig()
        self._inner = InProcessSandboxDispatcher(self.config)

    def dispatch(
        self,
        action: ToolActionRequest,
        *,
        sandbox: SandboxHandle,
    ) -> T.ToolAction:
        # File operations are confined in-process; only git gets bwrap.
        if action.command != "git":
            return self._inner.dispatch(action, sandbox=sandbox)
        return self._dispatch_bwrap_git(action, sandbox=sandbox)

    def snapshot(
        self,
        *,
        sandbox: SandboxHandle,
        transcript: Sequence[T.ToolAction],
    ) -> T.RepoState:
        del transcript
        return repo_state_snapshot(sandbox.root)

    def _dispatch_bwrap_git(
        self,
        action: ToolActionRequest,
        *,
        sandbox: SandboxHandle,
    ) -> T.ToolAction:
        start = time.monotonic()
        cwd = action.cwd or "."
        argv = tuple(str(a) for a in action.argv)
        env_overrides = {str(k): str(v) for k, v in action.env_overrides.items()}

        violation = self._inner._check_command_allowed(action.command)
        if violation is not None:
            return self._inner._violation_row(
                action, cwd, argv, env_overrides, violation, start
            )
        cred_keys = _credential_override_violations(env_overrides, self.config)
        if cred_keys:
            reason = "credential env overrides stripped: " + ", ".join(sorted(cred_keys))
            return self._inner._violation_row(
                action, cwd, argv, env_overrides, _ViolationRecord(reason), start
            )
        # C07 review: validate the full argv against the strict safe
        # subcommand/option allowlist BEFORE invoking git inside bwrap.  The
        # bwrap backend shares the same chokepoint as the in-process backend
        # so the two cannot drift on what argv reaches host git.
        violation = _validate_git_argv(argv)
        if violation is not None:
            return self._inner._violation_row(
                action, cwd, argv, env_overrides,
                _ViolationRecord(violation), start,
            )
        sub = argv[0]
        rest = argv[1:]

        cwd_path = _confine_relative(sandbox.root, cwd)
        _check_symlink_escape(sandbox.root, cwd_path)
        env = sanitize_env(
            os.environ, sandbox_root=sandbox.root, config=self.config,
            overrides=env_overrides,
        )
        self._inner._reject_credential_path_args(rest, sandbox.root)

        timeout_ms = action.timeout_ms or sandbox.default_timeout_ms or self.config.default_timeout_ms
        timeout_s = max(1, timeout_ms / 1000.0)
        bwrap_argv = [
            "bwrap",
            "--ro-bind", "/usr", "/usr",
            "--ro-bind", "/lib", "/lib",
            "--ro-bind", "/lib64", "/lib64",
            "--ro-bind", "/bin", "/bin",
            "--proc", "/proc",
            "--dev", "/dev",
            "--tmpfs", "/tmp",
            "--bind", str(sandbox.root.resolve()), str(sandbox.root.resolve()),
            "--unshare-all",
            "--die-with-parent",
            "--new-session",
            "git", sub, *rest,
        ]
        try:
            proc = subprocess.run(
                bwrap_argv,
                cwd=cwd_path,
                env=env,
                input=action.stdin,
                capture_output=True,
                text=True,
                timeout=timeout_s,
            )
        except subprocess.TimeoutExpired:
            return self._inner._timeout_row(action, cwd, argv, env_overrides, start)
        except FileNotFoundError:
            return self._inner._error_row(
                action, cwd, argv, env_overrides, "bwrap executable not found", start
            )
        wall = int((time.monotonic() - start) * 1000)
        return T.ToolAction(
            command=action.command,
            argv=argv,
            cwd=cwd,
            env_overrides=self._inner._surviving_env(env_overrides),
            stdin=action.stdin,
            exit_code=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            wall_clock_ms=wall,
            timeout=False,
            sandbox_boundary_violation=False,
            violation_reason=None,
        )


# ---------------------------------------------------------------------------
# Module-level default dispatcher for runner integration
# ---------------------------------------------------------------------------


_DEFAULT_DISPATCHER: CommandDispatcher | None = None


def default_dispatcher() -> CommandDispatcher:
    """Return a process-wide default enforced dispatcher.

    Constructed lazily so importing the module is cheap.  The runner asks for
    a dispatcher per-run via :func:`select_dispatcher`; this helper exists for
    tests and callers that want the auto-selected backend.
    """
    global _DEFAULT_DISPATCHER
    if _DEFAULT_DISPATCHER is None:
        _DEFAULT_DISPATCHER = select_dispatcher()
    return _DEFAULT_DISPATCHER
