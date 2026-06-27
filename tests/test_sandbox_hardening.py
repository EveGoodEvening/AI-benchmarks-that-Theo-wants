"""C07.3 — Network/env/credential/resource-limit hardening tests.

Verifies the enforced sandbox security posture (not just documented): no
outbound network, no inherited credentials, timeouts/resource limits applied,
and every boundary violation is recorded in the run-record transcript with the
``sandbox_boundary_violation`` flag and a reason. Every required acceptance
test fails closed and is recorded.
"""

from __future__ import annotations
import os
import resource
from pathlib import Path
from typing import Any, Sequence

import pytest
import yaml

from ai_bench import sandbox as SB
from ai_bench.models import SandboxHandle, ToolActionRequest


def _handle(root: Path, *, case_id: str = "case-1", timeout_ms: int = 5_000) -> SandboxHandle:
    return SandboxHandle(
        root=root,
        case_id=case_id,
        allowed_commands=SB.ALLOWED_COMMANDS,
        env_allowlist=tuple(SB.DEFAULT_ENV_ALLOWLIST),
        default_timeout_ms=timeout_ms,
    )


def _dispatch(
    root: Path,
    command: str,
    argv: Sequence[str] = (),
    *,
    cwd: str = ".",
    env_overrides: dict[str, str] | None = None,
    timeout_ms: int | None = None,
) -> Any:
    dispatcher = SB.InProcessSandboxDispatcher()
    handle = _handle(root)
    action = ToolActionRequest(
        command=command,
        argv=tuple(argv),
        cwd=cwd,
        env_overrides=env_overrides or {},
        timeout_ms=timeout_ms,
    )
    return dispatcher.dispatch(action, sandbox=handle)


# ---------------------------------------------------------------------------
# Network denial
# ---------------------------------------------------------------------------


def test_git_fetch_denied_and_recorded(tmp_path: Path) -> None:
    root = tmp_path / "sandbox"
    root.mkdir()
    row = _dispatch(root, "git", ("fetch", "origin"))
    assert row.sandbox_boundary_violation is True
    assert "network" in (row.violation_reason or "").lower()
    assert row.exit_code == 126


def test_git_clone_denied_and_recorded(tmp_path: Path) -> None:
    root = tmp_path / "sandbox"
    root.mkdir()
    row = _dispatch(root, "git", ("clone", "https://example.com/repo.git"))
    assert row.sandbox_boundary_violation is True
    assert "network" in (row.violation_reason or "").lower()


def test_git_push_denied_and_recorded(tmp_path: Path) -> None:
    root = tmp_path / "sandbox"
    root.mkdir()
    row = _dispatch(root, "git", ("push", "origin", "main"))
    assert row.sandbox_boundary_violation is True
    assert "network" in (row.violation_reason or "").lower()


def test_git_pull_denied_and_recorded(tmp_path: Path) -> None:
    root = tmp_path / "sandbox"
    root.mkdir()
    row = _dispatch(root, "git", ("pull",))
    assert row.sandbox_boundary_violation is True
    assert "network" in (row.violation_reason or "").lower()


def test_git_url_argument_denied_and_recorded(tmp_path: Path) -> None:
    root = tmp_path / "sandbox"
    root.mkdir()
    row = _dispatch(root, "git", ("fetch", "https://example.com/repo.git"))
    assert row.sandbox_boundary_violation is True
    assert "network" in (row.violation_reason or "").lower()


def test_git_ssh_url_denied_and_recorded(tmp_path: Path) -> None:
    root = tmp_path / "sandbox"
    root.mkdir()
    row = _dispatch(root, "git", ("clone", "git@github.com:foo/bar.git"))
    assert row.sandbox_boundary_violation is True
    assert "network" in (row.violation_reason or "").lower()


# ---------------------------------------------------------------------------
# Git argv safe-subcommand/option allowlist (C07 review)
# ---------------------------------------------------------------------------


def test_git_global_c_alias_shell_escape_denied(tmp_path: Path) -> None:
    """Regression: ``git -c alias.x='!sh -c ...'`` must not reach host git.

    A global ``-c`` option before the subcommand can define an alias whose
    expansion runs an arbitrary shell command.  The allowlist rejects every
    pre-subcommand option, so this config-injection / shell-escape vector is
    blocked before git is ever invoked.
    """
    root = tmp_path / "sandbox"
    root.mkdir()
    row = _dispatch(
        root,
        "git",
        ("-c", "alias.pwn=!sh -c 'touch /etc/pwned'", "pwn"),
    )
    assert row.sandbox_boundary_violation is True
    assert row.exit_code == 126
    reason = (row.violation_reason or "").lower()
    assert "forbidden" in reason or "-c" in reason or "global" in reason


def test_git_global_c_config_injection_denied(tmp_path: Path) -> None:
    """``git -c core.sshCommand=...`` is rejected as a forbidden global option."""
    root = tmp_path / "sandbox"
    root.mkdir()
    row = _dispatch(
        root,
        "git",
        ("-c", "core.sshCommand=sh", "status"),
    )
    assert row.sandbox_boundary_violation is True
    assert row.exit_code == 126
    assert "forbidden" in (row.violation_reason or "").lower()


def test_git_no_pre_subcommand_options_allowed(tmp_path: Path) -> None:
    """Any option before the subcommand is rejected, even benign-looking ones."""
    root = tmp_path / "sandbox"
    root.mkdir()
    row = _dispatch(root, "git", ("--git-dir", "/tmp/x", "status"))
    assert row.sandbox_boundary_violation is True
    assert row.exit_code == 126


def test_git_disallowed_subcommand_denied(tmp_path: Path) -> None:
    """Subcommands outside the safe set (e.g. ``submodule``) are rejected."""
    root = tmp_path / "sandbox"
    root.mkdir()
    row = _dispatch(root, "git", ("submodule", "update", "--init"))
    assert row.sandbox_boundary_violation is True
    assert "allowlist" in (row.violation_reason or "").lower()


def test_git_unvetted_option_after_subcommand_denied(tmp_path: Path) -> None:
    """An option not in the per-subcommand allowlist is rejected."""
    root = tmp_path / "sandbox"
    root.mkdir()
    row = _dispatch(root, "git", ("status", "--bogus-option"))
    assert row.sandbox_boundary_violation is True
    assert "allowlist" in (row.violation_reason or "").lower()


def test_git_forbidden_option_after_subcommand_denied(tmp_path: Path) -> None:
    """A forbidden option (e.g. ``--exec``) after the subcommand is rejected."""
    root = tmp_path / "sandbox"
    root.mkdir()
    row = _dispatch(root, "git", ("log", "--exec", "/bin/sh"))
    assert row.sandbox_boundary_violation is True
    assert "forbidden" in (row.violation_reason or "").lower()


def test_git_safe_subcommand_with_safe_options_passes_allowlist(tmp_path: Path) -> None:
    """A safe subcommand with allowlisted options is not rejected by the allowlist.

    This guards against the allowlist becoming too tight and breaking the
    legitimate fixture scripts (status --short, add, commit -m, init -q -b).
    """
    root = tmp_path / "sandbox"
    root.mkdir()
    # These should pass the allowlist (git may then fail on an empty repo, but
    # the violation flag must be False -- the allowlist did not reject them).
    for argv in [
        ("init", "-q", "-b", "main"),
        ("config", "user.name", "fixture"),
        ("status", "--short"),
        ("add", "README.md"),
        ("commit", "-m", "add notes"),
        ("log", "--oneline"),
    ]:
        row = _dispatch(root, "git", argv)
        assert not row.sandbox_boundary_violation, (
            f"{argv}: allowlist rejected a safe command: {row.violation_reason}"
        )


def test_bwrap_backend_does_not_share_host_network(tmp_path: Path) -> None:
    """The bwrap backend must not pass ``--share-net``; network is unshared.

    This is a static guard over the constructed bwrap argv so it holds even in
    environments where ``bwrap`` is not installed.  ``--unshare-all`` creates
    an empty network namespace; ``--share-net`` would re-share the host net
    namespace and MUST NOT appear.
    """
    import inspect
    src = inspect.getsource(SB.BwrapSandboxDispatcher._dispatch_bwrap_git)
    assert "--share-net" not in src, (
        "bwrap backend must not share the host network namespace "
        "(--share-net present)"
    )
    assert "--unshare-all" in src, (
        "bwrap backend must unshare namespaces including network"
    )


def test_bwrap_backend_validates_git_argv_before_invoke(tmp_path: Path) -> None:
    """The bwrap backend uses the same allowlist chokepoint as in-process."""
    import inspect
    src = inspect.getsource(SB.BwrapSandboxDispatcher._dispatch_bwrap_git)
    assert "_validate_git_argv" in src, (
        "bwrap backend must validate git argv through _validate_git_argv"
    )



# ---------------------------------------------------------------------------
# C07 second-pass: git config key confinement, path-operand confinement,
# rebase -x/--exec shell-escape removal, and bwrap BoundaryViolation capture.
# ---------------------------------------------------------------------------


def test_git_config_dangerous_keys_denied_and_recorded(tmp_path: Path) -> None:
    """``git config`` is constrained to ``user.name``/``user.email`` only.

    Dangerous config keys that arm a follow-up git invocation with an external
    helper, pager, editor, hook path, or alias shell escape are rejected at
    the allowlist chokepoint and recorded as boundary violations.
    """
    root = tmp_path / "sandbox"
    root.mkdir()
    for key in [
        "diff.external", "core.pager", "core.editor", "credential.helper",
        "core.hooksPath", "alias.x", "core.sshCommand", "core.askpass",
        "gc.auto", "filter.lfs.clean",
    ]:
        row = _dispatch(root, "git", ("config", key, "malicious"))
        assert row.sandbox_boundary_violation is True, (
            f"config {key}: expected boundary violation, got "
            f"{row.violation_reason!r}"
        )
        assert row.exit_code == 126
        assert "safe-key" in (row.violation_reason or "").lower() or key in (
            row.violation_reason or ""
        ), f"config {key}: reason {row.violation_reason!r}"


def test_git_config_safe_keys_pass_allowlist(tmp_path: Path) -> None:
    """Only ``user.name``/``user.email`` config keys pass the allowlist."""
    root = tmp_path / "sandbox"
    root.mkdir()
    for argv in [
        ("config", "user.name", "fixture"),
        ("config", "user.email", "fixture@ai-bench.local"),
        ("config", "--local", "user.name", "fixture"),
        ("config", "--get", "user.name"),
        ("config", "--list"),
    ]:
        row = _dispatch(root, "git", argv)
        assert not row.sandbox_boundary_violation, (
            f"{argv}: safe config rejected by allowlist: {row.violation_reason}"
        )


def test_git_config_global_system_scope_denied(tmp_path: Path) -> None:
    """``--global``/``--system`` config scopes reach host config and are denied."""
    root = tmp_path / "sandbox"
    root.mkdir()
    for opt in ("--global", "--system"):
        row = _dispatch(root, "git", ("config", opt, "user.name", "x"))
        assert row.sandbox_boundary_violation is True, (
            f"config {opt}: expected violation, got {row.violation_reason!r}"
        )
        assert "allowlist" in (row.violation_reason or "").lower()


def test_git_config_diff_external_with_diff_subcommand_still_confined(
    tmp_path: Path,
) -> None:
    """Regression: ``diff.external`` cannot be armed via config and then used.

    The config key is rejected at the allowlist, so a subsequent ``git diff``
    cannot invoke an external diff helper.  This test pins the config-side
    half of the ``diff.external`` + ``diff`` regression pair.
    """
    root = tmp_path / "sandbox"
    root.mkdir()
    row = _dispatch(root, "git", ("config", "diff.external", "/bin/echo"))
    assert row.sandbox_boundary_violation is True
    assert "diff.external" in (row.violation_reason or "")
    # And the bare diff subcommand itself must not be flagged as a violation
    # (it is a safe read-only inspection subcommand).
    row = _dispatch(root, "git", ("diff", "--stat"))
    assert not row.sandbox_boundary_violation, (
        f"git diff --stat flagged as violation: {row.violation_reason}"
    )


def test_git_relative_path_operand_dotdot_escape_denied(tmp_path: Path) -> None:
    """Relative git path operands with ``..`` that escape the sandbox are denied.

    Covers ``config --file ../host.cfg``, ``diff --no-index ../outside``, and
    ``init ../escape`` from the C07 second-pass findings.
    """
    root = tmp_path / "sandbox"
    root.mkdir()
    (root / "sub").mkdir()
    (root / "sibling").mkdir()
    for argv, cwd in [
        (("config", "--file", "../host.cfg", "user.name"), "."),
        (("diff", "--no-index", "../outside", "inside"), "."),
        (("init", "../escape"), "."),
        (("add", "../escape"), "."),
        (("commit", "-F", "../escape"), "."),
        (("add", "../../etc"), "sub"),
    ]:
        row = _dispatch(root, "git", argv, cwd=cwd)
        assert row.sandbox_boundary_violation is True, (
            f"{argv} cwd={cwd}: expected escape violation, got "
            f"{row.violation_reason!r}"
        )
        assert row.exit_code == 126
        assert "escape" in (row.violation_reason or "").lower() or ".." in (
            row.violation_reason or ""
        ), f"{argv}: reason {row.violation_reason!r}"


def test_git_in_sandbox_dotdot_traversal_allowed(tmp_path: Path) -> None:
    """In-sandbox ``..`` traversals that stay under root are NOT rejected.

    ``add ../sibling/file`` from a subdirectory whose ``..`` stays inside the
    sandbox root must pass confinement (git may then fail, but not with a
    boundary violation).  This guards against the confinement becoming too
    tight and breaking legitimate in-sandbox relative paths.
    """
    root = tmp_path / "sandbox"
    root.mkdir()
    (root / "sub").mkdir()
    (root / "sibling").mkdir()
    row = _dispatch(root, "git", ("add", "../sibling/file"), cwd="sub")
    assert not row.sandbox_boundary_violation, (
        f"in-sandbox ../sibling/file rejected: {row.violation_reason}"
    )


def test_git_non_path_option_value_not_confined(tmp_path: Path) -> None:
    """Non-path option values (e.g. ``commit -m``) are not treated as paths.

    A commit message containing ``..`` must NOT be confined as a path operand;
    only path-taking option values and positional path operands are confined.
    """
    root = tmp_path / "sandbox"
    root.mkdir()
    for argv in [
        ("commit", "-m", "../notes"),
        ("commit", "--message=../notes"),
        ("rebase", "--onto", "main", "topic"),
        ("checkout", "-b", "../branch"),
        ("blame", "-L", "1,10", "file"),
    ]:
        row = _dispatch(root, "git", argv)
        assert not row.sandbox_boundary_violation, (
            f"{argv}: non-path value confined as path: {row.violation_reason}"
        )


def test_git_path_taking_option_value_confined(tmp_path: Path) -> None:
    """Path-taking option values (``-F``, ``--file``, ``--separate-git-dir``) are confined."""
    root = tmp_path / "sandbox"
    root.mkdir()
    for argv in [
        ("commit", "-F", "../escape"),
        ("tag", "-F", "../escape"),
        ("merge", "-F", "../escape"),
        ("init", "--separate-git-dir", "../escape"),
        ("mv", "--pathspec-from-file", "../escape"),
        ("reset", "--pathspec-from-file", "../escape"),
        ("ls-files", "--exclude-from", "../escape"),
    ]:
        row = _dispatch(root, "git", argv)
        assert row.sandbox_boundary_violation is True, (
            f"{argv}: path-taking option value escape not caught: "
            f"{row.violation_reason!r}"
        )


def test_git_rebase_exec_short_option_denied(tmp_path: Path) -> None:
    """``git rebase -x <cmd>`` runs a shell command per commit and is denied."""
    root = tmp_path / "sandbox"
    root.mkdir()
    row = _dispatch(root, "git", ("rebase", "-x", "sh -c 'evil'"))
    assert row.sandbox_boundary_violation is True
    assert row.exit_code == 126
    assert "allowlist" in (row.violation_reason or "").lower()


def test_git_rebase_exec_long_option_denied(tmp_path: Path) -> None:
    """``git rebase --exec <cmd>`` is a forbidden shell-exec option."""
    root = tmp_path / "sandbox"
    root.mkdir()
    row = _dispatch(root, "git", ("rebase", "--exec", "evil"))
    assert row.sandbox_boundary_violation is True
    assert "forbidden" in (row.violation_reason or "").lower()


def test_git_cherry_pick_x_not_treated_as_exec(tmp_path: Path) -> None:
    """``git cherry-pick -x`` appends a message, not shell exec; it must pass.

    Guards against over-broad removal of ``-x``: only ``rebase -x`` is exec.
    """
    root = tmp_path / "sandbox"
    root.mkdir()
    row = _dispatch(root, "git", ("cherry-pick", "-x", "abc"))
    assert not row.sandbox_boundary_violation, (
        f"cherry-pick -x flagged as exec: {row.violation_reason}"
    )


def test_bwrap_backend_catches_boundary_violation(tmp_path: Path) -> None:
    """The bwrap backend records a BoundaryViolation as a transcript row.

    A path-operand escape raises ``BoundaryViolation`` from the shared
    ``_confine_git_path_args`` chokepoint; the bwrap backend MUST catch it and
    return a violation row instead of propagating out of ``dispatch`` and
    crashing the runner.  Verified without a real ``bwrap`` install by
    stubbing availability: the violation is raised BEFORE any subprocess.
    """
    root = tmp_path / "sandbox"
    root.mkdir()
    handle = _handle(root)
    action = ToolActionRequest(
        command="git",
        argv=("add", "../escape"),
        cwd=".",
        env_overrides={},
        timeout_ms=None,
    )
    orig = SB._bwrap_available
    SB._bwrap_available = lambda: True
    try:
        dispatcher = SB.BwrapSandboxDispatcher()
        row = dispatcher.dispatch(action, sandbox=handle)
    finally:
        SB._bwrap_available = orig
    assert row.sandbox_boundary_violation is True, (
        f"bwrap did not record BoundaryViolation as a row: {row.violation_reason!r}"
    )
    assert row.exit_code == 126
    assert "escape" in (row.violation_reason or "").lower()


def test_bwrap_backend_uses_path_confinement_chokepoint(tmp_path: Path) -> None:
    """The bwrap backend confines git path operands through the shared chokepoint."""
    import inspect
    src = inspect.getsource(SB.BwrapSandboxDispatcher._dispatch_bwrap_git)
    assert "_confine_git_path_args" in src, (
        "bwrap backend must confine git path operands via _confine_git_path_args"
    )
    assert "BoundaryViolation" in src, (
        "bwrap backend must catch BoundaryViolation and return a violation row"
    )

# ---------------------------------------------------------------------------
# Environment / credential stripping
# ---------------------------------------------------------------------------


def test_sanitize_env_clears_inherited_and_allowlists() -> None:
    root = Path("/tmp/sandbox-test")
    cfg = SB.SandboxConfig()
    env = SB.sanitize_env(
        {
            "PATH": "/usr/bin:/bin",
            "HOME": "/home/host-user",
            "AWS_ACCESS_KEY_ID": "AKIAHOSTSECRET",
            "GITHUB_TOKEN": "ghp_hosttoken",
            "SSH_AUTH_SOCK": "/tmp/host-ssh",
            "RANDOM_HOST_VAR": "should-be-dropped",
            "LANG": "C.UTF-8",
        },
        sandbox_root=root,
        config=cfg,
    )
    assert "AWS_ACCESS_KEY_ID" not in env
    assert "GITHUB_TOKEN" not in env
    assert "SSH_AUTH_SOCK" not in env
    assert "RANDOM_HOST_VAR" not in env
    # HOME is rewritten into the sandbox.
    assert env["HOME"] == str(root)
    # Allowlisted vars survive.
    assert env["PATH"] == "/usr/bin:/bin"
    assert env["LANG"] == "C.UTF-8"
    # Git config isolation is set.
    assert env["GIT_CONFIG_NOSYSTEM"] == "1"
    assert env["GIT_TERMINAL_PROMPT"] == "0"


def test_credential_env_overrides_stripped_and_recorded(tmp_path: Path) -> None:
    root = tmp_path / "sandbox"
    root.mkdir()
    row = _dispatch(
        root,
        "git",
        ("status",),
        env_overrides={"AWS_SECRET_ACCESS_KEY": "stolen", "GITHUB_TOKEN": "ghp_x"},
    )
    assert row.sandbox_boundary_violation is True
    assert "credential" in (row.violation_reason or "").lower()
    assert "AWS_SECRET_ACCESS_KEY" in (row.violation_reason or "")
    assert "GITHUB_TOKEN" in (row.violation_reason or "")


def test_non_allowlisted_env_override_dropped_silently(tmp_path: Path) -> None:
    root = tmp_path / "sandbox"
    root.mkdir()
    row = _dispatch(
        root,
        "git",
        ("status",),
        env_overrides={"UNRELATED_VAR": "dropped"},
    )
    # Non-credential, non-allowlisted overrides are dropped but NOT a violation.
    assert row.sandbox_boundary_violation is False
    assert "UNRELATED_VAR" not in row.env_overrides


def test_host_gitconfig_reference_denied_and_recorded(tmp_path: Path) -> None:
    root = tmp_path / "sandbox"
    root.mkdir()
    row = _dispatch(root, "git", ("config", "--file", "~/.gitconfig", "user.name"))
    assert row.sandbox_boundary_violation is True
    assert "credential" in (row.violation_reason or "").lower() or "gitconfig" in (row.violation_reason or "")


def test_host_ssh_path_reference_denied_and_recorded(tmp_path: Path) -> None:
    root = tmp_path / "sandbox"
    root.mkdir()
    row = _dispatch(root, "git", ("config", "--file", "~/.ssh/config", "core.sshCommand"))
    assert row.sandbox_boundary_violation is True


def test_host_aws_path_reference_denied_and_recorded(tmp_path: Path) -> None:
    root = tmp_path / "sandbox"
    root.mkdir()
    row = _dispatch(root, "git", ("config", "--file", "~/.aws/credentials", "user.name"))
    assert row.sandbox_boundary_violation is True


def test_absolute_git_arg_outside_sandbox_denied(tmp_path: Path) -> None:
    root = tmp_path / "sandbox"
    root.mkdir()
    row = _dispatch(root, "git", ("config", "--file", "/etc/gitconfig", "user.name"))
    assert row.sandbox_boundary_violation is True
    assert "absolute" in (row.violation_reason or "").lower() or "outside" in (row.violation_reason or "").lower()


# ---------------------------------------------------------------------------
# Timeouts / resource limits
# ---------------------------------------------------------------------------


def test_timeout_is_enforced_and_recorded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A long-running git action is killed and recorded as a timeout violation.

    Deterministic: this exercises the *real* timeout enforcement and recording
    path (``_handle_git`` -> ``subprocess.run(..., timeout=...)`` ->
    ``TimeoutExpired`` -> ``_timeout_row``) without betting on ``git log``
    being slower than a sub-millisecond wall-clock budget, which is unreliable
    on fast machines (fork/exec + a tiny repo can complete in ~3ms even with
    ``timeout_ms=1``).  Instead the test fakes ``subprocess.run`` in the
    ``ai_bench.sandbox`` module namespace: it asserts the requested timeout is
    propagated faithfully as a sub-second value (proving the enforcement
    wiring) and then raises ``subprocess.TimeoutExpired`` to deterministically
    drive the dispatcher's timeout-recording path.  The production code is
    unchanged and still uses the real ``subprocess.run`` timeout; no security
    posture is weakened.
    """
    import subprocess as _subprocess

    root = tmp_path / "sandbox"
    root.mkdir()
    _init_repo_with_commit(root)

    requested_timeout_ms = 1
    expected_timeout_s = max(requested_timeout_ms / 1000.0, 1e-6)
    captured: dict[str, Any] = {}

    def _fake_run(*args: Any, **kwargs: Any) -> Any:
        # Prove the timeout is wired through faithfully as a sub-second value
        # (the real enforcement path).  ``max(..., 1e-6)`` epsilon is the
        # dispatcher's own floor; assert it rather than a raw 0.001 so the
        # test tracks the production formula.
        captured["timeout"] = kwargs.get("timeout")
        assert kwargs.get("timeout") == expected_timeout_s, (
            f"timeout not propagated faithfully: expected {expected_timeout_s}, "
            f"got {kwargs.get('timeout')!r}"
        )
        raise _subprocess.TimeoutExpired(cmd=args[0] if args else "git", timeout=expected_timeout_s)

    monkeypatch.setattr(SB.subprocess, "run", _fake_run)

    row = _dispatch(root, "git", ("log", "--all"), timeout_ms=requested_timeout_ms)

    # The fake subprocess.run was actually called (enforcement path is live).
    assert captured.get("timeout") == expected_timeout_s
    assert row.timeout is True, (
        f"expected timeout violation, got exit={row.exit_code} "
        f"reason={row.violation_reason!r}"
    )
    assert row.sandbox_boundary_violation is True
    assert "timeout" in (row.violation_reason or "").lower()
    assert row.exit_code == 137


def test_cpu_resource_limit_applied(tmp_path: Path) -> None:
    """The dispatcher applies an RLIMIT_CPU limit during dispatch."""
    root = tmp_path / "sandbox"
    root.mkdir()
    cfg = SB.SandboxConfig(cpu_seconds=1)
    dispatcher = SB.InProcessSandboxDispatcher(cfg)
    handle = _handle(root)
    action = ToolActionRequest(command="file.write", argv=("a.txt", "x"), cwd=".")
    # The CPU limit is applied and restored; we assert it does not break
    # normal operations and is restored afterward.
    before = resource.getrlimit(resource.RLIMIT_CPU)
    row = dispatcher.dispatch(action, sandbox=handle)
    after = resource.getrlimit(resource.RLIMIT_CPU)
    assert row.exit_code == 0
    assert before == after, "RLIMIT_CPU must be restored after dispatch"


def test_file_write_size_limit_enforced(tmp_path: Path) -> None:
    """file.write exceeding the disk-write limit fails closed."""
    root = tmp_path / "sandbox"
    root.mkdir()
    cfg = SB.SandboxConfig(max_file_bytes=16)
    dispatcher = SB.InProcessSandboxDispatcher(cfg)
    handle = _handle(root)
    action = ToolActionRequest(
        command="file.write",
        argv=("big.txt", "x" * 32),
        cwd=".",
    )
    row = dispatcher.dispatch(action, sandbox=handle)
    assert row.exit_code != 0
    assert "max file bytes" in row.stderr
    assert not (root / "big.txt").exists()


# ---------------------------------------------------------------------------
# Boundary-violation recording (every violation recorded with a reason)
# ---------------------------------------------------------------------------


def test_every_violation_has_reason_and_flag(tmp_path: Path) -> None:
    root = tmp_path / "sandbox"
    root.mkdir()
    cases = [
        ("absolute path", ToolActionRequest(command="file.write", argv=("/etc/x", "bad"), cwd=".")),
        ("dotdot escape", ToolActionRequest(command="file.write", argv=("../../x", "bad"), cwd=".")),
        ("non-allowlisted", ToolActionRequest(command="curl", argv=("http://x",), cwd=".")),
        ("network git", ToolActionRequest(command="git", argv=("fetch",), cwd=".")),
        ("credential env", ToolActionRequest(command="git", argv=("status",), cwd=".", env_overrides={"AWS_TOKEN": "x"})),
    ]
    dispatcher = SB.InProcessSandboxDispatcher()
    handle = _handle(root)
    for label, action in cases:
        row = dispatcher.dispatch(action, sandbox=handle)
        assert row.sandbox_boundary_violation is True, f"{label}: violation flag not set"
        assert row.violation_reason, f"{label}: missing violation reason"
        assert row.exit_code in (126, 137), f"{label}: unexpected exit code {row.exit_code}"


def test_violation_does_not_raise_but_returns_record(tmp_path: Path) -> None:
    """Boundary violations fail closed (non-zero exit) without raising, so the
    run-record transcript captures them as data rather than aborting the run."""
    root = tmp_path / "sandbox"
    root.mkdir()
    dispatcher = SB.InProcessSandboxDispatcher()
    handle = _handle(root)
    action = ToolActionRequest(command="file.write", argv=("/etc/x", "bad"), cwd=".")
    row = dispatcher.dispatch(action, sandbox=handle)
    assert row.sandbox_boundary_violation is True
    assert row.exit_code == 126


# ---------------------------------------------------------------------------
# End-to-end: hardening violations recorded in a run-record transcript
# ---------------------------------------------------------------------------


def test_hardening_violations_recorded_in_run_record_transcript(tmp_path: Path) -> None:
    """A run with a script that attempts violations records them in the transcript."""
    from ai_bench import runner as R

    bdir = tmp_path / "hardening-benchmark"
    cases = bdir / "cases"
    cases.mkdir(parents=True)
    _write_yaml(
        bdir / "benchmark.yaml",
        {
            "schema_version": "1",
            "id": "harden-c07",
            "name": "Harden C07",
            "description": "C07.3 hardening fixture.",
            "domain": "tool-use",
            "task_type": "tool-task",
            "metric": {"verifier": "state_check", "params": {}},
            "version": "0.1.0",
            "contributor": {"name": "tests"},
            "license": "MIT",
            "case_glob": "cases/*.yaml",
            "tags": ["tool"],
            "status": "experimental",
        },
    )
    _write_yaml(
        cases / "case-1.yaml",
        {
            "schema_version": "1",
            "id": "case-1",
            "input": {
                "prompt": "Attempt violations.",
                "script": [
                    {"command": "git", "argv": ["fetch", "origin"], "cwd": "."},
                    {"command": "file.write", "argv": ["/etc/host-attack", "bad"], "cwd": "."},
                    {"command": "curl", "argv": ["http://example.com"], "cwd": "."},
                ],
            },
            "expected": "state-check-real",
            "tags": ["smoke"],
            "difficulty": "easy",
            "provenance": {"source": "original", "license": "MIT"},
            "state_check": {"git": {"status_clean": True}},
        },
    )

    output = tmp_path / "record.json"
    result = R.run_benchmark(
        bdir,
        output=output,
        model="stub",
        now=lambda: "2026-06-27T00:00:00Z",
    )
    transcript = result.record["cases"][0]["transcript"]
    violations = [a for a in transcript if a["sandbox_boundary_violation"]]
    assert len(violations) == 3, [a["violation_reason"] for a in transcript]
    reasons = " ".join(a["violation_reason"] or "" for a in violations)
    assert "network" in reasons.lower()
    assert "absolute" in reasons.lower() or "outside" in reasons.lower()
    assert "allowlist" in reasons.lower()
    # Every violation has a reason.
    assert all(a["violation_reason"] for a in violations)
    # The run-record is schema-valid (written).
    assert output.is_file()


# ---------------------------------------------------------------------------
# C07 final hardening: symlink escape on git path operands, HOME/PATH
# override rejection, signing/editor/verification/interactive/helper option
# removal, hooks disabling, and max_processes enforcement.
# ---------------------------------------------------------------------------


def test_git_path_operand_symlink_escape_denied(tmp_path: Path) -> None:
    """A git path operand that is a symlink escaping the sandbox is rejected.

    Regression for the C07 final-hardening finding that git path operands were
    only lexically confined: ``git config --file link`` where ``link`` is a
    symlink to a host file passes the lexical check (no ``..`` component) but
    would read a host file.  The symlink-escape check is now applied to every
    confined git path operand/option value.
    """
    root = tmp_path / "sandbox"
    root.mkdir()
    outside = tmp_path / "outside.cfg"
    outside.write_text("host", encoding="utf-8")
    link = root / "link"
    os.symlink(outside, link)
    row = _dispatch(root, "git", ("config", "--file", "link", "user.name"))
    assert row.sandbox_boundary_violation is True
    assert row.exit_code == 126
    reason = (row.violation_reason or "").lower()
    assert "symlink" in reason or "outside" in reason


def test_git_path_operand_symlink_ancestor_escape_denied(tmp_path: Path) -> None:
    """A git path operand through a symlinked directory ancestor is rejected."""
    root = tmp_path / "sandbox"
    root.mkdir()
    outside = tmp_path / "outside-dir"
    outside.mkdir()
    link = root / "link"
    os.symlink(outside, link)
    row = _dispatch(root, "git", ("config", "--file", "link/host.cfg", "user.name"))
    assert row.sandbox_boundary_violation is True
    reason = (row.violation_reason or "").lower()
    assert "ancestor" in reason or "symlink" in reason or "outside" in reason


def test_git_path_taking_option_symlink_value_confined(tmp_path: Path) -> None:
    """Path-taking option values that are escaping symlinks are confined."""
    root = tmp_path / "sandbox"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    link = root / "link"
    os.symlink(outside, link)
    for argv in [
        ("commit", "-F", "link/notes"),
        ("tag", "-F", "link/notes"),
        ("init", "--separate-git-dir", "link"),
    ]:
        row = _dispatch(root, "git", argv)
        assert row.sandbox_boundary_violation is True, (
            f"{argv}: symlink escape not caught: {row.violation_reason!r}"
        )


def test_git_in_sandbox_symlink_target_allowed(tmp_path: Path) -> None:
    """A symlink whose target stays inside the sandbox is NOT rejected."""
    root = tmp_path / "sandbox"
    root.mkdir()
    (root / "real").mkdir()
    (root / "real" / "f.txt").write_text("x", encoding="utf-8")
    link = root / "link"
    os.symlink(root / "real", link)
    # ``git status`` reading through an in-sandbox symlink must not be a
    # boundary violation (git may fail, but not with a violation).
    row = _dispatch(root, "git", ("status", "--porcelain"))
    assert not row.sandbox_boundary_violation, (
        f"in-sandbox symlink rejected: {row.violation_reason}"
    )


def test_home_env_override_rejected_as_boundary_violation(tmp_path: Path) -> None:
    """A HOME override is a boundary violation; HOME is fixed inside the sandbox."""
    root = tmp_path / "sandbox"
    root.mkdir()
    row = _dispatch(
        root, "git", ("status",), env_overrides={"HOME": "/home/attacker"}
    )
    assert row.sandbox_boundary_violation is True
    assert row.exit_code == 126
    assert "HOME" in (row.violation_reason or "")
    assert "boundary" in (row.violation_reason or "").lower()


def test_path_env_override_rejected_as_boundary_violation(tmp_path: Path) -> None:
    """A PATH override is a boundary violation; PATH is fixed to a trusted value."""
    root = tmp_path / "sandbox"
    root.mkdir()
    row = _dispatch(
        root, "git", ("status",),
        env_overrides={"PATH": "/home/attacker/bin"},
    )
    assert row.sandbox_boundary_violation is True
    assert "PATH" in (row.violation_reason or "")
    assert "boundary" in (row.violation_reason or "").lower()


def test_sanitize_env_path_is_fixed_trusted() -> None:
    """sanitize_env fixes PATH to /usr/bin:/bin regardless of base or override."""
    env = SB.sanitize_env(
        {"PATH": "/host/evil/bin", "HOME": "/host/home"},
        sandbox_root=Path("/tmp/sandbox"),
        config=SB.SandboxConfig(),
        overrides={"PATH": "/override/bin", "HOME": "/override/home"},
    )
    assert env["PATH"] == "/usr/bin:/bin"
    assert env["HOME"] == "/tmp/sandbox"


def test_git_tag_sign_option_denied(tmp_path: Path) -> None:
    """``git tag -s`` (signing) is removed from the allowlist."""
    root = tmp_path / "sandbox"
    root.mkdir()
    row = _dispatch(root, "git", ("tag", "-s", "-m", "x", "t"))
    assert row.sandbox_boundary_violation is True
    assert "allowlist" in (row.violation_reason or "").lower()


def test_git_tag_verify_option_denied(tmp_path: Path) -> None:
    """``git tag -v`` (verification) is removed from the allowlist."""
    root = tmp_path / "sandbox"
    root.mkdir()
    row = _dispatch(root, "git", ("tag", "-v", "t"))
    assert row.sandbox_boundary_violation is True
    assert "allowlist" in (row.violation_reason or "").lower()


def test_git_tag_edit_option_denied(tmp_path: Path) -> None:
    """``git tag -e`` (editor) is removed from the allowlist."""
    root = tmp_path / "sandbox"
    root.mkdir()
    row = _dispatch(root, "git", ("tag", "-e", "-a", "-m", "x", "t"))
    assert row.sandbox_boundary_violation is True


def test_git_tag_local_user_option_denied(tmp_path: Path) -> None:
    """``git tag -u`` (gpg helper) is removed from the allowlist."""
    root = tmp_path / "sandbox"
    root.mkdir()
    row = _dispatch(root, "git", ("tag", "-u", "key", "-a", "t"))
    assert row.sandbox_boundary_violation is True


def test_git_commit_edit_and_verify_options_denied(tmp_path: Path) -> None:
    """``git commit -e``/``--no-verify`` (editor/verification) are denied."""
    root = tmp_path / "sandbox"
    root.mkdir()
    for argv in [("commit", "-e", "-m", "x"), ("commit", "--no-verify", "-m", "x")]:
        row = _dispatch(root, "git", argv)
        assert row.sandbox_boundary_violation is True, (
            f"{argv}: editor/verify option not denied: {row.violation_reason!r}"
        )


def test_git_commit_signoff_option_denied(tmp_path: Path) -> None:
    """``git commit -s``/``--signoff`` (signing) is removed from the allowlist."""
    root = tmp_path / "sandbox"
    root.mkdir()
    for argv in [("commit", "-s", "-m", "x"), ("commit", "--signoff", "-m", "x")]:
        row = _dispatch(root, "git", argv)
        assert row.sandbox_boundary_violation is True, (
            f"{argv}: signoff option not denied: {row.violation_reason!r}"
        )


def test_git_merge_strategy_option_denied(tmp_path: Path) -> None:
    """``git merge -s``/``--strategy`` (external helper) is removed."""
    root = tmp_path / "sandbox"
    root.mkdir()
    for argv in [("merge", "-s", "ours"), ("merge", "--strategy=ours")]:
        row = _dispatch(root, "git", argv)
        assert row.sandbox_boundary_violation is True, (
            f"{argv}: strategy option not denied: {row.violation_reason!r}"
        )


def test_git_rebase_interactive_option_denied(tmp_path: Path) -> None:
    """``git rebase -i`` (interactive) is removed from the allowlist."""
    root = tmp_path / "sandbox"
    root.mkdir()
    row = _dispatch(root, "git", ("rebase", "-i", "main"))
    assert row.sandbox_boundary_violation is True


def test_git_add_interactive_option_denied(tmp_path: Path) -> None:
    """``git add -i``/``-p`` (interactive) is removed from the allowlist."""
    root = tmp_path / "sandbox"
    root.mkdir()
    for argv in [("add", "-i"), ("add", "-p"), ("add", "--interactive"), ("add", "--patch")]:
        row = _dispatch(root, "git", argv)
        assert row.sandbox_boundary_violation is True, (
            f"{argv}: interactive option not denied: {row.violation_reason!r}"
        )


def test_git_log_show_signature_option_denied(tmp_path: Path) -> None:
    """``git log --show-signature`` (verification) is removed from the allowlist."""
    root = tmp_path / "sandbox"
    root.mkdir()
    row = _dispatch(root, "git", ("log", "--show-signature"))
    assert row.sandbox_boundary_violation is True


def test_git_commit_message_option_still_allowed(tmp_path: Path) -> None:
    """Regression: benign commit options (-m) still pass the allowlist."""
    root = tmp_path / "sandbox"
    _init_repo_with_commit(root)
    row = _dispatch(root, "git", ("commit", "-m", "ok", "--allow-empty"))
    # git may succeed or fail (no upstream/etc.), but it must NOT be a
    # boundary violation from the allowlist.
    assert not row.sandbox_boundary_violation, (
        f"commit -m flagged as violation: {row.violation_reason}"
    )


def test_git_commit_hooks_disabled(tmp_path: Path) -> None:
    """Commit-producing commands disable hooks: an armed pre-commit hook cannot run.

    A ``.git/hooks/pre-commit`` program that would fail the commit is placed
    in the sandbox repo; because the dispatcher points ``core.hooksPath`` at
    an empty directory for commit-producing commands, the hook never runs and
    the commit succeeds (exit 0) rather than being blocked by the hook.
    """
    root = tmp_path / "sandbox"
    _init_repo_with_commit(root)
    hooks_dir = root / ".git" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook = hooks_dir / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    row = _dispatch(root, "git", ("commit", "--allow-empty", "-m", "no-hook"))
    assert not row.sandbox_boundary_violation, (
        f"commit flagged as violation: {row.violation_reason}"
    )
    assert row.exit_code == 0, (
        f"pre-commit hook ran (hooks not disabled): exit={row.exit_code} "
        f"stderr={row.stderr!r}"
    )


def test_git_non_commit_command_hooks_not_disabled(tmp_path: Path) -> None:
    """Non-commit-producing commands do not set the hooks-disable env addition."""
    root = tmp_path / "sandbox"
    root.mkdir()
    # ``git status`` is not commit-producing; the helper returns no additions.
    assert SB._hooks_disabled_env(root, "status") == {}
    assert SB._hooks_disabled_env(root, "commit") != {}


def test_max_processes_enforced_records_violation(tmp_path: Path) -> None:
    """The process-count cap is enforced: exceeding it records a boundary violation.

    ``max_processes`` is no longer merely declared; the dispatcher tracks
    active subprocesses and rejects a git action that would exceed the cap.
    We simulate a saturated cap by setting ``_active_processes`` to the cap
    before dispatching a git action.
    """
    root = tmp_path / "sandbox"
    root.mkdir()
    dispatcher = SB.InProcessSandboxDispatcher()
    dispatcher._active_processes = dispatcher.config.max_processes
    handle = _handle(root)
    action = ToolActionRequest(
        command="git", argv=("status",), cwd=".", env_overrides={},
        timeout_ms=None,
    )
    row = dispatcher.dispatch(action, sandbox=handle)
    assert row.sandbox_boundary_violation is True
    assert row.exit_code == 126
    assert "process-count cap" in (row.violation_reason or "")
    # The counter is restored (the rejected action did not decrement below 0).
    assert dispatcher._active_processes == dispatcher.config.max_processes


def test_max_processes_counter_restored_after_git(tmp_path: Path) -> None:
    """The active-process counter returns to 0 after a git action completes."""
    root = tmp_path / "sandbox"
    _init_repo_with_commit(root)
    dispatcher = SB.InProcessSandboxDispatcher()
    handle = _handle(root)
    action = ToolActionRequest(
        command="git", argv=("status", "--porcelain"), cwd=".",
        env_overrides={}, timeout_ms=None,
    )
    assert dispatcher._active_processes == 0
    dispatcher.dispatch(action, sandbox=handle)
    assert dispatcher._active_processes == 0


def test_git_positional_path_operand_symlink_escape_denied(tmp_path: Path) -> None:
    """A positional git path operand that is an escaping symlink is rejected.

    Regression for the C07 final-hardening finding that git path operands
    were only lexically confined: ``git add link`` where ``link`` is a
    symlink to a host file passes the lexical check (no ``..`` component)
    but would let git operate on a host path.  The symlink-escape check is
    applied to positional path operands (not just path-taking option
    values) for every subcommand except ``config``.
    """
    root = tmp_path / "sandbox"
    root.mkdir()
    outside = tmp_path / "outside-target"
    outside.mkdir()
    link = root / "link"
    os.symlink(outside, link)
    for argv in [("add", "link"), ("add", "link/inside")]:
        row = _dispatch(root, "git", argv)
        assert row.sandbox_boundary_violation is True, (
            f"{argv}: symlink escape not caught: {row.violation_reason!r}"
        )
        reason = (row.violation_reason or "").lower()
        assert "symlink" in reason or "outside" in reason or "ancestor" in reason


def test_bwrap_backend_enforces_max_processes(tmp_path: Path) -> None:
    """The bwrap backend enforces the process-count cap via the shared counter.

    The bwrap backend spawns one bwrap subprocess per git action; a
    concurrent caller that would exceed ``max_processes`` records a
    boundary violation instead of spawning an extra child.  The counter
    lives on the shared in-process inner dispatcher so both backends share
    one cap.  Verified without a real ``bwrap`` install by stubbing
    availability and saturating the cap: the violation is recorded BEFORE
    any subprocess is spawned.
    """
    root = tmp_path / "sandbox"
    root.mkdir()
    handle = _handle(root)
    action = ToolActionRequest(
        command="git", argv=("status",), cwd=".", env_overrides={},
        timeout_ms=None,
    )
    orig = SB._bwrap_available
    SB._bwrap_available = lambda: True
    try:
        dispatcher = SB.BwrapSandboxDispatcher()
        # Saturate the shared cap so the next git action must be rejected.
        dispatcher._inner._active_processes = dispatcher.config.max_processes
        row = dispatcher.dispatch(action, sandbox=handle)
    finally:
        SB._bwrap_available = orig
    assert row.sandbox_boundary_violation is True, (
        f"bwrap did not enforce process-count cap: {row.violation_reason!r}"
    )
    assert row.exit_code == 126
    assert "process-count cap" in (row.violation_reason or "")
    # The rejected action did not decrement the counter below the cap.
    assert dispatcher._inner._active_processes == dispatcher.config.max_processes


def test_bwrap_backend_counter_restored_after_boundary_violation(
    tmp_path: Path,
) -> None:
    """The bwrap counter is restored even when a BoundaryViolation is raised.

    A path-operand escape raises ``BoundaryViolation`` from the shared
    ``_confine_git_path_args`` chokepoint; the outer try/finally must
    decrement the active-process counter so the cap is not permanently
    consumed by a rejected action.  Verified without a real ``bwrap``
    install by stubbing availability.
    """
    root = tmp_path / "sandbox"
    root.mkdir()
    handle = _handle(root)
    action = ToolActionRequest(
        command="git", argv=("add", "../escape"), cwd=".",
        env_overrides={}, timeout_ms=None,
    )
    orig = SB._bwrap_available
    SB._bwrap_available = lambda: True
    try:
        dispatcher = SB.BwrapSandboxDispatcher()
        assert dispatcher._inner._active_processes == 0
        dispatcher.dispatch(action, sandbox=handle)
    finally:
        SB._bwrap_available = orig
    assert dispatcher._inner._active_processes == 0, (
        "bwrap counter not restored after BoundaryViolation"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_yaml(path: Path, data: Any) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _init_repo_with_commit(root: Path) -> None:
    """Initialize a real git repo with one commit so git commands do real work.

    The root directory is created (idempotently) so callers do not need to
    ``mkdir`` first; ``git init`` requires its cwd to already exist.
    """
    import subprocess
    root.mkdir(parents=True, exist_ok=True)
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(root),
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    subprocess.run(["git", "init", "-q"], cwd=root, env=env, check=True,
                   capture_output=True)
    (root / "f.txt").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "f.txt"], cwd=root, env=env, check=True,
                   capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=root, env=env,
                   check=True, capture_output=True)
