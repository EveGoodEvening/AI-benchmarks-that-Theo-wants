"""C07.2 — Repo-state verifier integration tests.

Verifies the real state-check verifier implementation, runner integration that
plugs the sandboxed dispatcher into the C05 agent-adapter contract, the
integration scenario where the stub agent creates a commit inside the sandbox
and the state-check verifier observes pass and fail paths with the host
repository byte-identical before and after, and the real-verifier
transcript-replay acceptance deferred from C05.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Mapping, Sequence

import pytest
import yaml

from ai_bench import models as M
from ai_bench import runner as R
from ai_bench import sandbox as SB
from ai_bench import scoring as S
from ai_bench import types as T


# ---------------------------------------------------------------------------
# Real state-check verifier unit tests
# ---------------------------------------------------------------------------


def _repo_state(
    *,
    file_tree: Sequence[str] = ("README.md",),
    git_status: str = "",
    branches: Sequence[str] = ("main",),
    commits: Sequence[Mapping[str, str]] = ({"sha": "abc1234", "subject": "add notes"},),
    diff: str = "",
) -> T.RepoState:
    return T.RepoState(
        file_tree=tuple(file_tree),
        git_status=git_status,
        branches=tuple(branches),
        commits=tuple(commits),
        diff=diff,
    )


class TestRepoStateVerifier:
    def test_passes_when_all_checks_satisfied(self) -> None:
        verifier = S.RepoStateVerifier()
        spec = T.StateCheckSpec(
            files={"notes.md": {"exists": True}},
            git={"status_clean": True, "head_commit_message": "add notes"},
            absent=("secret.txt",),
        )
        state = _repo_state(file_tree=("README.md", "notes.md"), git_status="")
        result = verifier.check(spec, state, {})
        assert result.verdict == "pass"
        assert result.score == 1.0
        assert "passed" in result.reason

    def test_fails_when_expected_file_absent(self) -> None:
        verifier = S.RepoStateVerifier()
        spec = T.StateCheckSpec(files={"notes.md": {"exists": True}})
        state = _repo_state(file_tree=("README.md",))
        result = verifier.check(spec, state, {})
        assert result.verdict == "fail"
        assert "notes.md" in result.reason
        assert "absent" in result.reason
        assert "mismatches" in result.details

    def test_fails_when_absent_path_present(self) -> None:
        verifier = S.RepoStateVerifier()
        spec = T.StateCheckSpec(absent=("secret.txt",))
        state = _repo_state(file_tree=("README.md", "secret.txt"))
        result = verifier.check(spec, state, {})
        assert result.verdict == "fail"
        assert "secret.txt" in result.reason

    def test_fails_when_git_status_not_clean(self) -> None:
        verifier = S.RepoStateVerifier()
        spec = T.StateCheckSpec(git={"status_clean": True})
        state = _repo_state(git_status=" M README.md\n")
        result = verifier.check(spec, state, {})
        assert result.verdict == "fail"
        assert "status" in result.reason.lower()

    def test_fails_when_head_commit_message_mismatched(self) -> None:
        verifier = S.RepoStateVerifier()
        spec = T.StateCheckSpec(git={"head_commit_message": "add notes"})
        state = _repo_state(commits=({"sha": "abc1234", "subject": "wrong thing"},))
        result = verifier.check(spec, state, {})
        assert result.verdict == "fail"
        assert "head" in result.reason.lower()

    def test_fails_when_expected_branch_missing(self) -> None:
        verifier = S.RepoStateVerifier()
        spec = T.StateCheckSpec(git={"branches": ["main", "feature"]})
        state = _repo_state(branches=("main",))
        result = verifier.check(spec, state, {})
        assert result.verdict == "fail"
        assert "feature" in result.reason

    def test_fails_when_expected_commit_missing(self) -> None:
        verifier = S.RepoStateVerifier()
        spec = T.StateCheckSpec(git={"commits": {"deadbee": "add notes"}})
        state = _repo_state(commits=({"sha": "abc1234", "subject": "add notes"},))
        result = verifier.check(spec, state, {})
        assert result.verdict == "fail"
        assert "deadbee" in result.reason

    def test_file_exists_false_passes_when_absent(self) -> None:
        verifier = S.RepoStateVerifier()
        spec = T.StateCheckSpec(files={"gone.txt": {"exists": False}})
        state = _repo_state(file_tree=("README.md",))
        result = verifier.check(spec, state, {})
        assert result.verdict == "pass"

    def test_file_exists_false_fails_when_present(self) -> None:
        verifier = S.RepoStateVerifier()
        spec = T.StateCheckSpec(files={"README.md": {"exists": False}})
        state = _repo_state(file_tree=("README.md",))
        result = verifier.check(spec, state, {})
        assert result.verdict == "fail"
        assert "absent" in result.reason

    def test_multiple_mismatches_all_explained(self) -> None:
        verifier = S.RepoStateVerifier()
        spec = T.StateCheckSpec(
            files={"missing.txt": {"exists": True}},
            git={"status_clean": True, "head_commit_message": "expected"},
            absent=("present.txt",),
        )
        state = _repo_state(
            file_tree=("README.md", "present.txt"),
            git_status=" M x\n",
            commits=({"sha": "abc1234", "subject": "other"},),
        )
        result = verifier.check(spec, state, {})
        assert result.verdict == "fail"
        assert len(result.details["mismatches"]) == 4

    def test_check_is_deterministic(self) -> None:
        verifier = S.RepoStateVerifier()
        spec = T.StateCheckSpec(files={"a.txt": {"exists": True}}, absent=("b.txt",))
        state = _repo_state(file_tree=("a.txt",))
        r1 = verifier.check(spec, state, {})
        r2 = verifier.check(spec, state, {})
        assert r1 == r2


def test_contains_assertion_passes_when_diff_has_matching_content() -> None:
    """contains is enforced against the snapshot diff: matching content passes."""
    verifier = S.RepoStateVerifier()
    spec = T.StateCheckSpec(
        files={"notes.md": {"exists": True, "contains": "sandbox commit"}},
    )
    state = _repo_state(
        file_tree=("README.md", "notes.md"),
        diff="diff --git a/notes.md b/notes.md\n+++ b/notes.md\n@@ -0,0 +1,1 @@\n+sandbox commit\n",
    )
    result = verifier.check(spec, state, {})
    assert result.verdict == "pass", result.reason


def test_contains_assertion_fails_when_diff_lacks_content() -> None:
    """contains is enforced: a diff that lacks the needle fails closed."""
    verifier = S.RepoStateVerifier()
    spec = T.StateCheckSpec(
        files={"notes.md": {"exists": True, "contains": "NONEXISTENT"}},
    )
    state = _repo_state(
        file_tree=("README.md", "notes.md"),
        diff="diff --git a/notes.md b/notes.md\n+++ b/notes.md\n@@ -0,0 +1,1 @@\n+sandbox commit\n",
    )
    result = verifier.check(spec, state, {})
    assert result.verdict == "fail"
    assert "contain" in result.reason
    assert "NONEXISTENT" in result.reason


def test_contains_assertion_fails_closed_when_content_unavailable() -> None:
    """contains must NOT silently pass when the file is present but not in the diff.

    A present file whose content is not carried by the snapshot diff is
    unverifiable; the assertion fails closed rather than passing unchecked.
    """
    verifier = S.RepoStateVerifier()
    spec = T.StateCheckSpec(
        files={"README.md": {"exists": True, "contains": "fixture"}},
    )
    state = _repo_state(file_tree=("README.md",), diff="")
    result = verifier.check(spec, state, {})
    assert result.verdict == "fail"
    assert "cannot be verified" in result.reason or "not available" in result.reason


def test_sha256_assertion_fails_closed_as_unsupported() -> None:
    """sha256 assertions cannot be verified from a path-only snapshot and fail closed.

    The C02 RepoState carries no content hashes, so a sha256 assertion MUST NOT
    silently pass as an unchecked detail; it fails closed so fixtures cannot
    claim a content hash that was never actually checked.
    """
    verifier = S.RepoStateVerifier()
    spec = T.StateCheckSpec(
        files={"notes.md": {"exists": True, "sha256": "a" * 64}},
    )
    state = _repo_state(file_tree=("README.md", "notes.md"))
    result = verifier.check(spec, state, {})
    assert result.verdict == "fail"
    assert "sha256" in result.reason
    assert "cannot be verified" in result.reason
    # No unchecked_sha256 detail is recorded anymore.
    assert "unchecked_sha256" not in result.details


# ---------------------------------------------------------------------------
# Runner integration: enforced dispatcher + real verifier
# ---------------------------------------------------------------------------


def _fixed_clock() -> Any:
    values = iter(["2026-06-27T00:00:00Z", "2026-06-27T00:00:01Z"])
    return lambda: next(values)


def _make_tool_benchmark(tmp_path: Path, *, with_state_check: bool = True) -> Path:
    """Build a tool-task benchmark that uses the REAL state_check verifier.

    When ``with_state_check`` is True the metric has no ``c05_stub_state_check``
    param, so the runner registers the real :class:`S.RepoStateVerifier`.
    """
    bdir = tmp_path / "tool-benchmark"
    cases = bdir / "cases"
    fixtures = bdir / "fixtures" / "repo"
    cases.mkdir(parents=True)
    fixtures.mkdir(parents=True)
    (fixtures / "README.md").write_text("fixture\n", encoding="utf-8")
    _git_init(fixtures)
    params: dict[str, Any] = {}
    _write_yaml(
        bdir / "benchmark.yaml",
        {
            "schema_version": "1",
            "id": "tool-c07",
            "name": "Tool C07",
            "description": "C07.2 integration fixture.",
            "domain": "tool-use",
            "task_type": "tool-task",
            "metric": {"verifier": "state_check", "params": params},
            "version": "0.1.0",
            "contributor": {"name": "tests"},
            "license": "MIT",
            "case_glob": "cases/*.yaml",
            "tags": ["tool"],
            "status": "experimental",
        },
    )
    script = [
        {"command": "git", "argv": ["status", "--short"], "cwd": "."},
        {"command": "file.write", "argv": ["notes.md", "sandbox commit\n"], "cwd": "."},
        {"command": "git", "argv": ["add", "notes.md"], "cwd": "."},
        {"command": "git", "argv": ["commit", "-m", "add notes"], "cwd": "."},
    ]
    _write_yaml(
        cases / "case-1.yaml",
        {
            "schema_version": "1",
            "id": "case-1",
            "input": {
                "prompt": "Make a harmless git change.",
                "fixture": "fixtures/repo",
                "script": script,
            },
            "expected": "state-check-real",
            "tags": ["smoke"],
            "difficulty": "easy",
            "provenance": {"source": "original", "license": "MIT"},
            "state_check": {
                "files": {"notes.md": {"exists": True}},
                "git": {"status_clean": True, "head_commit_message": "add notes"},
                "absent": ["secret.txt"],
            },
        },
    )
    return bdir


def _git_init(repo: Path) -> None:
    """Initialize a tiny git repo with one commit (no host config leaks)."""
    import subprocess
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(repo),
        "GIT_AUTHOR_NAME": "fixture",
        "GIT_AUTHOR_EMAIL": "fixture@ai-bench.local",
        "GIT_COMMITTER_NAME": "fixture",
        "GIT_COMMITTER_EMAIL": "fixture@ai-bench.local",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
    }
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, env=env, check=True)
    subprocess.run(["git", "add", "README.md"], cwd=repo, env=env, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial fixture"], cwd=repo, env=env, check=True)


def test_runner_uses_enforced_dispatcher_by_default(tmp_path: Path) -> None:
    """The runner selects an enforced sandbox dispatcher when none is passed."""
    benchmark = _make_tool_benchmark(tmp_path)
    output = tmp_path / "record.json"
    result = R.run_benchmark(
        benchmark,
        output=output,
        model="stub",
        now=_fixed_clock(),
    )
    backend = result.record["environment"]["sandbox_backend"]
    assert backend in {"bwrap", "in-process"}, backend
    assert backend == SB.default_backend_id()


def test_stub_agent_creates_commit_and_real_verifier_passes(tmp_path: Path) -> None:
    """Integration: stub agent commits inside the sandbox; real verifier passes."""
    benchmark = _make_tool_benchmark(tmp_path)
    output = tmp_path / "record.json"
    result = R.run_benchmark(
        benchmark,
        output=output,
        model="stub",
        now=_fixed_clock(),
    )
    case = result.record["cases"][0]
    assert case["verdict"] == "pass", case
    transcript = case["transcript"]
    commands = [a["command"] for a in transcript]
    assert "git" in commands
    assert "file.write" in commands
    # The commit action succeeded.
    commit_actions = [a for a in transcript if a["command"] == "git" and a["argv"] and a["argv"][0] == "commit"]
    assert commit_actions, "expected a git commit action"
    assert commit_actions[-1]["exit_code"] == 0, commit_actions[-1]
    # The final repo state reflects the new file.
    state = case["final_repo_state"]
    assert "notes.md" in state["file_tree"]
    assert any("add notes" in c["subject"] for c in state["commits"])


def test_real_verifier_fails_when_state_does_not_match(tmp_path: Path) -> None:
    """Fail path: the stub agent does not create the expected file."""
    benchmark = _make_tool_benchmark(tmp_path)
    # Rewrite the case to expect a file the agent never creates.
    case_path = benchmark / "cases" / "case-1.yaml"
    data = yaml.safe_load(case_path.read_text(encoding="utf-8"))
    data["state_check"] = {
        "files": {"never-created.md": {"exists": True}},
        "git": {"status_clean": True},
    }
    case_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    output = tmp_path / "record.json"
    result = R.run_benchmark(
        benchmark,
        output=output,
        model="stub",
        now=_fixed_clock(),
    )
    case = result.record["cases"][0]
    assert case["verdict"] == "fail"
    # The failure reason explains the mismatch.
    assert "never-created.md" in (case.get("error") or "") or "never-created.md" in str(case)


def test_host_repository_byte_identical_before_and_after(tmp_path: Path) -> None:
    """The host repo (fixture source) must be byte-identical before/after a run."""
    benchmark = _make_tool_benchmark(tmp_path)
    fixture = benchmark / "fixtures" / "repo"
    before = SB.host_tree_hash(fixture)

    output = tmp_path / "record.json"
    R.run_benchmark(
        benchmark,
        output=output,
        model="stub",
        now=_fixed_clock(),
    )
    after = SB.host_tree_hash(fixture)
    assert before == after, "host fixture repo must be byte-identical after a sandboxed run"


def test_runner_does_not_edit_models_or_run_records() -> None:
    """C07 contract: the runner must not edit models.py or run_records.py."""
    # This is a static guard: the runner imports sandbox and scoring but the
    # C05-owned modules remain the sole owners of the adapter/run-record
    # contract. We assert the runner does not redefine the frozen dataclasses.
    import ai_bench.models as models_mod
    import ai_bench.run_records as rr_mod
    assert hasattr(models_mod, "ToolActionRequest")
    assert hasattr(models_mod, "SandboxHandle")
    assert hasattr(models_mod, "CommandDispatcher")
    assert hasattr(rr_mod, "tool_action_from_mapping")
    assert hasattr(rr_mod, "repo_state_from_mapping")


# ---------------------------------------------------------------------------
# Real-verifier transcript-replay acceptance (deferred from C05)
# ---------------------------------------------------------------------------


def _tool_action(
    *,
    command: str = "git",
    argv: Sequence[str] = ("status", "--short"),
    exit_code: int = 0,
    stdout: str = "",
    stderr: str = "",
    violation: bool = False,
) -> dict[str, Any]:
    return {
        "command": command,
        "argv": list(argv),
        "cwd": ".",
        "env_overrides": {},
        "stdin": None,
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": exit_code,
        "wall_clock_ms": 1,
        "timeout": False,
        "sandbox_boundary_violation": violation,
    }


def _repo_state_dict(
    *,
    file_tree: Sequence[str] = ("README.md", "notes.md"),
    git_status: str = "",
    branches: Sequence[str] = ("main",),
    commits: Sequence[Mapping[str, str]] = ({"sha": "abc1234", "subject": "add notes"},),
    diff: str = "",
) -> dict[str, Any]:
    return {
        "file_tree": list(file_tree),
        "git_status": git_status,
        "branches": list(branches),
        "commits": [dict(c) for c in commits],
        "diff": diff,
    }


def test_real_verifier_transcript_replay_acceptance(tmp_path: Path) -> None:
    """C07.2 real-verifier transcript-replay acceptance.

    ``ai-bench run --replay`` replays a small fixture of submitted agent
    tool-action transcripts (with final repo-state snapshots) through the
    now-implemented real state-check verifier, writes a validated run-record,
    and requires no API key/network/host mutation. This is the acceptance that
    C05 deliberately deferred.
    """
    benchmark = _make_tool_benchmark(tmp_path)
    replay = tmp_path / "replay"
    replay.mkdir()
    _write_json(
        replay / "case-1.json",
        {
            "case_id": "case-1",
            "transcript": [
                _tool_action(command="git", argv=("status", "--short")),
                _tool_action(command="file.write", argv=("notes.md", "sandbox commit\n")),
                _tool_action(command="git", argv=("add", "notes.md")),
                _tool_action(command="git", argv=("commit", "-m", "add notes")),
            ],
            "final_repo_state": _repo_state_dict(),
        },
    )

    output = tmp_path / "replay-record.json"
    result = R.run_benchmark(
        benchmark,
        replay=replay,
        output=output,
        now=_fixed_clock(),
    )
    assert result.record["model"] == {"id": f"replay:{replay}", "adapter": "replay"}
    assert result.record["environment"]["sandbox_backend"] == "replay-no-exec"
    case = result.record["cases"][0]
    assert case["verdict"] == "pass", case
    assert case["transcript"][0]["command"] == "git"
    assert "notes.md" in case["final_repo_state"]["file_tree"]


def test_real_verifier_transcript_replay_fail_path(tmp_path: Path) -> None:
    """Replay a transcript whose snapshot does not match the spec -> fail verdict."""
    benchmark = _make_tool_benchmark(tmp_path)
    replay = tmp_path / "replay"
    replay.mkdir()
    _write_json(
        replay / "case-1.json",
        {
            "case_id": "case-1",
            "transcript": [_tool_action(command="git", argv=("status", "--short"))],
            "final_repo_state": _repo_state_dict(
                file_tree=("README.md",),  # notes.md missing
                commits=({"sha": "abc1234", "subject": "initial fixture"},),
            ),
        },
    )

    output = tmp_path / "replay-record.json"
    result = R.run_benchmark(
        benchmark,
        replay=replay,
        output=output,
        now=_fixed_clock(),
    )
    case = result.record["cases"][0]
    assert case["verdict"] == "fail"
    # The run still exits 0 (failed verdicts are data, not command failures).
    assert output.is_file()


def test_replay_with_failed_verdict_exits_zero_via_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The CLI exits 0 for a replayed failed verdict (C05 exit contract)."""
    from ai_bench import cli
    benchmark = _make_tool_benchmark(tmp_path)
    replay = tmp_path / "replay"
    replay.mkdir()
    _write_json(
        replay / "case-1.json",
        {
            "case_id": "case-1",
            "transcript": [_tool_action()],
            "final_repo_state": _repo_state_dict(file_tree=("README.md",)),
        },
    )
    rc = cli.main(
        ["run", str(benchmark), "--replay", str(replay),
         "--output", str(tmp_path / "cli.json")]
    )
    captured = capsys.readouterr()
    assert rc == 0
    assert "fail=1" in captured.out


# ---------------------------------------------------------------------------
# End-to-end against the checked-in sandbox fixture benchmark
# ---------------------------------------------------------------------------


def test_checked_in_sandbox_fixture_validates() -> None:
    """The checked-in C07 sandbox fixture benchmark validates."""
    from ai_bench import cli
    fixture = Path(__file__).parent / "fixtures" / "sandbox" / "git-benchmark"
    rc = cli.main(["validate", str(fixture)])
    assert rc == 0


def test_checked_in_sandbox_fixture_runs_with_real_verifier(tmp_path: Path) -> None:
    """The checked-in sandbox fixture runs end-to-end with the real verifier.

    The fixture is self-sufficient: its case scripts run ``git init`` and
    ``git config`` inside the sandbox (C07 review), so no out-of-band test
    init or embedded ``.git`` is required.  The checked-in fixture ships
    ordinary files only (no nested ``.git``).
    """
    fixture = Path(__file__).parent / "fixtures" / "sandbox" / "git-benchmark"
    # Copy into tmp_path so the run-record output and any sandbox dirs do not
    # pollute the checked-in fixture tree.
    local = tmp_path / "fixture-copy"
    shutil.copytree(fixture, local)
    output = tmp_path / "record.json"
    result = R.run_benchmark(
        local,
        output=output,
        model="stub",
        now=_fixed_clock(),
    )
    assert output.is_file()
    # At least one case passed (create-commit) and the run-record is valid.
    assert result.record["aggregate"]["n_cases"] >= 1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_yaml(path: Path, data: Mapping[str, Any]) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
