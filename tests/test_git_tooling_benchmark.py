"""Benchmark-specific tests for the git-tooling reference benchmark (C08).

These tests exercise the checked-in ``benchmarks/git-tooling`` benchmark
directly: schema/loader validation, the smoke subset selector, the stub run
path, and the non-stub ``--replay`` path that scores real tool-action
transcripts through the real state_check verifier (C07.2). Acceptance is based
on schema-valid run-records and correct benchmark wiring, not on every
stub/sample verdict passing (per the C05 exit contract).
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
import yaml
from ai_bench import cli
from ai_bench import loader as L
from ai_bench import runner as R

# Repository root: tests/test_git_tooling_benchmark.py -> <repo>
_REPO_ROOT = Path(__file__).resolve().parents[1]
_BENCHMARK_DIR = _REPO_ROOT / "benchmarks" / "git-tooling"

# The four smoke-tagged cases that make up the selectable smoke subset.
_SMOKE_IDS = {"init-repo", "create-branch", "stage-and-commit", "dirty-no-commit"}


def _load_cases() -> list[tuple[Path, dict]]:
    manifest = L.load_benchmark(_BENCHMARK_DIR)
    return L.load_cases(manifest)


def _validate_run_record(record: dict) -> None:
    schema = json.loads((_REPO_ROOT / "schemas" / "run-record.schema.json").read_text())
    jsonschema.Draft202012Validator(schema).validate(record)


def test_benchmark_validates_against_schemas() -> None:
    """Manifest and all cases validate via the C03 loader/schema gate."""
    manifest = L.load_benchmark(_BENCHMARK_DIR)
    cases = L.load_cases(manifest)
    assert manifest.id == "git-tooling"
    assert manifest.data["task_type"] == "tool-task"
    assert manifest.data["metric"]["verifier"] == "state_check"
    assert "tool-use" in list(manifest.tags)
    assert "git" in list(manifest.tags)
    assert manifest.data["status"] == "experimental"
    # 20-50 original cases per the C08 deliverable.
    assert 20 <= len(cases) <= 50


def test_cases_carry_provenance_and_license() -> None:
    """Every case carries provenance with source original and a license (C02 case schema)."""
    for _path, case in _load_cases():
        prov = case.get("provenance") or {}
        assert prov.get("source") == "original", case["id"]
        assert prov.get("license"), case["id"]


def test_cases_use_state_check_verifier() -> None:
    """Every case uses the per-case state_check verifier with a non-empty block."""
    for _path, case in _load_cases():
        verifier = case.get("verifier") or {}
        assert verifier.get("verifier") == "state_check", case["id"]
        state_check = case.get("state_check") or {}
        assert state_check, case["id"]
        # state_check must not rely on a sha256 content hash (state, not bytes).
        assert "sha256" not in state_check, case["id"]


def test_smoke_subset_is_non_empty_and_selectable() -> None:
    """The four smoke-tagged cases exist and --tag smoke selects only them."""
    cases = _load_cases()
    smoke_ids = [c["id"] for _, c in cases if "smoke" in list(c.get("tags", []))]
    assert set(smoke_ids) == _SMOKE_IDS

    output = _REPO_ROOT / "build" / "c08-smoke-record.json"
    output.parent.mkdir(exist_ok=True)
    try:
        result = R.run_benchmark(
            _BENCHMARK_DIR,
            tag="smoke",
            model="stub",
            output=output,
        )
    finally:
        # Keep the repo tree clean; the run-record is verification evidence,
        # not a checked-in artifact.
        if output.is_file():
            output.unlink()

    assert result.record["tag_filter"] == "smoke"
    assert result.record["aggregate"]["n_cases"] == len(smoke_ids)
    # Only smoke-tagged case ids appear in the run-record.
    assert {c["case_id"] for c in result.record["cases"]} == set(smoke_ids)


def test_stub_run_writes_schema_valid_record(tmp_path: Path) -> None:
    """Stub run exits 0 (no exception) and writes a schema-valid run-record.

    Stub runs use the real sandbox dispatcher and real state_check verifier,
    so some stub verdicts may fail; those are evaluation data, not a command
    failure (C05 exit contract).
    """
    output = tmp_path / "stub-record.json"
    result = R.run_benchmark(_BENCHMARK_DIR, model="stub", output=output)
    assert output.is_file()
    _validate_run_record(result.record)
    assert result.record["aggregate"]["n_cases"] == len(_load_cases())


def test_non_stub_replay_scores_real_transcripts(tmp_path: Path) -> None:
    """The checked-in sample_transcripts are scored by the real state_check verifier.

    The run-record records the replay source as the model id, is schema-valid,
    and covers all 24 cases. At least one case passes and the deliberate miss
    (dirty-no-commit) is recorded as a failed verdict, proving the real-verifier
    transcript-replay acceptance path.
    """
    transcripts = _BENCHMARK_DIR / "sample_transcripts"
    assert transcripts.is_dir(), "sample_transcripts directory must be checked in"

    output = tmp_path / "replay-record.json"
    result = R.run_benchmark(
        _BENCHMARK_DIR,
        replay=transcripts,
        output=output,
    )
    assert output.is_file()
    _validate_run_record(result.record)

    assert result.record["model"]["adapter"] == "replay"
    assert result.record["model"]["id"].startswith("replay:")
    assert result.record["aggregate"]["n_cases"] == 24
    assert result.record["aggregate"]["n_pass"] >= 1
    verdicts = {c["case_id"]: c["verdict"] for c in result.record["cases"]}
    assert verdicts["dirty-no-commit"] == "fail"


def test_cli_validate_one_exits_zero() -> None:
    """``ai-bench validate benchmarks/git-tooling`` exits 0."""
    assert cli.main(["validate", str(_BENCHMARK_DIR)]) == 0


def test_cli_run_replay_exits_zero(tmp_path: Path) -> None:
    """``ai-bench run --replay`` exits 0 per the C05 exit contract."""
    output = tmp_path / "cli-replay-record.json"
    rc = cli.main(
        [
            "run",
            str(_BENCHMARK_DIR),
            "--replay",
            str(_BENCHMARK_DIR / "sample_transcripts"),
            "--output",
            str(output),
        ]
    )
    assert rc == 0
    assert output.is_file()
