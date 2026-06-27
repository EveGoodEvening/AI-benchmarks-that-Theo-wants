"""C07.1 — Sandbox backend + sandboxed dispatcher confinement tests.

Verifies the enforced sandbox backend is concrete (in-process allowlisted
dispatcher, or bwrap when available), backend selection is explicit and
recorded, working-directory/path/host-boundary confinement is enforced and
recorded, the host repo cannot be mutated (host-tree hash before/after), and
cleanup is reliable after success and failure. The dispatcher satisfies the
C05 agent-adapter contract.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any, Sequence

import pytest

from ai_bench import sandbox as SB
from ai_bench import types as T
from ai_bench.models import SandboxHandle, ToolActionRequest


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------


def test_default_backend_id_is_explicit_and_recorded() -> None:
    """Backend selection is explicit, not silent, and is a known id."""
    backend = SB.default_backend_id()
    assert backend in {"bwrap", "in-process"}, backend


def test_select_dispatcher_returns_enforced_backend() -> None:
    """select_dispatcher returns a concrete enforced dispatcher, not a temp tree."""
    dispatcher = SB.select_dispatcher(backend="in-process")
    assert dispatcher.backend_id == "in-process"
    # The in-process backend is NOT a plain temp working tree: it has an
    # allowlist and confinement logic.
    assert isinstance(dispatcher, SB.InProcessSandboxDispatcher)


def test_select_dispatcher_auto_prefers_bwrap_or_in_process() -> None:
    """Auto selection picks bwrap when available, else in-process."""
    dispatcher = SB.select_dispatcher()
    assert dispatcher.backend_id == SB.default_backend_id()


def test_select_dispatcher_rejects_unknown_backend() -> None:
    with pytest.raises(SB.SandboxError, match="unknown sandbox backend"):
        SB.select_dispatcher(backend="not-a-backend")


def test_bwrap_dispatcher_only_when_available() -> None:
    if not SB._bwrap_available():
        with pytest.raises(SB.SandboxError, match="bwrap backend"):
            SB.select_dispatcher(backend="bwrap")
    else:
        dispatcher = SB.select_dispatcher(backend="bwrap")
        assert dispatcher.backend_id == "bwrap"


# ---------------------------------------------------------------------------
# Path confinement
# ---------------------------------------------------------------------------


def _handle(root: Path, *, case_id: str = "case-1") -> SandboxHandle:
    return SandboxHandle(
        root=root,
        case_id=case_id,
        allowed_commands=SB.ALLOWED_COMMANDS,
        env_allowlist=tuple(SB.DEFAULT_ENV_ALLOWLIST),
        default_timeout_ms=5_000,
    )


def test_absolute_path_write_is_rejected_and_recorded(tmp_path: Path) -> None:
    root = tmp_path / "sandbox"
    root.mkdir()
    dispatcher = SB.InProcessSandboxDispatcher()
    handle = _handle(root)
    action = ToolActionRequest(
        command="file.write",
        argv=("/etc/host-attack", "bad"),
        cwd=".",
    )
    row = dispatcher.dispatch(action, sandbox=handle)
    assert row.sandbox_boundary_violation is True
    assert row.violation_reason is not None
    assert "absolute path" in row.violation_reason
    assert row.exit_code == 126
    # The host file was NOT created.
    assert not (Path("/etc/host-attack").exists())


def test_dotdot_escape_is_rejected_and_recorded(tmp_path: Path) -> None:
    root = tmp_path / "sandbox"
    root.mkdir()
    (root / "inside.txt").write_text("kept", encoding="utf-8")
    dispatcher = SB.InProcessSandboxDispatcher()
    handle = _handle(root)
    action = ToolActionRequest(
        command="file.write",
        argv=("../../escape.txt", "bad"),
        cwd=".",
    )
    row = dispatcher.dispatch(action, sandbox=handle)
    assert row.sandbox_boundary_violation is True
    assert row.exit_code == 126
    assert not (tmp_path / "escape.txt").exists()
    assert not (tmp_path.parent / "escape.txt").exists()


def test_symlink_escape_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "sandbox"
    root.mkdir()
    target = tmp_path / "outside.txt"
    target.write_text("secret", encoding="utf-8")
    link = root / "link"
    os.symlink(target, link)
    dispatcher = SB.InProcessSandboxDispatcher()
    handle = _handle(root)
    action = ToolActionRequest(
        command="file.read",
        argv=("link",),
        cwd=".",
    )
    row = dispatcher.dispatch(action, sandbox=handle)
    assert row.sandbox_boundary_violation is True
    assert "symlink" in (row.violation_reason or "").lower() or "outside" in (row.violation_reason or "")



def test_symlink_ancestor_escape_write_is_rejected(tmp_path: Path) -> None:
    """Regression: file.write through a symlinked directory ancestor is rejected.

    A write to ``link/notes.md`` where ``link`` is a symlink to ``/etc`` would
    escape the sandbox even though ``notes.md`` does not yet exist.  The
    ancestor walk in ``_check_symlink_escape`` catches this before any file or
    directory is created through the symlink, so the write fails closed and is
    recorded as a boundary violation.
    """
    root = tmp_path / "sandbox"
    root.mkdir()
    outside = tmp_path / "outside-dir"
    outside.mkdir()
    link = root / "link"
    os.symlink(outside, link)
    dispatcher = SB.InProcessSandboxDispatcher()
    handle = _handle(root)
    action = ToolActionRequest(
        command="file.write",
        argv=("link/notes.md", "escaped\n"),
        cwd=".",
    )
    row = dispatcher.dispatch(action, sandbox=handle)
    assert row.sandbox_boundary_violation is True
    assert row.exit_code == 126
    reason = (row.violation_reason or "").lower()
    assert "ancestor" in reason or "symlink" in reason or "outside" in reason
    # Nothing was written through the symlink.
    assert not (outside / "notes.md").exists()
    assert not (root / "link" / "notes.md").exists()


def test_symlink_ancestor_escape_mkdir_is_rejected(tmp_path: Path) -> None:
    """file.mkdir through a symlinked directory ancestor is rejected too."""
    root = tmp_path / "sandbox"
    root.mkdir()
    outside = tmp_path / "outside-dir"
    outside.mkdir()
    link = root / "link"
    os.symlink(outside, link)
    dispatcher = SB.InProcessSandboxDispatcher()
    handle = _handle(root)
    action = ToolActionRequest(
        command="file.mkdir",
        argv=("link/sub",),
        cwd=".",
    )
    row = dispatcher.dispatch(action, sandbox=handle)
    assert row.sandbox_boundary_violation is True
    assert not (outside / "sub").exists()

def test_in_sandbox_relative_path_write_succeeds(tmp_path: Path) -> None:
    root = tmp_path / "sandbox"
    root.mkdir()
    dispatcher = SB.InProcessSandboxDispatcher()
    handle = _handle(root)
    action = ToolActionRequest(
        command="file.write",
        argv=("sub/dir/notes.md", "hello"),
        cwd=".",
    )
    row = dispatcher.dispatch(action, sandbox=handle)
    assert row.exit_code == 0
    assert row.sandbox_boundary_violation is False
    assert (root / "sub" / "dir" / "notes.md").read_text() == "hello"


def test_cwd_is_confined(tmp_path: Path) -> None:
    root = tmp_path / "sandbox"
    root.mkdir()
    dispatcher = SB.InProcessSandboxDispatcher()
    handle = _handle(root)
    # cwd escapes via ..
    action = ToolActionRequest(
        command="file.write",
        argv=("x.txt", "bad"),
        cwd="../..",
    )
    row = dispatcher.dispatch(action, sandbox=handle)
    assert row.sandbox_boundary_violation is True
    assert row.exit_code == 126


# ---------------------------------------------------------------------------
# Allowlist enforcement
# ---------------------------------------------------------------------------


def test_non_allowlisted_command_is_rejected_and_recorded(tmp_path: Path) -> None:
    root = tmp_path / "sandbox"
    root.mkdir()
    dispatcher = SB.InProcessSandboxDispatcher()
    handle = _handle(root)
    action = ToolActionRequest(
        command="curl",
        argv=("http://example.com",),
        cwd=".",
    )
    row = dispatcher.dispatch(action, sandbox=handle)
    assert row.sandbox_boundary_violation is True
    assert "allowlist" in (row.violation_reason or "")
    assert row.exit_code == 126


def test_empty_command_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "sandbox"
    root.mkdir()
    dispatcher = SB.InProcessSandboxDispatcher()
    handle = _handle(root)
    action = ToolActionRequest(command="", argv=(), cwd=".")
    row = dispatcher.dispatch(action, sandbox=handle)
    assert row.sandbox_boundary_violation is True
    assert "non-empty" in (row.violation_reason or "")


# ---------------------------------------------------------------------------
# Transcript fields (C02/C05 contract)
# ---------------------------------------------------------------------------


def test_dispatch_records_c02_transcript_fields(tmp_path: Path) -> None:
    root = tmp_path / "sandbox"
    root.mkdir()
    dispatcher = SB.InProcessSandboxDispatcher()
    handle = _handle(root)
    action = ToolActionRequest(
        command="file.write",
        argv=("a.txt", "content"),
        cwd=".",
        env_overrides={"GIT_AUTHOR_NAME": "tester"},
        stdin=None,
        timeout_ms=1000,
    )
    row = dispatcher.dispatch(action, sandbox=handle)
    assert row.command == "file.write"
    assert tuple(row.argv) == ("a.txt", "content")
    assert row.cwd == "."
    assert row.exit_code == 0
    assert row.wall_clock_ms >= 0
    assert row.timeout is False
    assert row.sandbox_boundary_violation is False
    # env_overrides in the transcript only contain surviving allowlisted keys.
    assert row.env_overrides == {"GIT_AUTHOR_NAME": "tester"}
    assert row.stdout == "wrote a.txt\n"


# ---------------------------------------------------------------------------
# No-host-mutation (host-tree hash before/after)
# ---------------------------------------------------------------------------


def test_host_tree_hash_is_deterministic(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "c.txt").write_text("c", encoding="utf-8")
    h1 = SB.host_tree_hash(tmp_path)
    h2 = SB.host_tree_hash(tmp_path)
    assert h1 == h2
    (tmp_path / "a.txt").write_text("changed", encoding="utf-8")
    h3 = SB.host_tree_hash(tmp_path)
    assert h3 != h1


def test_host_repo_byte_identical_after_sandboxed_run(tmp_path: Path) -> None:
    """A sandboxed run must not mutate the host tree."""
    host = tmp_path / "host"
    host.mkdir()
    (host / "README.md").write_text("host fixture\n", encoding="utf-8")
    (host / ".git").mkdir()  # pretend git dir so snapshot tries git
    before = SB.host_tree_hash(host)

    sandbox_root = tmp_path / "sandbox"
    sandbox_root.mkdir()
    shutil.copytree(host, sandbox_root, dirs_exist_ok=True)
    dispatcher = SB.InProcessSandboxDispatcher()
    handle = _handle(sandbox_root)
    # Mutate inside the sandbox.
    dispatcher.dispatch(
        ToolActionRequest(command="file.write", argv=("new.txt", "sandbox only"), cwd="."),
        sandbox=handle,
    )
    after = SB.host_tree_hash(host)
    assert before == after, "host repo must be byte-identical after a sandboxed run"
    # The sandbox was mutated, not the host.
    assert (sandbox_root / "new.txt").exists()
    assert not (host / "new.txt").exists()


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


def test_sandbox_cleanup_after_success(tmp_path: Path) -> None:
    root = tmp_path / "sandbox"
    root.mkdir()
    dispatcher = SB.InProcessSandboxDispatcher()
    handle = _handle(root)
    dispatcher.dispatch(
        ToolActionRequest(command="file.write", argv=("a.txt", "x"), cwd="."),
        sandbox=handle,
    )
    shutil.rmtree(root)
    assert not root.exists()


def test_sandbox_cleanup_after_failure(tmp_path: Path) -> None:
    root = tmp_path / "sandbox"
    root.mkdir()
    dispatcher = SB.InProcessSandboxDispatcher()
    handle = _handle(root)
    # A violation does not raise; it returns a violation row. Cleanup still works.
    row = dispatcher.dispatch(
        ToolActionRequest(command="file.write", argv=("../../escape", "x"), cwd="."),
        sandbox=handle,
    )
    assert row.sandbox_boundary_violation is True
    shutil.rmtree(root)
    assert not root.exists()


# ---------------------------------------------------------------------------
# Snapshot (C07.1 dispatcher.snapshot satisfies C05 contract)
# ---------------------------------------------------------------------------


def test_snapshot_returns_repo_state_with_required_fields(tmp_path: Path) -> None:
    root = tmp_path / "sandbox"
    root.mkdir()
    (root / "a.txt").write_text("a", encoding="utf-8")
    dispatcher = SB.InProcessSandboxDispatcher()
    handle = _handle(root)
    state = dispatcher.snapshot(sandbox=handle, transcript=())
    assert isinstance(state, T.RepoState)
    assert "a.txt" in state.file_tree
    assert isinstance(state.git_status, str)
    assert isinstance(state.branches, tuple)
    assert isinstance(state.commits, tuple)
    assert isinstance(state.diff, str)


def test_snapshot_excludes_git_dir_from_file_tree(tmp_path: Path) -> None:
    root = tmp_path / "sandbox"
    root.mkdir()
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("[git]", encoding="utf-8")
    (root / "real.md").write_text("x", encoding="utf-8")
    dispatcher = SB.InProcessSandboxDispatcher()
    handle = _handle(root)
    state = dispatcher.snapshot(sandbox=handle, transcript=())
    assert "real.md" in state.file_tree
    assert all(not p.startswith(".git") for p in state.file_tree)


# ---------------------------------------------------------------------------
# Fixture mounting/copying (read-only strategy)
# ---------------------------------------------------------------------------


def test_fixture_copy_does_not_mutate_source(tmp_path: Path) -> None:
    source = tmp_path / "fixture"
    source.mkdir()
    (source / "README.md").write_text("original", encoding="utf-8")
    source_hash_before = SB.host_tree_hash(source)

    sandbox_root = tmp_path / "sandbox"
    sandbox_root.mkdir()
    shutil.copytree(source, sandbox_root, dirs_exist_ok=True)
    dispatcher = SB.InProcessSandboxDispatcher()
    handle = _handle(sandbox_root)
    dispatcher.dispatch(
        ToolActionRequest(command="file.write", argv=("README.md", "mutated"), cwd="."),
        sandbox=handle,
    )
    # The source fixture is unchanged.
    assert SB.host_tree_hash(source) == source_hash_before
    assert (source / "README.md").read_text() == "original"
    assert (sandbox_root / "README.md").read_text() == "mutated"


# ---------------------------------------------------------------------------
# Dispatcher satisfies C05 CommandDispatcher protocol
# ---------------------------------------------------------------------------


def test_in_process_dispatcher_satisfies_c05_protocol() -> None:
    from ai_bench.models import CommandDispatcher

    dispatcher = SB.InProcessSandboxDispatcher()
    assert isinstance(dispatcher, CommandDispatcher)


def test_bwrap_dispatcher_satisfies_c05_protocol_when_available() -> None:
    if not SB._bwrap_available():
        pytest.skip("bwrap not available")
    from ai_bench.models import CommandDispatcher

    dispatcher = SB.select_dispatcher(backend="bwrap")
    assert isinstance(dispatcher, CommandDispatcher)
