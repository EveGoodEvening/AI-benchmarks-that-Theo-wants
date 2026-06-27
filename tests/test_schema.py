"""Schema and typed-contract acceptance/rejection tests for chunk C02.

These tests load the four v1 JSON Schemas from ``schemas/`` and assert:

  * Valid manifests/cases/run-records/failure-stores validate.
  * Invalid ones are rejected with actionable schema errors.
  * The benchmark ``status`` enum accepts ``experimental``/``stable`` and
    rejects unknown values; ``tags`` is a string array.
  * The case schema accepts the reserved ``smoke`` tag and rejects malformed
    tag arrays.
  * The run-record schema validates tool-action transcript and final
    repo-state fields, not just text-output records.
  * The failure-store schema validates a preserved failure record with the
    full reproducibility determinant set.
  * The typed contracts in ``ai_bench.types`` cannot silently drift from the
    schemas: representative fixtures built from the dataclasses validate
    against the schemas.

No real benchmark fixtures are added here -- only minimal test fixtures.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import jsonschema
import pytest

from ai_bench import types as T

SCHEMAS_DIR = Path(__file__).resolve().parents[1] / "schemas"


def _load_schema(name: str) -> dict[str, Any]:
    with (SCHEMAS_DIR / name).open("r", encoding="utf-8") as fh:
        import json

        return json.load(fh)


@pytest.fixture(scope="module")
def benchmark_schema() -> dict[str, Any]:
    return _load_schema("benchmark.schema.json")


@pytest.fixture(scope="module")
def case_schema() -> dict[str, Any]:
    return _load_schema("case.schema.json")


@pytest.fixture(scope="module")
def run_record_schema() -> dict[str, Any]:
    return _load_schema("run-record.schema.json")


@pytest.fixture(scope="module")
def failure_store_schema() -> dict[str, Any]:
    return _load_schema("failure-store.schema.json")


def _validate(schema: dict[str, Any], instance: Any) -> None:
    jsonschema.validate(instance=instance, schema=schema)


def _invalid(schema: dict[str, Any], instance: Any) -> jsonschema.ValidationError:
    with pytest.raises(jsonschema.ValidationError) as exc:
        jsonschema.validate(instance=instance, schema=schema)
    return exc.value


# --- Shared minimal fixtures ------------------------------------------------


def _valid_benchmark_manifest(
    *,
    status: str = "experimental",
    tags: list[str] | None = None,
    task_type: str = "text",
    verifier: str = "exact_match",
) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "schema_version": "1",
        "id": "description-label",
        "name": "Description-to-label",
        "description": "Map a description to a label.",
        "domain": "recreation",
        "task_type": task_type,
        "metric": {"verifier": verifier, "params": {"case_sensitive": False}},
        "version": "0.1.0",
        "contributor": {"name": "AI-bench contributors", "contact": "https://example.org"},
        "license": "MIT",
        "case_glob": "cases/*.yaml",
        "tags": tags if tags is not None else ["recreation", "spatial-reasoning"],
        "status": status,
    }
    if verifier == "llm_judge":
        manifest["llm_judge"] = {
            "judge_model": "pinned-judge",
            "judge_prompt": "Is this correct?",
            "judge_params": {"temperature": 0.0},
            "judge_seed": 1,
        }
    return manifest


def _valid_case(
    *,
    tags: list[str] | None = None,
    expected: Any = "label-a",
    expected_metadata: dict[str, Any] | None = None,
    task_type: str = "text",
) -> dict[str, Any]:
    case: dict[str, Any] = {
        "schema_version": "1",
        "id": "case-1",
        "input": "A small rounded hill of compact earth.",
        "expected": expected,
        "tags": tags if tags is not None else ["smoke"],
        "difficulty": "easy",
        "provenance": {"source": "original", "license": "MIT"},
    }
    if expected_metadata is not None:
        case["expected_metadata"] = expected_metadata
    if task_type == "tool-task":
        case["input"] = {"prompt": "Create a commit", "fixture": "fixtures/repo"}
        case["state_check"] = {
            "git": {"status_clean": True, "head_commit_message": "initial"}
        }
    return case


def _valid_tool_action() -> dict[str, Any]:
    return {
        "command": "git",
        "argv": ["commit", "-m", "initial"],
        "cwd": ".",
        "env_overrides": {"GIT_AUTHOR_NAME": "stub"},
        "stdin": None,
        "exit_code": 0,
        "stdout": "",
        "stderr": "",
        "wall_clock_ms": 12,
        "timeout": False,
        "sandbox_boundary_violation": False,
    }


def _valid_repo_state() -> dict[str, Any]:
    return {
        "file_tree": ["README.md", "src/main.py"],
        "git_status": "",
        "branches": ["main"],
        "commits": [{"sha": "abc1234", "subject": "initial"}],
        "diff": "",
    }


def _valid_run_record(*, task_type: str = "text") -> dict[str, Any]:
    case_result: dict[str, Any] = {
        "case_id": "case-1",
        "verdict": "pass",
        "score": 1.0,
        "expected": "label-a",
        "observed": "label-a",
        "error": None,
    }
    if task_type == "tool-task":
        case_result["transcript"] = [_valid_tool_action()]
        case_result["final_repo_state"] = _valid_repo_state()
    return {
        "schema_version": "1",
        "run_id": "run-0001",
        "benchmark": {
            "id": "description-label",
            "version": "0.1.0",
            "task_type": task_type,
            "domain": "recreation",
            "tags": ["recreation"],
            "status": "experimental",
        },
        "model": {"id": "stub", "adapter": "stub"},
        "prompt": {"version": "0.1.0", "template": "Describe: {input}"},
        "sampling_params": {"temperature": 0.0, "max_tokens": 16},
        "seed": 0,
        "fixture_version": "0.1.0",
        "manifest_version": "0.1.0",
        "environment_hash": "sha256:deadbeefdeadbeef",
        "environment": {
            "sandbox_backend": "in-process",
            "python": "3.11",
            "os": "linux",
            "runner_version": "0.1.0",
        },
        "metric_params": {"case_sensitive": False},
        "verifier": {"name": "exact_match", "version": "1.0.0"},
        "tag_filter": "smoke",
        "cases": [case_result],
        "aggregate": {
            "metric": "exact_match",
            "value": 1.0,
            "n_cases": 1,
            "n_pass": 1,
            "n_fail": 0,
        },
    }


def _valid_failure_record() -> dict[str, Any]:
    return {
        "benchmark_id": "description-label",
        "case_id": "case-2",
        "manifest_version": "0.1.0",
        "fixture_version": "0.1.0",
        "prompt_version": "0.1.0",
        "model_id": "stub",
        "sampling_params": {"temperature": 0.0},
        "seed": 0,
        "verifier_version": "exact_match@1.0.0",
        "metric_params": {"case_sensitive": False},
        "environment_hash": "sha256:cafecafecafecafe",
        "task_input": "A small rounded hill of compact earth.",
        "model_output": "mountain",
        "expected": "knoll",
        "verifier_verdict": {"verdict": "fail", "score": 0.0, "reason": "mismatch"},
        "run_record_ref": {"run_id": "run-0001", "path": "run-records/run-0001.json"},
        "preserved_at": "2026-06-27T00:00:00Z",
    }


def _valid_failure_store() -> dict[str, Any]:
    return {
        "schema_version": "1",
        "storage_version": "1.0.0",
        "benchmark_id": "description-label",
        "created_at": "2026-06-27T00:00:00Z",
        "updated_at": "2026-06-27T00:00:00Z",
        "failures": [_valid_failure_record()],
    }


# === Benchmark schema =======================================================


class TestBenchmarkSchema:
    def test_valid_manifest_accepts(self, benchmark_schema: dict[str, Any]) -> None:
        _validate(benchmark_schema, _valid_benchmark_manifest())

    def test_status_experimental_and_stable_accepted(
        self, benchmark_schema: dict[str, Any]
    ) -> None:
        for status in ("experimental", "stable"):
            _validate(benchmark_schema, _valid_benchmark_manifest(status=status))

    def test_status_unknown_rejected(self, benchmark_schema: dict[str, Any]) -> None:
        err = _invalid(benchmark_schema, _valid_benchmark_manifest(status="draft"))
        assert "status" in str(err.message).lower() or "draft" in str(err).lower()

    def test_status_defaults_to_experimental_when_omitted(
        self, benchmark_schema: dict[str, Any]
    ) -> None:
        manifest = _valid_benchmark_manifest()
        del manifest["status"]
        # Default applied by the loader (C03); schema itself permits omission.
        _validate(benchmark_schema, manifest)

    def test_tags_is_string_array(self, benchmark_schema: dict[str, Any]) -> None:
        _validate(benchmark_schema, _valid_benchmark_manifest(tags=["recreation", "spatial-reasoning"]))

    def test_tags_non_string_rejected(self, benchmark_schema: dict[str, Any]) -> None:
        err = _invalid(benchmark_schema, _valid_benchmark_manifest(tags=["ok", 5]))
        assert err.instance == 5 or "is not of type" in str(err)

    def test_tags_duplicate_rejected(self, benchmark_schema: dict[str, Any]) -> None:
        err = _invalid(
            benchmark_schema, _valid_benchmark_manifest(tags=["recreation", "recreation"])
        )
        assert "unique" in str(err).lower()

    def test_missing_required_identity_fields_rejected(
        self, benchmark_schema: dict[str, Any]
    ) -> None:
        for field in ("id", "name", "version", "contributor", "license", "case_glob"):
            manifest = _valid_benchmark_manifest()
            del manifest[field]
            err = _invalid(benchmark_schema, manifest)
            assert field in str(err).lower()

    def test_missing_provenance_license_rejected(
        self, benchmark_schema: dict[str, Any]
    ) -> None:
        manifest = _valid_benchmark_manifest()
        del manifest["license"]
        err = _invalid(benchmark_schema, manifest)
        assert "license" in str(err).lower()

    def test_unknown_task_type_rejected(self, benchmark_schema: dict[str, Any]) -> None:
        err = _invalid(benchmark_schema, _valid_benchmark_manifest(task_type="vision"))
        assert "task_type" in str(err).lower() or "vision" in str(err).lower()

    def test_unknown_verifier_rejected(self, benchmark_schema: dict[str, Any]) -> None:
        manifest = _valid_benchmark_manifest()
        manifest["metric"]["verifier"] = "magic"
        err = _invalid(benchmark_schema, manifest)
        assert "verifier" in str(err).lower() or "magic" in str(err).lower()

    def test_all_v1_verifier_types_accepted(
        self, benchmark_schema: dict[str, Any]
    ) -> None:
        for verifier in (
            "exact_match",
            "contains_any",
            "regex_match",
            "set_f1",
            "state_check",
            "llm_judge",
        ):
            manifest = _valid_benchmark_manifest(verifier=verifier)
            if verifier == "state_check":
                manifest["task_type"] = "tool-task"
            _validate(benchmark_schema, manifest)

    def test_llm_judge_metric_without_pinned_config_rejected(
        self, benchmark_schema: dict[str, Any]
    ) -> None:
        # An llm_judge benchmark metric must pin judge metadata; the helper
        # adds it by default, so strip it to assert rejection.
        manifest = _valid_benchmark_manifest(verifier="llm_judge")
        del manifest["llm_judge"]
        err = _invalid(benchmark_schema, manifest)
        assert "llm_judge" in str(err).lower()


# === Case schema ============================================================


class TestCaseSchema:
    def test_valid_case_accepts(self, case_schema: dict[str, Any]) -> None:
        _validate(case_schema, _valid_case())

    def test_smoke_tag_accepted(self, case_schema: dict[str, Any]) -> None:
        _validate(case_schema, _valid_case(tags=["smoke"]))

    def test_malformed_tag_array_rejected(self, case_schema: dict[str, Any]) -> None:
        err = _invalid(case_schema, _valid_case(tags=["smoke", "SMOKE"]))
        # uppercase violates the pattern
        assert "pattern" in str(err).lower() or "SMOKE" in str(err)

    def test_tags_non_string_rejected(self, case_schema: dict[str, Any]) -> None:
        err = _invalid(case_schema, _valid_case(tags=[None]))
        assert err.instance is None or "is not of type" in str(err)

    def test_tags_duplicate_rejected(self, case_schema: dict[str, Any]) -> None:
        err = _invalid(case_schema, _valid_case(tags=["smoke", "smoke"]))
        assert "unique" in str(err).lower()

    def test_null_expected_requires_metadata(self, case_schema: dict[str, Any]) -> None:
        # null expected WITHOUT metadata is rejected by the allOf rule.
        err = _invalid(case_schema, _valid_case(expected=None, expected_metadata=None))
        assert "expected_metadata" in str(err).lower() or "required" in str(err).lower()

    def test_null_expected_with_metadata_accepted(
        self, case_schema: dict[str, Any]
    ) -> None:
        case = _valid_case(
            expected=None,
            expected_metadata={
                "reason": "preserved_failure_case",
                "source_run_record": "run-0001",
            },
        )
        _validate(case_schema, case)

    def test_missing_required_id_rejected(self, case_schema: dict[str, Any]) -> None:
        case = _valid_case()
        del case["id"]
        err = _invalid(case_schema, case)
        assert "id" in str(err).lower()

    def test_tool_task_state_check_accepted(self, case_schema: dict[str, Any]) -> None:
        _validate(case_schema, _valid_case(task_type="tool-task"))

    def test_llm_judge_config_accepted(self, case_schema: dict[str, Any]) -> None:
        case = _valid_case()
        case["verifier"] = {"verifier": "llm_judge", "params": {}}
        case["llm_judge"] = {
            "judge_model": "pinned-judge",
            "judge_prompt": "Is this correct?",
            "judge_params": {"temperature": 0.0},
            "judge_seed": 1,
        }
        _validate(case_schema, case)

    def test_additional_properties_rejected(self, case_schema: dict[str, Any]) -> None:
        case = _valid_case()
        case["unexpected_field"] = "boom"
        err = _invalid(case_schema, case)
        assert "unexpected_field" in str(err) or "additional" in str(err).lower()

    def test_normal_case_missing_expected_rejected(
        self, case_schema: dict[str, Any]
    ) -> None:
        # A normal (non-failure) case must carry a non-null scoring target.
        case = _valid_case()
        del case["expected"]
        err = _invalid(case_schema, case)
        assert "expected" in str(err).lower()

    def test_normal_case_missing_provenance_rejected(
        self, case_schema: dict[str, Any]
    ) -> None:
        case = _valid_case()
        del case["provenance"]
        err = _invalid(case_schema, case)
        assert "provenance" in str(err).lower()

    def test_normal_case_provenance_without_license_rejected(
        self, case_schema: dict[str, Any]
    ) -> None:
        case = _valid_case()
        case["provenance"] = {"source": "original"}
        err = _invalid(case_schema, case)
        assert "license" in str(err).lower()

    def test_state_check_verifier_without_state_check_block_rejected(
        self, case_schema: dict[str, Any]
    ) -> None:
        case = _valid_case()
        case["verifier"] = {"verifier": "state_check", "params": {}}
        err = _invalid(case_schema, case)
        assert "state_check" in str(err).lower()

    def test_llm_judge_verifier_without_pinned_config_rejected(
        self, case_schema: dict[str, Any]
    ) -> None:
        case = _valid_case()
        case["verifier"] = {"verifier": "llm_judge", "params": {}}
        err = _invalid(case_schema, case)
        assert "llm_judge" in str(err).lower()


# === Run-record schema ======================================================


class TestRunRecordSchema:
    def test_valid_text_run_record_accepts(
        self, run_record_schema: dict[str, Any]
    ) -> None:
        _validate(run_record_schema, _valid_run_record(task_type="text"))

    def test_valid_tool_task_run_record_with_transcript_accepts(
        self, run_record_schema: dict[str, Any]
    ) -> None:
        _validate(run_record_schema, _valid_run_record(task_type="tool-task"))

    def test_tool_action_transcript_fields_validated(
        self, run_record_schema: dict[str, Any]
    ) -> None:
        record = _valid_run_record(task_type="tool-task")
        action = record["cases"][0]["transcript"][0]
        # Remove a required frozen field -> rejected.
        for field in (
            "command",
            "argv",
            "cwd",
            "exit_code",
            "wall_clock_ms",
            "timeout",
            "sandbox_boundary_violation",
        ):
            bad = {k: v for k, v in action.items() if k != field}
            record["cases"][0]["transcript"] = [bad]
            err = _invalid(run_record_schema, record)
            assert field in str(err).lower()
            # restore for next iteration
            record["cases"][0]["transcript"] = [action]

    def test_tool_action_env_overrides_string_values(
        self, run_record_schema: dict[str, Any]
    ) -> None:
        record = _valid_run_record(task_type="tool-task")
        record["cases"][0]["transcript"][0]["env_overrides"] = {"PATH": "/usr/bin"}
        _validate(run_record_schema, record)

    def test_repo_state_snapshot_validated(
        self, run_record_schema: dict[str, Any]
    ) -> None:
        record = _valid_run_record(task_type="tool-task")
        record["cases"][0]["final_repo_state"] = _valid_repo_state()
        _validate(run_record_schema, record)

    def test_repo_state_missing_fields_ok(
        self, run_record_schema: dict[str, Any]
    ) -> None:
        # repo_state properties are all optional.
        record = _valid_run_record(task_type="tool-task")
        record["cases"][0]["final_repo_state"] = {}
        _validate(run_record_schema, record)

    def test_missing_required_reproducibility_fields_rejected(
        self, run_record_schema: dict[str, Any]
    ) -> None:
        for field in (
            "model",
            "prompt",
            "sampling_params",
            "seed",
            "fixture_version",
            "manifest_version",
            "environment_hash",
            "metric_params",
        ):
            record = _valid_run_record()
            del record[field]
            err = _invalid(run_record_schema, record)
            assert field in str(err).lower()

    def test_verifier_names_enum_enforced(
        self, run_record_schema: dict[str, Any]
    ) -> None:
        record = _valid_run_record()
        record["verifier"] = {"name": "magic", "version": "1.0.0"}
        err = _invalid(run_record_schema, record)
        assert "verifier" in str(err).lower() or "magic" in str(err).lower()

    def test_failed_verdict_recorded_as_data(
        self, run_record_schema: dict[str, Any]
    ) -> None:
        record = _valid_run_record()
        record["cases"][0]["verdict"] = "fail"
        record["cases"][0]["score"] = 0.0
        record["aggregate"]["n_pass"] = 0
        record["aggregate"]["n_fail"] = 1
        record["aggregate"]["value"] = 0.0
        _validate(run_record_schema, record)

    def test_adapter_enum_enforced(self, run_record_schema: dict[str, Any]) -> None:
        record = _valid_run_record()
        record["model"]["adapter"] = "magic"
        err = _invalid(run_record_schema, record)
        assert "adapter" in str(err).lower() or "magic" in str(err).lower()

    def test_text_result_without_raw_output_rejected(
        self, run_record_schema: dict[str, Any]
    ) -> None:
        # Text benchmark runs must preserve per-case raw text output.
        record = _valid_run_record(task_type="text")
        del record["cases"][0]["observed"]
        err = _invalid(run_record_schema, record)
        assert "observed" in str(err).lower()

    def test_tool_task_result_without_transcript_rejected(
        self, run_record_schema: dict[str, Any]
    ) -> None:
        record = _valid_run_record(task_type="tool-task")
        del record["cases"][0]["transcript"]
        err = _invalid(run_record_schema, record)
        assert "transcript" in str(err).lower()

    def test_tool_task_result_without_final_repo_state_rejected(
        self, run_record_schema: dict[str, Any]
    ) -> None:
        record = _valid_run_record(task_type="tool-task")
        del record["cases"][0]["final_repo_state"]
        err = _invalid(run_record_schema, record)
        assert "final_repo_state" in str(err).lower()

    def test_replay_result_without_transcript_rejected(
        self, run_record_schema: dict[str, Any]
    ) -> None:
        # Replay adapter runs must preserve transcript + final repo state.
        record = _valid_run_record(task_type="text")
        record["model"]["adapter"] = "replay"
        err = _invalid(run_record_schema, record)
        assert "transcript" in str(err).lower() or "final_repo_state" in str(err).lower()


# === Failure-store schema ===================================================


class TestFailureStoreSchema:
    def test_valid_failure_store_accepts(
        self, failure_store_schema: dict[str, Any]
    ) -> None:
        _validate(failure_store_schema, _valid_failure_store())

    def test_empty_failures_accepted(
        self, failure_store_schema: dict[str, Any]
    ) -> None:
        store = _valid_failure_store()
        store["failures"] = []
        _validate(failure_store_schema, store)

    def test_full_determinant_set_required(
        self, failure_store_schema: dict[str, Any]
    ) -> None:
        # Every determinant field is required on a failure record.
        determinant_fields = (
            "benchmark_id",
            "case_id",
            "manifest_version",
            "fixture_version",
            "prompt_version",
            "model_id",
            "sampling_params",
            "seed",
            "verifier_version",
            "metric_params",
            "environment_hash",
            "run_record_ref",
        )
        for field in determinant_fields:
            store = _valid_failure_store()
            del store["failures"][0][field]
            err = _invalid(failure_store_schema, store)
            assert field in str(err).lower()

    def test_verifier_verdict_must_be_fail(
        self, failure_store_schema: dict[str, Any]
    ) -> None:
        store = _valid_failure_store()
        store["failures"][0]["verifier_verdict"]["verdict"] = "pass"
        err = _invalid(failure_store_schema, store)
        assert "verdict" in str(err).lower() or "pass" in str(err).lower()

    def test_storage_version_required(
        self, failure_store_schema: dict[str, Any]
    ) -> None:
        store = _valid_failure_store()
        del store["storage_version"]
        err = _invalid(failure_store_schema, store)
        assert "storage_version" in str(err).lower()

    def test_run_record_ref_run_id_required(
        self, failure_store_schema: dict[str, Any]
    ) -> None:
        store = _valid_failure_store()
        del store["failures"][0]["run_record_ref"]["run_id"]
        err = _invalid(failure_store_schema, store)
        assert "run_id" in str(err).lower()

    def test_null_expected_with_metadata_accepted(
        self, failure_store_schema: dict[str, Any]
    ) -> None:
        store = _valid_failure_store()
        store["failures"][0]["expected"] = None
        store["failures"][0]["expected_metadata"] = {"reason": "preserved_failure_case"}
        _validate(failure_store_schema, store)

    def test_null_expected_without_metadata_rejected(
        self, failure_store_schema: dict[str, Any]
    ) -> None:
        store = _valid_failure_store()
        store["failures"][0]["expected"] = None
        err = _invalid(failure_store_schema, store)
        assert "expected_metadata" in str(err).lower() or "reason" in str(err).lower()

    def test_null_expected_metadata_without_reason_rejected(
        self, failure_store_schema: dict[str, Any]
    ) -> None:
        store = _valid_failure_store()
        store["failures"][0]["expected"] = None
        store["failures"][0]["expected_metadata"] = {"source_run_record": "run-0001"}
        err = _invalid(failure_store_schema, store)
        assert "reason" in str(err).lower()


# === Typed-contract / schema drift guard ====================================


class TestTypedContractDrift:
    """The dataclasses in ``ai_bench.types`` must stay aligned with the schemas.

    We build representative instances from the typed contracts, serialize them
    to plain JSON-compatible dicts, and validate against the schemas. If a
    schema field is added/renamed without updating the dataclass (or vice
    versa), these tests fail.
    """

    def test_benchmark_manifest_dataclass_validates(
        self, benchmark_schema: dict[str, Any]
    ) -> None:
        manifest = T.BenchmarkManifest(
            schema_version="1",
            id="description-label",
            name="Description-to-label",
            description="Map a description to a label.",
            domain="recreation",
            task_type="text",
            metric=T.MetricConfig(verifier="exact_match", params={"case_sensitive": False}),
            version="0.1.0",
            contributor=T.Contributor(name="AI-bench contributors", contact="https://example.org"),
            license="MIT",
            case_glob="cases/*.yaml",
            tags=("recreation", "spatial-reasoning"),
            status="experimental",
        )
        _validate(benchmark_schema, _dataclass_to_dict(manifest))

    def test_benchmark_manifest_llm_judge_dataclass_validates(
        self, benchmark_schema: dict[str, Any]
    ) -> None:
        manifest = T.BenchmarkManifest(
            schema_version="1",
            id="llm-judged-bench",
            name="LLM-judged benchmark",
            description="A benchmark scored by a pinned LLM judge.",
            domain="recreation",
            task_type="text",
            metric=T.MetricConfig(verifier="llm_judge", params={}),
            version="0.1.0",
            contributor=T.Contributor(name="AI-bench contributors"),
            license="MIT",
            case_glob="cases/*.yaml",
            tags=("recreation",),
            status="experimental",
            llm_judge=T.LLMJudgeConfig(
                judge_model="pinned-judge",
                judge_prompt="Is this correct?",
                judge_params={"temperature": 0.0},
                judge_seed=1,
            ),
        )
        _validate(benchmark_schema, _dataclass_to_dict(manifest))

    def test_case_definition_dataclass_validates(
        self, case_schema: dict[str, Any]
    ) -> None:
        case = T.CaseDefinition(
            schema_version="1",
            id="case-1",
            input="A small rounded hill of compact earth.",
            expected="knoll",
            tags=("smoke",),
            difficulty="easy",
            provenance=T.Provenance(source="original", license="MIT"),
        )
        _validate(case_schema, _dataclass_to_dict(case))

    def test_case_definition_null_expected_with_metadata_validates(
        self, case_schema: dict[str, Any]
    ) -> None:
        case = T.CaseDefinition(
            schema_version="1",
            id="case-fail",
            input="A preserved failure case.",
            expected=None,
            expected_metadata={"reason": "preserved_failure_case", "source_run_record": "run-0001"},
            tags=(),
        )
        serialized = _dataclass_to_dict(case)
        # A preserved failure case serializes expected as an explicit null so
        # the schema's null-expected branch (requiring expected_metadata.reason)
        # applies; _dataclass_to_dict omits None, so re-inject it here.
        serialized["expected"] = None
        _validate(case_schema, serialized)

    def test_run_record_dataclass_validates_text(
        self, run_record_schema: dict[str, Any]
    ) -> None:
        record = T.RunRecord(
            schema_version="1",
            run_id="run-0001",
            benchmark=T.BenchmarkRef(
                id="description-label",
                version="0.1.0",
                task_type="text",
                domain="recreation",
                tags=("recreation",),
                status="experimental",
            ),
            model=T.ModelRef(id="stub", adapter="stub"),
            prompt=T.RunPrompt(version="0.1.0", template="Describe: {input}"),
            sampling_params={"temperature": 0.0, "max_tokens": 16},
            seed=0,
            fixture_version="0.1.0",
            manifest_version="0.1.0",
            environment_hash="sha256:deadbeefdeadbeef",
            metric_params={"case_sensitive": False},
            cases=(
                T.CaseResult(
                    case_id="case-1",
                    verdict="pass",
                    score=1.0,
                    expected="knoll",
                    observed="knoll",
                    error=None,
                ),
            ),
            aggregate=T.AggregateScore(
                metric="exact_match",
                value=1.0,
                n_cases=1,
                n_pass=1,
                n_fail=0,
            ),
            environment=T.RunEnvironment(
                sandbox_backend="in-process",
                python="3.11",
                os="linux",
                runner_version="0.1.0",
            ),
            verifier=T.RunVerifier(name="exact_match", version="1.0.0"),
            tag_filter="smoke",
        )
        _validate(run_record_schema, _dataclass_to_dict(record))

    def test_run_record_dataclass_validates_tool_task_with_transcript(
        self, run_record_schema: dict[str, Any]
    ) -> None:
        record = T.RunRecord(
            schema_version="1",
            run_id="run-0002",
            benchmark=T.BenchmarkRef(
                id="git-tooling",
                version="0.1.0",
                task_type="tool-task",
                domain="tool-use",
                tags=("tool-use",),
                status="experimental",
            ),
            model=T.ModelRef(id="stub", adapter="agent"),
            prompt=T.RunPrompt(version="0.1.0", template="Create a commit"),
            sampling_params={"temperature": 0.0},
            seed=0,
            fixture_version="0.1.0",
            manifest_version="0.1.0",
            environment_hash="sha256:cafecafecafecafe",
            metric_params={},
            cases=(
                T.CaseResult(
                    case_id="case-1",
                    verdict="pass",
                    score=1.0,
                    expected=None,
                    observed=None,
                    transcript=(
                        T.ToolAction(
                            command="git",
                            argv=("commit", "-m", "initial"),
                            cwd=".",
                            exit_code=0,
                            wall_clock_ms=12,
                            timeout=False,
                            sandbox_boundary_violation=False,
                            env_overrides={"GIT_AUTHOR_NAME": "stub"},
                            stdin=None,
                            stdout="",
                            stderr="",
                        ),
                    ),
                    final_repo_state=T.RepoState(
                        file_tree=("README.md",),
                        git_status="",
                        branches=("main",),
                        commits=({"sha": "abc1234", "subject": "initial"},),
                        diff="",
                    ),
                ),
            ),
            aggregate=T.AggregateScore(
                metric="state_check",
                value=1.0,
                n_cases=1,
                n_pass=1,
                n_fail=0,
            ),
            verifier=T.RunVerifier(name="state_check", version="1.0.0"),
            tag_filter="smoke",
        )
        _validate(run_record_schema, _dataclass_to_dict(record))

    def test_failure_store_dataclass_validates(
        self, failure_store_schema: dict[str, Any]
    ) -> None:
        store = T.FailureStore(
            schema_version="1",
            storage_version="1.0.0",
            failures=(
                T.FailureRecord(
                    benchmark_id="description-label",
                    case_id="case-2",
                    manifest_version="0.1.0",
                    fixture_version="0.1.0",
                    prompt_version="0.1.0",
                    model_id="stub",
                    sampling_params={"temperature": 0.0},
                    seed=0,
                    verifier_version="exact_match@1.0.0",
                    metric_params={"case_sensitive": False},
                    environment_hash="sha256:cafecafecafecafe",
                    task_input="A small rounded hill of compact earth.",
                    model_output="mountain",
                    expected="knoll",
                    verifier_verdict=T.FailureVerifierVerdict(
                        verdict="fail", score=0.0, reason="mismatch"
                    ),
                    run_record_ref=T.RunRecordRef(
                        run_id="run-0001", path="run-records/run-0001.json"
                    ),
                    preserved_at="2026-06-27T00:00:00Z",
                ),
            ),
            benchmark_id="description-label",
            created_at="2026-06-27T00:00:00Z",
            updated_at="2026-06-27T00:00:00Z",
        )
        _validate(failure_store_schema, _dataclass_to_dict(store))

    def test_schema_version_constant_matches_v1(self) -> None:
        assert T.SCHEMA_VERSION == "1"


# === Schema freeze / v1 scope ===============================================


class TestSchemaFreeze:
    def test_all_four_schemas_exist(self) -> None:
        for name in (
            "benchmark.schema.json",
            "case.schema.json",
            "run-record.schema.json",
            "failure-store.schema.json",
        ):
            assert (SCHEMAS_DIR / name).is_file(), f"missing schema: {name}"

    def test_all_schemas_pin_v1_schema_version(self) -> None:
        for name in (
            "benchmark.schema.json",
            "case.schema.json",
            "run-record.schema.json",
            "failure-store.schema.json",
        ):
            schema = _load_schema(name)
            # The schema_version property must be pinned to "1" via const.
            props = schema.get("properties", {})
            assert props.get("schema_version", {}).get("const") == "1", (
                f"{name} does not pin schema_version to '1'"
            )


# --- helpers ----------------------------------------------------------------


def _dataclass_to_dict(obj: Any) -> Any:
    """Recursively convert a frozen dataclass instance to a JSON-compatible dict.

    Omits ``None`` values so optional fields absent from the schema instance do
    not trigger spurious rejections, and converts tuples to lists.
    """
    import dataclasses

    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        out: dict[str, Any] = {}
        for f in dataclasses.fields(obj):
            val = getattr(obj, f.name)
            if val is None:
                continue
            out[f.name] = _dataclass_to_dict(val)
        return out
    if isinstance(obj, (tuple, list)):
        return [_dataclass_to_dict(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _dataclass_to_dict(v) for k, v in obj.items() if v is not None}
    return obj
