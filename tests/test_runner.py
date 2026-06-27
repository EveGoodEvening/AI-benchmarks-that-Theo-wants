"""Runner/CLI contract tests for chunk C05."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import pytest
import yaml

from ai_bench import cli
from ai_bench import runner as R


def test_stub_text_run_writes_schema_valid_record_and_failed_verdict_is_data(tmp_path: Path) -> None:
    benchmark = _make_text_benchmark(tmp_path)
    output = tmp_path / "stub-record.json"

    result = R.run_benchmark(benchmark, output=output, model="stub", now=_fixed_clock())

    assert output.is_file()
    assert result.record["model"]["adapter"] == "stub"
    assert result.record["aggregate"]["n_cases"] == 2
    assert result.record["aggregate"]["n_fail"] == 2
    assert all(case["observed"].startswith("stub:0:") for case in result.record["cases"])


def test_smoke_tag_selector_runs_only_smoke_cases(tmp_path: Path) -> None:
    benchmark = _make_text_benchmark(tmp_path)

    result = R.run_benchmark(
        benchmark,
        tag="smoke",
        output=tmp_path / "smoke-record.json",
        model="stub",
        now=_fixed_clock(),
    )

    assert result.record["tag_filter"] == "smoke"
    assert [case["case_id"] for case in result.record["cases"]] == ["case-1"]
    assert result.record["aggregate"]["n_cases"] == 1


def test_stub_seed_reproducibility_and_seed_variance(tmp_path: Path) -> None:
    benchmark = _make_text_benchmark(tmp_path)

    first = R.run_benchmark(
        benchmark,
        output=tmp_path / "first.json",
        model="stub",
        seed=123,
        now=_fixed_clock(),
    ).record
    second = R.run_benchmark(
        benchmark,
        output=tmp_path / "second.json",
        model="stub",
        seed=123,
        now=_fixed_clock(),
    ).record
    changed = R.run_benchmark(
        benchmark,
        output=tmp_path / "changed.json",
        model="stub",
        seed=124,
        now=_fixed_clock(),
    ).record

    assert first == second
    assert _without_volatile(first) != _without_volatile(changed)
    assert [c["observed"] for c in first["cases"]] != [c["observed"] for c in changed["cases"]]
    assert first["environment_hash"] == changed["environment_hash"]


def test_predictions_dir_scores_real_text_outputs_with_c04_verifier(tmp_path: Path) -> None:
    benchmark = _make_text_benchmark(tmp_path)
    preds = tmp_path / "preds"
    preds.mkdir()
    (preds / "case-1.txt").write_text("alpha", encoding="utf-8")
    (preds / "case-2.txt").write_text("wrong", encoding="utf-8")

    result = R.run_benchmark(
        benchmark,
        predictions=preds,
        output=tmp_path / "pred-record.json",
        now=_fixed_clock(),
    )

    assert result.record["model"] == {"id": f"file:{preds}", "adapter": "file"}
    assert result.record["aggregate"]["n_pass"] == 1
    assert result.record["aggregate"]["n_fail"] == 1
    assert [case["verdict"] for case in result.record["cases"]] == ["pass", "fail"]


def test_predictions_file_jsonl_supported(tmp_path: Path) -> None:
    benchmark = _make_text_benchmark(tmp_path)
    pred_file = tmp_path / "preds.jsonl"
    pred_file.write_text(
        '{"case_id":"case-1","prediction":"alpha"}\n'
        '{"case_id":"case-2","prediction":"beta"}\n',
        encoding="utf-8",
    )

    result = R.run_benchmark(
        benchmark,
        predictions_file=pred_file,
        output=tmp_path / "pred-file-record.json",
        now=_fixed_clock(),
    )

    assert result.record["aggregate"]["n_pass"] == 2
    assert result.record["model"]["id"] == f"file:{pred_file}"


def test_cli_failed_verdicts_exit_zero_but_missing_prediction_exits_nonzero(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    benchmark = _make_text_benchmark(tmp_path)
    preds = tmp_path / "preds"
    preds.mkdir()
    (preds / "case-1.txt").write_text("wrong", encoding="utf-8")
    (preds / "case-2.txt").write_text("wrong", encoding="utf-8")

    ok = cli.main(
        [
            "run",
            str(benchmark),
            "--predictions",
            str(preds),
            "--output",
            str(tmp_path / "cli-record.json"),
        ]
    )
    captured = capsys.readouterr()

    assert ok == 0
    assert "fail=2" in captured.out
    assert (tmp_path / "cli-record.json").is_file()

    (preds / "case-2.txt").unlink()
    bad = cli.main(["run", str(benchmark), "--predictions", str(preds)])
    captured = capsys.readouterr()

    assert bad == 1
    assert "missing prediction" in captured.err


def test_replay_plumbing_scores_transcripts_with_c05_fake_state_check(tmp_path: Path) -> None:
    benchmark = _make_tool_benchmark(tmp_path, stub_result="fail")
    replay = tmp_path / "replay"
    replay.mkdir()
    _write_json(
        replay / "case-1.json",
        {
            "case_id": "case-1",
            "transcript": [_tool_action()],
            "final_repo_state": _repo_state(),
        },
    )

    result = R.run_benchmark(
        benchmark,
        replay=replay,
        output=tmp_path / "replay-record.json",
        now=_fixed_clock(),
    )

    assert result.record["model"] == {"id": f"replay:{replay}", "adapter": "replay"}
    assert result.record["environment"]["sandbox_backend"] == "replay-no-exec"
    assert result.record["aggregate"]["n_fail"] == 1
    assert result.record["cases"][0]["transcript"][0]["command"] == "git"
    assert result.record["cases"][0]["final_repo_state"]["branches"] == ["main"]


def test_cli_replay_failed_verdict_exits_zero_missing_transcript_exits_nonzero(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    benchmark = _make_tool_benchmark(tmp_path, stub_result=False)
    replay = tmp_path / "replay"
    replay.mkdir()
    _write_json(replay / "case-1.json", {"transcript": [_tool_action()]})

    ok = cli.main(
        [
            "run",
            str(benchmark),
            "--replay",
            str(replay),
            "--output",
            str(tmp_path / "replay-cli.json"),
        ]
    )
    captured = capsys.readouterr()

    assert ok == 0
    assert "fail=1" in captured.out
    assert (tmp_path / "replay-cli.json").is_file()

    (replay / "case-1.json").unlink()
    bad = cli.main(["run", str(benchmark), "--replay", str(replay)])
    captured = capsys.readouterr()

    assert bad == 1
    assert "missing replay transcript" in captured.err


def test_invalid_verifier_config_and_empty_selection_are_command_failures(tmp_path: Path) -> None:
    bad_tool = _make_tool_benchmark(tmp_path, stub_result="not-a-verdict")
    with pytest.raises(R.RunnerError, match="c05_stub_state_check"):
        R.run_benchmark(bad_tool, replay=_make_replay(tmp_path), output=tmp_path / "bad.json")

    text = _make_text_benchmark(tmp_path / "other")
    with pytest.raises(R.RunnerError, match="no selected"):
        R.run_benchmark(text, tag="does_not_exist", output=tmp_path / "empty.json")


def test_run_record_write_failure_is_command_failure(tmp_path: Path) -> None:
    benchmark = _make_text_benchmark(tmp_path)
    parent_file = tmp_path / "not-a-dir"
    parent_file.write_text("file", encoding="utf-8")

    with pytest.raises(R.RunnerError, match="could not write run-record"):
        R.run_benchmark(
            benchmark,
            output=parent_file / "record.json",
            predictions_file=_make_predictions_file(tmp_path),
        )


def _make_text_benchmark(tmp_path: Path) -> Path:
    bdir = tmp_path / "text-benchmark"
    cases = bdir / "cases"
    cases.mkdir(parents=True)
    _write_yaml(
        bdir / "benchmark.yaml",
        {
            "schema_version": "1",
            "id": "text-c05",
            "name": "Text C05",
            "description": "Text runner fixture.",
            "domain": "labels",
            "task_type": "text",
            "metric": {"verifier": "exact_match", "params": {"case_sensitive": True}},
            "version": "0.1.0",
            "contributor": {"name": "tests"},
            "license": "MIT",
            "case_glob": "cases/*.yaml",
            "tags": ["text"],
            "status": "experimental",
            "prompt_template": {"version": "0.1.0", "template": "Answer: {input}"},
            "sampling": {"temperature": 0.0},
        },
    )
    _write_yaml(cases / "case-1.yaml", _text_case("case-1", "First", "alpha", ["smoke"]))
    _write_yaml(cases / "case-2.yaml", _text_case("case-2", "Second", "beta", []))
    return bdir


def _text_case(case_id: str, prompt: str, expected: str, tags: list[str]) -> dict[str, Any]:
    return {
        "schema_version": "1",
        "id": case_id,
        "input": prompt,
        "expected": expected,
        "tags": tags,
        "difficulty": "easy",
        "provenance": {"source": "original", "license": "MIT"},
    }


def _make_tool_benchmark(tmp_path: Path, *, stub_result: Any) -> Path:
    bdir = tmp_path / "tool-benchmark"
    cases = bdir / "cases"
    cases.mkdir(parents=True)
    _write_yaml(
        bdir / "benchmark.yaml",
        {
            "schema_version": "1",
            "id": "tool-c05",
            "name": "Tool C05",
            "description": "Replay runner fixture.",
            "domain": "tool-use",
            "task_type": "tool-task",
            "metric": {"verifier": "state_check", "params": {"c05_stub_state_check": stub_result}},
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
            "input": {"prompt": "Replay these actions."},
            "expected": "state-check-stub",
            "tags": ["smoke"],
            "difficulty": "easy",
            "provenance": {"source": "original", "license": "MIT"},
            "state_check": {"git": {"status_clean": True}},
        },
    )
    return bdir


def _make_replay(tmp_path: Path) -> Path:
    replay = tmp_path / "replay-for-error"
    replay.mkdir()
    _write_json(replay / "case-1.json", {"transcript": [_tool_action()]})
    return replay


def _make_predictions_file(tmp_path: Path) -> Path:
    path = tmp_path / "predictions.json"
    _write_json(path, {"case-1": "alpha", "case-2": "beta"})
    return path


def _tool_action() -> dict[str, Any]:
    return {
        "command": "git",
        "argv": ["status", "--short"],
        "cwd": ".",
        "env_overrides": {},
        "stdin": None,
        "stdout": "",
        "stderr": "",
        "exit_code": 0,
        "wall_clock_ms": 1,
        "timeout": False,
        "sandbox_boundary_violation": False,
    }


def _repo_state() -> dict[str, Any]:
    return {
        "file_tree": ["README.md"],
        "git_status": "",
        "branches": ["main"],
        "commits": [{"sha": "abc1234", "subject": "initial"}],
        "diff": "",
    }


def _fixed_clock() -> Any:
    values = iter(["2026-06-27T00:00:00Z", "2026-06-27T00:00:01Z"])
    return lambda: next(values)


def _without_volatile(record: Mapping[str, Any]) -> dict[str, Any]:
    data = json.loads(json.dumps(record))
    data.pop("run_id", None)
    data.pop("started_at", None)
    data.pop("ended_at", None)
    return data


def _write_yaml(path: Path, data: Mapping[str, Any]) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _write_json(path: Path, data: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
