"""Failure-case preservation, retry, and hard-set export tests (chunk C09).

Exercises the public ``ai-bench failures save``, ``ai-bench retry``, and
``ai-bench hard-set export`` entry points against real C05 run-records produced
by ``runner.run_benchmark``.  Covers the explicit C09 test scenarios:

  * induce a stub failure, save it, retry with a fixed prediction set and mark
    improved, retry with the original stub and mark unchanged, export a hard
    set and run it.
  * deduplication retains records that share task/model/params but differ in
    seed or environment hash (both records kept with their own provenance).
  * end-to-end preservation through the public runner, ``failures save``, and
    schema validation against ``schemas/failure-store.schema.json``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import jsonschema
import pytest
import yaml
from ai_bench import cli
from ai_bench import failures as F
from ai_bench import loader as L
from ai_bench import runner as R
from ai_bench import run_records as RR


# --- End-to-end preservation through the public runner ----------------------


def test_save_preserves_stub_failures_and_validates_against_schema(tmp_path: Path) -> None:
    benchmark = _make_text_benchmark(tmp_path)
    record_path = tmp_path / "stub-record.json"
    store_path = tmp_path / "store.json"

    # Real run-record from the public runner (stub -> all cases fail).
    result = R.run_benchmark(benchmark, output=record_path, model="stub", now=_fixed_clock())
    assert result.record["aggregate"]["n_fail"] == 2

    store = F.save_failures(record_path, store_path, benchmark_dir=benchmark)

    assert store_path.is_file()
    assert len(store.failures) == 2
    # The store must validate against the frozen C02 schema.
    _assert_store_validates(store_path)
    # Each failure record carries the full determinant set.
    for rec in store.failures:
        assert rec.verifier_verdict.verdict == "fail"
        assert rec.dedup_key is not None
        assert rec.dedup_key.startswith("sha256:")
        assert rec.run_record_ref.run_id == result.record["run_id"]
        # task_input loaded from --benchmark disk cases.
        assert rec.task_input in {"First", "Second"}


def test_save_via_cli_writes_schema_valid_store(tmp_path: Path) -> None:
    benchmark = _make_text_benchmark(tmp_path)
    record_path = tmp_path / "stub-record.json"
    store_path = tmp_path / "store.json"

    R.run_benchmark(benchmark, output=record_path, model="stub", now=_fixed_clock())

    rc = cli.main(["failures", "save", str(record_path), "--store", str(store_path), "--benchmark", str(benchmark)])
    assert rc == 0
    assert store_path.is_file()
    _assert_store_validates(store_path)


# --- Retry: improved / unchanged / regressed --------------------------------


def test_retry_with_fixed_predictions_marks_improved(tmp_path: Path) -> None:
    benchmark = _make_text_benchmark(tmp_path)
    record_path = tmp_path / "stub-record.json"
    store_path = tmp_path / "store.json"

    # 1. Induce stub failures and save them.
    R.run_benchmark(benchmark, output=record_path, model="stub", now=_fixed_clock())
    F.save_failures(record_path, store_path, benchmark_dir=benchmark)
    assert len(F.load_failure_store(store_path).failures) == 2

    # 2. Retry with correct predictions -> both improved.
    preds = tmp_path / "preds-fixed"
    preds.mkdir()
    (preds / "case-1.txt").write_text("alpha", encoding="utf-8")
    (preds / "case-2.txt").write_text("beta", encoding="utf-8")

    outcomes = F.retry_failures(
        store_path,
        benchmark,
        predictions=preds,
        output=tmp_path / "retry-fixed.json",
        now=_fixed_clock(),
    )
    assert len(outcomes) == 2
    assert all(o.classification == "improved" for o in outcomes)
    assert all(o.new_verdict == "pass" for o in outcomes)
    assert all(o.stored_verdict == "fail" for o in outcomes)


def test_retry_with_original_stub_marks_unchanged(tmp_path: Path) -> None:
    benchmark = _make_text_benchmark(tmp_path)
    record_path = tmp_path / "stub-record.json"
    store_path = tmp_path / "store.json"

    R.run_benchmark(benchmark, output=record_path, model="stub", now=_fixed_clock())
    F.save_failures(record_path, store_path, benchmark_dir=benchmark)

    # Retry with the same stub adapter -> still failing -> unchanged.
    outcomes = F.retry_failures(
        store_path,
        benchmark,
        model="stub",
        output=tmp_path / "retry-stub.json",
        now=_fixed_clock(),
    )
    assert len(outcomes) == 2
    assert all(o.classification == "unchanged" for o in outcomes)
    assert all(o.new_verdict == "fail" for o in outcomes)


def test_retry_via_cli_reports_classification_counts(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    benchmark = _make_text_benchmark(tmp_path)
    record_path = tmp_path / "stub-record.json"
    store_path = tmp_path / "store.json"

    R.run_benchmark(benchmark, output=record_path, model="stub", now=_fixed_clock())
    F.save_failures(record_path, store_path, benchmark_dir=benchmark)

    rc = cli.main(["retry", str(store_path), "--benchmark", str(benchmark), "--model", "stub"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "unchanged=2" in out
    assert "improved=0" in out


# --- Hard-set export + run --------------------------------------------------


def test_export_hard_set_produces_runnable_benchmark(tmp_path: Path) -> None:
    benchmark = _make_text_benchmark(tmp_path)
    record_path = tmp_path / "stub-record.json"
    store_path = tmp_path / "store.json"
    export_dir = tmp_path / "hardset"

    R.run_benchmark(benchmark, output=record_path, model="stub", now=_fixed_clock())
    F.save_failures(record_path, store_path, benchmark_dir=benchmark)

    exported = F.export_hard_set(store_path, export_dir, benchmark_dir=benchmark)
    assert exported == export_dir
    assert (export_dir / "benchmark.yaml").is_file()
    case_files = list((export_dir / "cases").glob("*.yaml"))
    assert len(case_files) == 2

    # The exported subset must validate as a benchmark.
    L.load_benchmark(export_dir)
    cases = L.load_cases(export_dir)
    assert {c[1]["id"] for c in cases} == {"case-1", "case-2"}
    # Provenance preserved back to the original failure cases.
    for _, case in cases:
        assert case["provenance"]["source"] == "ai-bench-failure-store"
        assert "run_id" in case["provenance"]["notes"] or "Preserved" in case["provenance"]["notes"]

    # The exported subset is runnable via the public runner.
    run = R.run_benchmark(exported, output=tmp_path / "hardset-run.json", model="stub", now=_fixed_clock())
    assert run.record["aggregate"]["n_cases"] == 2


def test_export_hard_set_via_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    benchmark = _make_text_benchmark(tmp_path)
    record_path = tmp_path / "stub-record.json"
    store_path = tmp_path / "store.json"
    export_dir = tmp_path / "hardset-cli"

    R.run_benchmark(benchmark, output=record_path, model="stub", now=_fixed_clock())
    F.save_failures(record_path, store_path, benchmark_dir=benchmark)

    rc = cli.main(["hard-set", "export", str(store_path), "--output", str(export_dir), "--benchmark", str(benchmark)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "OK: hard-set export" in out
    assert (export_dir / "benchmark.yaml").is_file()


# --- Deduplication: full determinant set ------------------------------------


def test_same_failure_saved_twice_is_deduplicated(tmp_path: Path) -> None:
    benchmark = _make_text_benchmark(tmp_path)
    record_path = tmp_path / "stub-record.json"
    store_path = tmp_path / "store.json"

    R.run_benchmark(benchmark, output=record_path, model="stub", seed=0, now=_fixed_clock())
    F.save_failures(record_path, store_path, benchmark_dir=benchmark)
    first_count = len(F.load_failure_store(store_path).failures)

    # Save the same run-record again -> no new records.
    F.save_failures(record_path, store_path, benchmark_dir=benchmark)
    second_count = len(F.load_failure_store(store_path).failures)

    assert first_count == 2
    assert second_count == 2


def test_different_seed_is_not_deduplicated(tmp_path: Path) -> None:
    benchmark = _make_text_benchmark(tmp_path)
    store_path = tmp_path / "store.json"

    rec_a = tmp_path / "seed-0.json"
    rec_b = tmp_path / "seed-1.json"
    R.run_benchmark(benchmark, output=rec_a, model="stub", seed=0, now=_fixed_clock())
    R.run_benchmark(benchmark, output=rec_b, model="stub", seed=1, now=_fixed_clock())

    F.save_failures(rec_a, store_path, benchmark_dir=benchmark)
    F.save_failures(rec_b, store_path, benchmark_dir=benchmark)

    store = F.load_failure_store(store_path)
    # Two seeds x two cases = four distinct failure records.
    assert len(store.failures) == 4
    seeds = {r.seed for r in store.failures}
    assert seeds == {0, 1}
    # Each record retains its own run-record provenance.
    ref_ids = {r.run_record_ref.run_id for r in store.failures}
    assert len(ref_ids) == 2


def test_different_environment_hash_is_not_deduplicated(tmp_path: Path) -> None:
    benchmark = _make_text_benchmark(tmp_path)
    store_path = tmp_path / "store.json"

    rec_a = tmp_path / "env-a.json"
    rec_b = tmp_path / "env-b.json"
    R.run_benchmark(benchmark, output=rec_a, model="stub", seed=0, now=_fixed_clock())

    # Produce a second run-record, then mutate its environment_hash to simulate
    # a different execution environment (same task/model/params/seed).
    R.run_benchmark(benchmark, output=rec_b, model="stub", seed=0, now=_fixed_clock())
    data_b = json.loads(rec_b.read_text(encoding="utf-8"))
    original_hash = data_b["environment_hash"]
    data_b["environment_hash"] = "sha256:" + "f" * 64
    data_b["run_id"] = "run-env-b"
    rec_b.write_text(json.dumps(data_b, sort_keys=True), encoding="utf-8")
    assert data_b["environment_hash"] != original_hash

    F.save_failures(rec_a, store_path, benchmark_dir=benchmark)
    F.save_failures(rec_b, store_path, benchmark_dir=benchmark)

    store = F.load_failure_store(store_path)
    # Same seed but different environment hash -> both records retained.
    assert len(store.failures) == 4
    env_hashes = {r.environment_hash for r in store.failures}
    assert len(env_hashes) == 2
    assert original_hash in env_hashes
    assert data_b["environment_hash"] in env_hashes


def test_dedup_key_covers_full_determinant_set() -> None:
    base = {
        "benchmark_id": "b",
        "case_id": "c",
        "manifest_version": "0.1.0",
        "fixture_version": "0.1.0",
        "prompt_version": "1",
        "model_id": "stub",
        "sampling_params": {"temperature": 0.0},
        "seed": 0,
        "verifier_version": "exact_match@1",
        "metric_params": {"case_sensitive": True},
        "environment_hash": "sha256:abc",
    }
    key_base = F.dedup_key(base)
    # Identical determinant set -> identical key.
    assert F.dedup_key(dict(base)) == key_base
    # Any single determinant field change -> different key.
    for field, new_val in [
        ("benchmark_id", "b2"),
        ("case_id", "c2"),
        ("manifest_version", "0.2.0"),
        ("fixture_version", "0.2.0"),
        ("prompt_version", "2"),
        ("model_id", "stub2"),
        ("sampling_params", {"temperature": 0.5}),
        ("seed", 1),
        ("verifier_version", "exact_match@2"),
        ("metric_params", {"case_sensitive": False}),
        ("environment_hash", "sha256:xyz"),
    ]:
        variant = dict(base)
        variant[field] = new_val
        assert F.dedup_key(variant) != key_base, f"dedup key insensitive to {field}"


# --- Schema validation and error paths --------------------------------------


def test_load_failure_store_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(F.FailureStoreError, match="not found"):
        F.load_failure_store(tmp_path / "nope.json")


def test_save_rejects_missing_run_record(tmp_path: Path) -> None:
    with pytest.raises(F.FailureStoreError, match="run-record not found"):
        F.save_failures(tmp_path / "nope.json", tmp_path / "store.json")


def test_save_skips_passing_cases(tmp_path: Path) -> None:
    benchmark = _make_text_benchmark(tmp_path)
    record_path = tmp_path / "mixed-record.json"
    store_path = tmp_path / "store.json"

    # One pass, one fail via predictions.
    preds = tmp_path / "preds-mixed"
    preds.mkdir()
    (preds / "case-1.txt").write_text("alpha", encoding="utf-8")
    (preds / "case-2.txt").write_text("wrong", encoding="utf-8")
    R.run_benchmark(benchmark, output=record_path, predictions=preds, now=_fixed_clock())

    store = F.save_failures(record_path, store_path, benchmark_dir=benchmark)
    assert len(store.failures) == 1
    assert store.failures[0].case_id == "case-2"


def test_export_rejects_empty_store(tmp_path: Path) -> None:
    store_path = tmp_path / "empty-store.json"
    F.write_failure_store(
        F.store_to_dict({"schema_version": "1", "storage_version": "1", "failures": []}),
        store_path,
    )
    with pytest.raises(F.FailureStoreError, match="empty"):
        F.export_hard_set(store_path, tmp_path / "out")


def test_export_rejects_multi_benchmark_store(tmp_path: Path) -> None:
    store_path = tmp_path / "multi-store.json"
    rec_a = {
        "schema_version": "1",
        "storage_version": "1",
        "failures": [
            _minimal_failure_dict(benchmark_id="b1", case_id="c1"),
            _minimal_failure_dict(benchmark_id="b2", case_id="c2"),
        ],
    }
    F.write_failure_store(rec_a, store_path)
    with pytest.raises(F.FailureStoreError, match="single benchmark"):
        F.export_hard_set(store_path, tmp_path / "out")


def test_save_without_benchmark_falls_back_to_rendered_prompt(tmp_path: Path) -> None:
    benchmark = _make_single_case_benchmark(tmp_path)
    record_path = tmp_path / "stub-record.json"
    store_path = tmp_path / "store.json"

    R.run_benchmark(benchmark, output=record_path, model="stub", now=_fixed_clock())
    store = F.save_failures(record_path, store_path)
    assert len(store.failures) == 1
    # Single-prompt run -> prompt.rendered is populated -> task_input preserved.
    assert isinstance(store.failures[0].task_input, str)
    assert store.failures[0].task_input


# --- Helpers ----------------------------------------------------------------


def _assert_store_validates(store_path: Path) -> None:
    schema = L.load_schema(F.FAILURE_STORE_SCHEMA_NAME)
    data = json.loads(store_path.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(data)


def _minimal_failure_dict(*, benchmark_id: str, case_id: str) -> dict[str, Any]:
    return {
        "benchmark_id": benchmark_id,
        "case_id": case_id,
        "manifest_version": "0.1.0",
        "fixture_version": "0.1.0",
        "prompt_version": "1",
        "model_id": "stub",
        "sampling_params": {"temperature": 0.0},
        "seed": 0,
        "verifier_version": "exact_match@1",
        "metric_params": {},
        "environment_hash": "sha256:" + "a" * 60,
        "task_input": "prompt",
        "model_output": "wrong",
        "expected": "right",
        "verifier_verdict": {"verdict": "fail", "score": 0.0},
        "run_record_ref": {"run_id": "run-x"},
    }


def _make_text_benchmark(tmp_path: Path) -> Path:
    bdir = tmp_path / "text-benchmark"
    cases = bdir / "cases"
    cases.mkdir(parents=True)
    _write_yaml(
        bdir / "benchmark.yaml",
        {
            "schema_version": "1",
            "id": "text-c09",
            "name": "Text C09",
            "description": "Failure-preservation fixture.",
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


def _make_single_case_benchmark(tmp_path: Path) -> Path:
    bdir = tmp_path / "single-case-benchmark"
    cases = bdir / "cases"
    cases.mkdir(parents=True)
    _write_yaml(
        bdir / "benchmark.yaml",
        {
            "schema_version": "1",
            "id": "single-c09",
            "name": "Single C09",
            "description": "Single-case failure-preservation fixture.",
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
    _write_yaml(cases / "case-1.yaml", _text_case("case-1", "Only", "right", ["smoke"]))
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


def _fixed_clock() -> Any:
    values = iter(["2026-06-27T00:00:00Z", "2026-06-27T00:00:01Z"])
    return lambda: next(values)


def _write_yaml(path: Path, data: Mapping[str, Any]) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
