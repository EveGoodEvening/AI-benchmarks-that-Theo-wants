"""Agent/tool-task adapter contract tests for chunk C05."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from ai_bench import models as M
from ai_bench import runner as R
from ai_bench import types as T


class RecordingDispatcher:
    backend_id = "recording-fake-dispatcher"

    def __init__(self) -> None:
        self.requests: list[M.ToolActionRequest] = []

    def dispatch(
        self,
        action: M.ToolActionRequest,
        *,
        sandbox: M.SandboxHandle,
    ) -> T.ToolAction:
        self.requests.append(action)
        return T.ToolAction(
            command=action.command,
            argv=tuple(action.argv),
            cwd=action.cwd,
            env_overrides=dict(action.env_overrides),
            stdin=action.stdin,
            exit_code=0,
            stdout=f"handled {action.command}\n",
            stderr="",
            wall_clock_ms=7,
            timeout=False,
            sandbox_boundary_violation=False,
        )

    def snapshot(
        self,
        *,
        sandbox: M.SandboxHandle,
        transcript: Sequence[T.ToolAction],
    ) -> T.RepoState:
        assert sandbox.root.exists()
        return T.RepoState(
            file_tree=("README.md",),
            git_status="",
            branches=("main",),
            commits=({"sha": "abc1234", "subject": "stub commit"},),
            diff="",
        )


def test_stub_agent_emits_structured_git_and_file_actions() -> None:
    agent = M.StubAgent()
    sandbox = M.SandboxHandle(root=Path("/tmp/c05-unused"), case_id="case-1")

    actions = tuple(agent.actions("prompt", params={}, sandbox=sandbox))

    assert [a.command for a in actions] == ["git", "file.write"]
    assert actions[0].argv == ("status", "--short")
    assert actions[1].cwd == "."


def test_stub_dispatcher_records_c02_transcript_fields(tmp_path: Path) -> None:
    dispatcher = M.StubCommandDispatcher()
    sandbox = M.SandboxHandle(root=tmp_path, case_id="case-1")
    action = M.ToolActionRequest(
        command="git",
        argv=("status", "--short"),
        cwd=".",
        env_overrides={"GIT_AUTHOR_NAME": "stub"},
    )

    row = dispatcher.dispatch(action, sandbox=sandbox)

    assert row.command == "git"
    assert row.env_overrides == {"GIT_AUTHOR_NAME": "stub"}
    assert row.exit_code == 0
    assert row.stdout.startswith("c05 fake git")
    assert row.wall_clock_ms >= 0
    assert row.timeout is False
    assert row.sandbox_boundary_violation is False


def test_runner_hands_stub_agent_state_to_fake_state_check(tmp_path: Path) -> None:
    benchmark = _make_tool_benchmark(tmp_path)
    output = tmp_path / "record.json"
    dispatcher = RecordingDispatcher()

    result = R.run_benchmark(
        benchmark,
        output=output,
        model="stub",
        dispatcher=dispatcher,
        now=_fixed_clock(),
    )

    assert output.is_file()
    assert len(dispatcher.requests) == 2
    case = result.record["cases"][0]
    assert case["verdict"] == "pass"
    assert [a["command"] for a in case["transcript"]] == ["git", "file.write"]
    assert case["transcript"][0]["stdout"] == "handled git\n"
    assert case["final_repo_state"]["commits"][0]["subject"] == "stub commit"
    assert result.record["environment"]["sandbox_backend"] == "recording-fake-dispatcher"


def _make_tool_benchmark(tmp_path: Path) -> Path:
    bdir = tmp_path / "tool-benchmark"
    cases = bdir / "cases"
    fixtures = bdir / "fixtures" / "repo"
    cases.mkdir(parents=True)
    fixtures.mkdir(parents=True)
    (fixtures / "README.md").write_text("fixture\n", encoding="utf-8")
    _write_yaml(
        bdir / "benchmark.yaml",
        {
            "schema_version": "1",
            "id": "tool-c05",
            "name": "Tool C05",
            "description": "Tool adapter contract fixture.",
            "domain": "tool-use",
            "task_type": "tool-task",
            "metric": {"verifier": "state_check", "params": {"c05_stub_state_check": "pass"}},
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
                "prompt": "Make a harmless git change.",
                "fixture": "fixtures/repo",
                "script": [
                    {"command": "git", "argv": ["status", "--short"], "cwd": "."},
                    {"command": "file.write", "argv": ["README.md", "updated"], "cwd": "."},
                ],
            },
            "expected": "state-check-stub",
            "tags": ["smoke"],
            "difficulty": "easy",
            "provenance": {"source": "original", "license": "MIT"},
            "state_check": {"git": {"status_clean": True}},
        },
    )
    return bdir


def _fixed_clock() -> Any:
    values = iter(["2026-06-27T00:00:00Z", "2026-06-27T00:00:01Z"])
    return lambda: next(values)


def _write_yaml(path: Path, data: Mapping[str, Any]) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


