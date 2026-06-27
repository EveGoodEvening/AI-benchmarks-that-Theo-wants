"""Benchmark-specific tests for the description-to-label reference benchmark (C06).

These tests exercise the checked-in ``benchmarks/description-label`` benchmark
directly: schema/loader validation, the smoke subset selector, the stub run
path, and the non-stub ``--predictions`` path that scores real submitted text
outputs with the real C04 verifiers. Acceptance is based on schema-valid
run-records and correct benchmark wiring, not on every stub/sample verdict
passing (per the C05 exit contract).
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

# Repository root: tests/test_description_label_benchmark.py -> <repo>
_REPO_ROOT = Path(__file__).resolve().parents[1]
_BENCHMARK_DIR = _REPO_ROOT / "benchmarks" / "description-label"


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
    assert manifest.id == "description-label"
    assert manifest.data["task_type"] == "text"
    assert manifest.data["metric"]["verifier"] == "exact_match"
    assert "recreation" in list(manifest.tags)
    assert "spatial-reasoning" in list(manifest.tags)
    # 20-50 original cases per the C06 deliverable.
    assert 20 <= len(cases) <= 50


def test_cases_carry_provenance_and_license() -> None:
    """Every normal case carries provenance with a license (C02 case schema)."""
    for _path, case in _load_cases():
        prov = case.get("provenance") or {}
        assert prov.get("source") == "original", case["id"]
        assert prov.get("license"), case["id"]


def test_smoke_subset_is_non_empty_and_selectable() -> None:
    """At least one smoke-tagged case exists and --tag smoke selects only it."""
    cases = _load_cases()
    smoke_ids = [c["id"] for _, c in cases if "smoke" in list(c.get("tags", []))]
    assert len(smoke_ids) >= 1

    output = _REPO_ROOT / "build" / "c06-smoke-record.json"
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

    Failed case verdicts are expected from the stub and are evaluation data,
    not a command failure (C05 exit contract).
    """
    output = tmp_path / "stub-record.json"
    result = R.run_benchmark(_BENCHMARK_DIR, model="stub", output=output)
    assert output.is_file()
    _validate_run_record(result.record)
    assert result.record["aggregate"]["n_cases"] == len(_load_cases())


def test_non_stub_predictions_path_scores_real_outputs(tmp_path: Path) -> None:
    """The checked-in sample_predictions are scored by the real C04 verifier.

    The run-record records the file prediction source as the model id, is
    schema-valid, and at least one case passes (the sample is mostly correct,
    with one deliberate miss to show failed verdicts are acceptable).
    """
    preds = _BENCHMARK_DIR / "sample_predictions"
    assert preds.is_dir(), "sample_predictions directory must be checked in"

    output = tmp_path / "pred-record.json"
    result = R.run_benchmark(_BENCHMARK_DIR, predictions=preds, output=output)
    assert output.is_file()
    _validate_run_record(result.record)

    assert result.record["model"]["adapter"] == "file"
    assert result.record["model"]["id"].startswith("file:")
    # The sample is mostly correct; require at least one pass and that the
    # one deliberate miss (surf-airs) is recorded as a failed verdict.
    n_pass = result.record["aggregate"]["n_pass"]
    assert n_pass >= 1
    verdicts = {c["case_id"]: c["verdict"] for c in result.record["cases"]}
    assert verdicts["surf-airs"] == "fail"


def test_cli_validate_one_exits_zero() -> None:
    """``ai-bench validate benchmarks/description-label`` exits 0."""
    assert cli.main(["validate", str(_BENCHMARK_DIR)]) == 0


def test_cli_run_predictions_exits_zero(tmp_path: Path) -> None:
    """``ai-bench run --predictions`` exits 0 per the C05 exit contract."""
    output = tmp_path / "cli-pred-record.json"
    rc = cli.main(
        [
            "run",
            str(_BENCHMARK_DIR),
            "--predictions",
            str(_BENCHMARK_DIR / "sample_predictions"),
            "--output",
            str(output),
        ]
    )
    assert rc == 0
    assert output.is_file()
