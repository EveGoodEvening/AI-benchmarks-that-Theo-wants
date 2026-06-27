"""Run-record validation tests for chunk C05."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ai_bench import run_records as RR
from ai_bench import types as T


def test_text_run_record_validates_and_writes(tmp_path: Path) -> None:
    record = _run_record(task_type="text")

    data = RR.validate_run_record(record)
    output = RR.write_run_record(record, tmp_path / "record.json")

    assert output.is_file()
    assert json.loads(output.read_text(encoding="utf-8")) == data
    assert data["cases"][0]["observed"] == "label-a"
    assert data["environment_hash"].startswith("sha256:")


def test_tool_run_record_preserves_transcript_and_final_state(tmp_path: Path) -> None:
    record = _run_record(task_type="tool-task")

    data = RR.validate_run_record(record)
    RR.write_run_record(record, tmp_path / "tool.json")

    case = data["cases"][0]
    assert case["transcript"][0]["command"] == "git"
    assert case["transcript"][0]["env_overrides"] == {"GIT_AUTHOR_NAME": "stub"}
    assert case["final_repo_state"]["branches"] == ["main"]


def test_environment_hash_is_deterministic_and_path_independent() -> None:
    env = RR.default_environment(sandbox_backend="c05-fake-dispatcher")

    assert RR.environment_hash(env) == RR.environment_hash(env)
    assert RR.environment_hash(env) == RR.environment_hash(
        {
            "sandbox_backend": "c05-fake-dispatcher",
            "python": env.python,
            "os": env.os,
            "runner_version": env.runner_version,
        }
    )


def test_validation_rejects_missing_text_observed() -> None:
    data = RR.record_to_dict(_run_record(task_type="text"))
    del data["cases"][0]["observed"]

    with pytest.raises(RR.RunRecordValidationError) as exc:
        RR.validate_run_record(data)

    assert "observed" in "\n".join(exc.value.errors)


def test_replay_materializers_require_c02_transcript_fields() -> None:
    action = _tool_action_dict()
    assert RR.tool_action_from_mapping(action).command == "git"

    broken = dict(action)
    del broken["stdin"]
    with pytest.raises(RR.RunRecordValidationError, match="stdin"):
        RR.tool_action_from_mapping(broken)


def test_repo_state_materializer_rejects_incomplete_snapshot() -> None:
    with pytest.raises(RR.RunRecordValidationError, match="diff"):
        RR.repo_state_from_mapping(
            {
                "file_tree": [],
                "git_status": "",
                "branches": ["main"],
                "commits": [],
            }
        )


def _run_record(*, task_type: str) -> T.RunRecord:
    environment = RR.default_environment(
        sandbox_backend="c05-fake-dispatcher" if task_type == "tool-task" else None
    )
    case = T.CaseResult(
        case_id="case-1",
        verdict="pass",
        score=1.0,
        expected="label-a",
        observed="label-a" if task_type == "text" else None,
        provenance={"source": "original", "license": "MIT"},
        transcript=(RR.tool_action_from_mapping(_tool_action_dict()),)
        if task_type == "tool-task"
        else (),
        final_repo_state=RR.repo_state_from_mapping(_repo_state_dict())
        if task_type == "tool-task"
        else None,
    )
    verifier_name = "state_check" if task_type == "tool-task" else "exact_match"
    return T.RunRecord(
        schema_version="1",
        run_id="run-0001",
        started_at="2026-06-27T00:00:00Z",
        ended_at="2026-06-27T00:00:01Z",
        benchmark=T.BenchmarkRef(
            id="sample-benchmark",
            version="0.1.0",
            task_type=task_type,  # type: ignore[arg-type]
            domain="unit",
            tags=("sample",),
            status="experimental",
        ),
        model=T.ModelRef(id="stub", provider="ai-bench", adapter="stub"),
        prompt=T.RunPrompt(version="0.1.0", template="{input}"),
        sampling_params={"temperature": 0.0},
        seed=0,
        fixture_version="0.1.0",
        manifest_version="0.1.0",
        environment_hash=RR.environment_hash(environment),
        environment=environment,
        metric_params={"case_sensitive": False} if verifier_name == "exact_match" else {},
        verifier=T.RunVerifier(name=verifier_name, version="1"),
        tag_filter=None,
        cases=(case,),
        aggregate=T.AggregateScore(
            metric=verifier_name,
            value=1.0,
            n_cases=1,
            n_pass=1,
            n_fail=0,
        ),
    )


def _tool_action_dict() -> dict[str, Any]:
    return {
        "command": "git",
        "argv": ["status", "--short"],
        "cwd": ".",
        "env_overrides": {"GIT_AUTHOR_NAME": "stub"},
        "stdin": None,
        "stdout": "",
        "stderr": "",
        "exit_code": 0,
        "wall_clock_ms": 3,
        "timeout": False,
        "sandbox_boundary_violation": False,
    }


def _repo_state_dict() -> dict[str, Any]:
    return {
        "file_tree": ["README.md"],
        "git_status": "",
        "branches": ["main"],
        "commits": [{"sha": "abc1234", "subject": "initial"}],
        "diff": "",
    }
