"""Failure-case preservation, retry, and hard-set export (chunk C09).

This module is the public failure-preservation entry point owned by C09.  It
consumes schema-valid C05 run-records produced by actual ``ai-bench run``
invocations, extracts cases with failed verifier verdicts, and creates or
updates a versioned failure store conforming to ``schemas/failure-store.schema.json``
(frozen by C02).  It also replays stored failures (retry) and turns curated
failures into a runnable benchmark subset (hard-set export).

Scope (C09):
  * ``save_failures`` / ``ai-bench failures save <run-record> --store <failure-store>``:
    extract failed cases from a run-record, build failure records carrying the
    full reproducibility determinant set, deduplicate against the existing
    store, and write a schema-valid failure store.
  * ``retry_failures`` / ``ai-bench retry <failure-store> --benchmark <dir>``:
    replay stored failures through the public runner and classify each as
    improved / regressed / unchanged based on verifier verdicts (not string
    guesses).
  * ``export_hard_set`` / ``ai-bench hard-set export <failure-store> --output <dir>``:
    turn curated failures into a runnable benchmark subset that preserves
    provenance back to the original failure cases.

Deduplication is keyed by the full reproducibility determinant set defined in
the failure-store schema: benchmark/case id, manifest/fixture version, prompt
or prompt-template version, model id, sampling params, seed, verifier/scorer
version or metric params, and environment hash.  Task/model/params/
fixture-version alone is insufficient.

C09 adds no schema files.  It consumes the C02 failure-store schema, the C05
run-record/exit semantics, and the C06/C08 benchmarks via the public runner.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import jsonschema
import yaml

from ai_bench import __version__
from ai_bench import loader as L
from ai_bench import runner as R
from ai_bench import run_records as RR
from ai_bench import types as T

__all__ = [
    "FailureStoreError",
    "FailureStoreValidationError",
    "FAILURE_STORE_SCHEMA_NAME",
    "STORAGE_VERSION",
    "dedup_key",
    "failure_record_to_dict",
    "store_to_dict",
    "store_from_dict",
    "validate_failure_store",
    "load_failure_store",
    "write_failure_store",
    "save_failures",
    "retry_failures",
    "RetryOutcome",
    "export_hard_set",
]

FAILURE_STORE_SCHEMA_NAME = "failure-store.schema.json"

# On-disk storage format version. Bumped when the store layout changes; distinct
# from schema_version (which is pinned to "1" by the C02 schema).
STORAGE_VERSION: str = "1"


# --- Errors ------------------------------------------------------------------


class FailureStoreError(Exception):
    """Base error for failure-store serialization, I/O, and preservation failures."""


class FailureStoreValidationError(FailureStoreError):
    """Raised when a failure store does not conform to the C02 schema."""

    def __init__(self, message: str, errors: Sequence[str] = ()) -> None:
        super().__init__(message)
        self.errors = tuple(errors)


# --- Schema loading ----------------------------------------------------------


@dataclass(frozen=True)
class _SchemaPieces:
    schema: Mapping[str, Any]
    validator: jsonschema.Draft202012Validator


_schema_pieces: _SchemaPieces | None = None


def _schema() -> _SchemaPieces:
    global _schema_pieces
    if _schema_pieces is None:
        schema = L.load_schema(FAILURE_STORE_SCHEMA_NAME)
        _schema_pieces = _SchemaPieces(
            schema=schema,
            validator=jsonschema.Draft202012Validator(schema),
        )
    return _schema_pieces


# --- Deduplication -----------------------------------------------------------


# Fields that form the full reproducibility determinant set.  Order is fixed so
# the computed dedup key is stable across runs.
_DETERMINANT_FIELDS: tuple[str, ...] = (
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
)


def dedup_key(record: Mapping[str, Any]) -> str:
    """Compute a deterministic dedup key from the full determinant set.

    The key is a SHA-256 digest of the canonical JSON encoding of the
    determinant fields.  Two failure records preserve the same failure only when
    every determinant field matches; task/model/params/fixture-version alone is
    insufficient.
    """
    payload: dict[str, Any] = {}
    for field in _DETERMINANT_FIELDS:
        payload[field] = L.canonicalize(record.get(field))
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


# --- Serialization -----------------------------------------------------------


def failure_record_to_dict(record: T.FailureRecord | Mapping[str, Any]) -> dict[str, Any]:
    """Convert a ``FailureRecord`` dataclass or mapping into schema JSON."""
    if isinstance(record, Mapping):
        return dict(record)

    out: dict[str, Any] = {
        "benchmark_id": record.benchmark_id,
        "case_id": record.case_id,
        "manifest_version": record.manifest_version,
        "fixture_version": record.fixture_version,
        "prompt_version": record.prompt_version,
        "model_id": record.model_id,
        "sampling_params": dict(record.sampling_params),
        "seed": record.seed,
        "verifier_version": record.verifier_version,
        "metric_params": dict(record.metric_params),
        "environment_hash": record.environment_hash,
        "task_input": L.canonicalize(record.task_input),
        "model_output": L.canonicalize(record.model_output),
        "expected": L.canonicalize(record.expected),
        "verifier_verdict": {
            "verdict": record.verifier_verdict.verdict,
        },
        "run_record_ref": {
            "run_id": record.run_record_ref.run_id,
        },
    }
    if record.verifier_verdict.score is not None:
        out["verifier_verdict"]["score"] = record.verifier_verdict.score
    if record.verifier_verdict.reason is not None:
        out["verifier_verdict"]["reason"] = record.verifier_verdict.reason
    if record.run_record_ref.path is not None:
        out["run_record_ref"]["path"] = record.run_record_ref.path
    if record.expected_metadata is not None:
        out["expected_metadata"] = L.canonicalize(dict(record.expected_metadata))
    if record.preserved_at is not None:
        out["preserved_at"] = record.preserved_at
    if record.dedup_key is not None:
        out["dedup_key"] = record.dedup_key
    return out


def store_to_dict(store: T.FailureStore | Mapping[str, Any]) -> dict[str, Any]:
    """Convert a ``FailureStore`` dataclass or mapping into schema JSON."""
    if isinstance(store, Mapping):
        return dict(store)

    out: dict[str, Any] = {
        "schema_version": store.schema_version,
        "storage_version": store.storage_version,
        "failures": [failure_record_to_dict(f) for f in store.failures],
    }
    if store.benchmark_id is not None:
        out["benchmark_id"] = store.benchmark_id
    if store.created_at is not None:
        out["created_at"] = store.created_at
    if store.updated_at is not None:
        out["updated_at"] = store.updated_at
    return out


def store_from_dict(data: Mapping[str, Any]) -> T.FailureStore:
    """Materialize a ``FailureStore`` dataclass from schema JSON."""
    failures: list[T.FailureRecord] = []
    for raw in data.get("failures", []):
        failures.append(_failure_record_from_mapping(raw))
    return T.FailureStore(
        schema_version=data["schema_version"],  # type: ignore[arg-type]
        storage_version=data["storage_version"],
        failures=tuple(failures),
        benchmark_id=data.get("benchmark_id"),
        created_at=data.get("created_at"),
        updated_at=data.get("updated_at"),
    )


def _failure_record_from_mapping(data: Mapping[str, Any]) -> T.FailureRecord:
    verdict_raw = data["verifier_verdict"]
    ref_raw = data["run_record_ref"]
    return T.FailureRecord(
        benchmark_id=data["benchmark_id"],
        case_id=data["case_id"],
        manifest_version=data["manifest_version"],
        fixture_version=data["fixture_version"],
        prompt_version=data["prompt_version"],
        model_id=data["model_id"],
        sampling_params=dict(data["sampling_params"]),
        seed=data["seed"],
        verifier_version=data["verifier_version"],
        metric_params=dict(data["metric_params"]),
        environment_hash=data["environment_hash"],
        task_input=data["task_input"],
        model_output=data["model_output"],
        expected=data.get("expected"),
        expected_metadata=dict(data["expected_metadata"]) if data.get("expected_metadata") else None,
        verifier_verdict=T.FailureVerifierVerdict(
            verdict=verdict_raw["verdict"],  # type: ignore[arg-type]
            score=verdict_raw.get("score"),
            reason=verdict_raw.get("reason"),
        ),
        run_record_ref=T.RunRecordRef(
            run_id=ref_raw["run_id"],
            path=ref_raw.get("path"),
        ),
        preserved_at=data.get("preserved_at"),
        dedup_key=data.get("dedup_key"),
    )


# --- Validation --------------------------------------------------------------


def validate_failure_store(store: T.FailureStore | Mapping[str, Any]) -> dict[str, Any]:
    """Validate a failure store against ``schemas/failure-store.schema.json``."""
    data = store_to_dict(store) if isinstance(store, T.FailureStore) else dict(store)
    pieces = _schema()
    errors = sorted(
        pieces.validator.iter_errors(data),
        key=_error_sort_key,
    )
    if errors:
        formatted = "; ".join(_format_error(e) for e in errors)
        raise FailureStoreValidationError(
            f"failure store failed schema validation: {formatted}",
            errors=[_format_error(e) for e in errors],
        )
    return data


def _error_sort_key(error: jsonschema.ValidationError) -> tuple[str, str]:
    path = ".".join(str(p) for p in error.absolute_path)
    return (path, error.message)


def _format_error(error: jsonschema.ValidationError) -> str:
    path = ".".join(str(p) for p in error.absolute_path) or "<root>"
    return f"{path}: {error.message}"


# --- I/O ---------------------------------------------------------------------


def load_failure_store(path: Path | str) -> T.FailureStore:
    """Load and validate a failure store from disk."""
    p = Path(path)
    if not p.is_file():
        raise FailureStoreError(f"failure store not found: {p}")
    try:
        raw = L.load_json(p)
    except L.LoadError as exc:
        raise FailureStoreError(str(exc)) from exc
    if not isinstance(raw, dict):
        raise FailureStoreValidationError(
            f"failure store must be a JSON object, got {type(raw).__name__}"
        )
    data = validate_failure_store(raw)
    return store_from_dict(data)


def write_failure_store(
    store: T.FailureStore | Mapping[str, Any],
    path: Path | str,
) -> Path:
    """Validate and write a failure store JSON file."""
    data = validate_failure_store(store)
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False)
    output.write_text(text + "\n", encoding="utf-8")
    return output


# --- Save: preserve failures from a run-record -------------------------------


def _verifier_version(run_record: Mapping[str, Any]) -> str:
    """Build the verifier version string (``<name>@<version>``) from a run-record."""
    verifier = run_record.get("verifier", {})
    name = verifier.get("name", "unknown")
    version = verifier.get("version")
    if version:
        return f"{name}@{version}"
    return f"{name}@unknown"


def _load_case_inputs(
    benchmark_dir: Path | str | None,
    benchmark_id: str,
) -> dict[str, Any]:
    """Load case ``input`` fields keyed by case id from a benchmark directory.

    Returns an empty dict when ``benchmark_dir`` is not provided, in which case
    ``save_failures`` falls back to run-record-derived task input.
    """
    if benchmark_dir is None:
        return {}
    try:
        manifest = L.load_benchmark(benchmark_dir)
    except (L.LoadError, L.ValidationError) as exc:
        raise FailureStoreError(
            f"could not load benchmark for task-input preservation: {exc}"
        ) from exc
    if manifest.id != benchmark_id:
        raise FailureStoreError(
            f"benchmark id mismatch: run-record references {benchmark_id!r} "
            f"but --benchmark points at {manifest.id!r}"
        )
    rows = L.load_cases(manifest)
    inputs: dict[str, Any] = {}
    for _, row in rows:
        cid = row.get("id")
        if cid is not None:
            inputs[str(cid)] = L.canonicalize(row.get("input"))
    return inputs


def _task_input_for_case(
    case: Mapping[str, Any],
    run_record: Mapping[str, Any],
    case_inputs: Mapping[str, Any],
) -> Any:
    """Resolve the task input to preserve for a failed case.

    Prefers the on-disk case ``input`` loaded via ``--benchmark``.  Falls back
    to the run-record's rendered prompt (single-prompt runs), then to a
    structured descriptor so the schema-required ``task_input`` is always
    populated and reproducible.
    """
    case_id = case.get("case_id")
    if case_id in case_inputs:
        return case_inputs[case_id]
    prompt = run_record.get("prompt", {})
    rendered = prompt.get("rendered")
    if isinstance(rendered, str) and rendered:
        return rendered
    return {
        "case_id": case_id,
        "benchmark_id": run_record.get("benchmark", {}).get("id"),
        "note": "task_input unavailable without --benchmark; preserve via ai-bench failures save --benchmark <dir>",
    }


def _model_output_for_case(case: Mapping[str, Any]) -> Any:
    """Extract the model output (observed text or transcript) from a case result."""
    if "transcript" in case and case["transcript"] is not None:
        return L.canonicalize(case["transcript"])
    if "observed" in case and case["observed"] is not None:
        return case["observed"]
    return ""


def _build_failure_record(
    case: Mapping[str, Any],
    run_record: Mapping[str, Any],
    run_record_path: Path | str | None,
    case_inputs: Mapping[str, Any],
) -> T.FailureRecord:
    """Build a ``FailureRecord`` from a failed case result and its run-record."""
    benchmark = run_record["benchmark"]
    verifier_version = _verifier_version(run_record)
    run_id = run_record["run_id"]
    ref_path = str(run_record_path) if run_record_path is not None else None

    expected = case.get("expected")
    expected_metadata: Mapping[str, Any] | None = None
    if expected is None:
        expected_metadata = {
            "reason": "preserved_failure_case",
            "source_run_record": run_id,
        }

    verdict = T.FailureVerifierVerdict(
        verdict="fail",  # type: ignore[arg-type]
        score=case.get("score"),
        reason=case.get("error"),
    )

    record = T.FailureRecord(
        benchmark_id=benchmark["id"],
        case_id=case["case_id"],
        manifest_version=run_record["manifest_version"],
        fixture_version=run_record["fixture_version"],
        prompt_version=run_record["prompt"]["version"],
        model_id=run_record["model"]["id"],
        sampling_params=dict(run_record.get("sampling_params", {})),
        seed=run_record.get("seed"),
        verifier_version=verifier_version,
        metric_params=dict(run_record.get("metric_params", {})),
        environment_hash=run_record["environment_hash"],
        task_input=_task_input_for_case(case, run_record, case_inputs),
        model_output=_model_output_for_case(case),
        verifier_verdict=verdict,
        run_record_ref=T.RunRecordRef(run_id=run_id, path=ref_path),
        expected=expected,
        expected_metadata=expected_metadata,
        preserved_at=RR.utc_now(),
    )
    # Stamp the computed dedup key onto the record.
    record_dict = failure_record_to_dict(record)
    key = dedup_key(record_dict)
    return T.FailureRecord(
        benchmark_id=record.benchmark_id,
        case_id=record.case_id,
        manifest_version=record.manifest_version,
        fixture_version=record.fixture_version,
        prompt_version=record.prompt_version,
        model_id=record.model_id,
        sampling_params=record.sampling_params,
        seed=record.seed,
        verifier_version=record.verifier_version,
        metric_params=record.metric_params,
        environment_hash=record.environment_hash,
        task_input=record.task_input,
        model_output=record.model_output,
        verifier_verdict=record.verifier_verdict,
        run_record_ref=record.run_record_ref,
        expected=record.expected,
        expected_metadata=record.expected_metadata,
        preserved_at=record.preserved_at,
        dedup_key=key,
    )


def save_failures(
    run_record_path: Path | str,
    store_path: Path | str,
    *,
    benchmark_dir: Path | str | None = None,
) -> T.FailureStore:
    """Preserve failed cases from a run-record into a versioned failure store.

    Loads the run-record at ``run_record_path`` (produced by ``ai-bench run``),
    extracts cases with ``verdict == "fail"``, builds failure records carrying
    the full reproducibility determinant set, deduplicates against any existing
    store at ``store_path``, and writes a schema-valid failure store.

    When ``benchmark_dir`` is provided, per-case ``task_input`` is loaded from
    the on-disk benchmark cases for full reproducibility.  When omitted, the
    task input falls back to the run-record's rendered prompt (single-prompt
    runs) or a structured descriptor.

    Returns the written ``FailureStore``.
    """
    run_record_path = Path(run_record_path)
    if not run_record_path.is_file():
        raise FailureStoreError(f"run-record not found: {run_record_path}")
    try:
        run_record = L.load_json(run_record_path)
    except L.LoadError as exc:
        raise FailureStoreError(str(exc)) from exc
    if not isinstance(run_record, dict):
        raise FailureStoreError(
            f"run-record must be a JSON object, got {type(run_record).__name__}"
        )

    benchmark_id = run_record.get("benchmark", {}).get("id", "")
    case_inputs = _load_case_inputs(benchmark_dir, benchmark_id)

    # Load existing store (if any) and index by dedup key.
    store_path = Path(store_path)
    existing: dict[str, T.FailureRecord] = {}
    existing_store: T.FailureStore | None = None
    if store_path.is_file():
        existing_store = load_failure_store(store_path)
        for rec in existing_store.failures:
            key = rec.dedup_key or dedup_key(failure_record_to_dict(rec))
            existing[key] = rec

    new_records: list[T.FailureRecord] = []
    for case in run_record.get("cases", []):
        if case.get("verdict") != "fail":
            continue
        record = _build_failure_record(case, run_record, run_record_path, case_inputs)
        key = record.dedup_key or dedup_key(failure_record_to_dict(record))
        if key in existing:
            # Same determinant set already preserved; keep the existing record
            # (do not overwrite provenance/timestamps).
            continue
        existing[key] = record
        new_records.append(record)

    all_failures = list(existing.values())
    # Stable ordering: by dedup key so store output is deterministic.
    all_failures.sort(
        key=lambda r: r.dedup_key or dedup_key(failure_record_to_dict(r))
    )

    now = RR.utc_now()
    created_at = existing_store.created_at if existing_store is not None else now
    benchmark_scope = existing_store.benchmark_id if existing_store is not None else None
    # If all failures share one benchmark id, scope the store to it.
    if benchmark_scope is None and all_failures:
        ids = {r.benchmark_id for r in all_failures}
        if len(ids) == 1:
            benchmark_scope = ids.pop()

    store = T.FailureStore(
        schema_version=T.SCHEMA_VERSION,  # type: ignore[arg-type]
        storage_version=STORAGE_VERSION,
        failures=tuple(all_failures),
        benchmark_id=benchmark_scope,
        created_at=created_at,
        updated_at=now,
    )
    write_failure_store(store, store_path)
    return store


# --- Retry: replay stored failures ------------------------------------------


@dataclass(frozen=True)
class RetryOutcome:
    """Result of replaying a single stored failure.

    ``classification`` is one of ``improved`` (was fail, now pass), ``regressed``
    (was fail, now fail with a strictly lower score), or ``unchanged`` (was fail,
    now fail with an equal or higher score, or no score comparable).
    """

    case_id: str
    benchmark_id: str
    classification: str
    stored_verdict: str
    new_verdict: str
    stored_score: float | None
    new_score: float | None
    run_record_path: Path | None
    reason: str | None = None


def retry_failures(
    store_path: Path | str,
    benchmark_dir: Path | str,
    *,
    output: Path | str | None = None,
    model: str = "stub",
    seed: str | int | None = 0,
    predictions: Path | str | None = None,
    predictions_file: Path | str | None = None,
    replay: Path | str | None = None,
    now: Any = RR.utc_now,
) -> list[RetryOutcome]:
    """Replay stored failures through the public runner and classify results.

    Loads the failure store at ``store_path``, re-runs the benchmark at
    ``benchmark_dir`` via ``runner.run_benchmark`` with the requested adapter
    mode, and compares each stored failure's verdict to the new verdict.
    Classification is based on verifier verdicts, not string guesses:

      * ``improved``  — stored ``fail``, new ``pass``.
      * ``regressed`` — stored ``fail``, new ``fail`` with a strictly lower
        score than the stored score (when both scores are comparable).
      * ``unchanged`` — stored ``fail``, new ``fail`` with an equal or higher
        score, or scores not comparable.

    Returns one ``RetryOutcome`` per stored failure, in store order.
    """
    store = load_failure_store(store_path)
    if not store.failures:
        return []

    # Re-run the benchmark through the public runner to produce a fresh
    # schema-valid run-record with real verifier verdicts.
    try:
        result = R.run_benchmark(
            benchmark_dir,
            model=model,
            seed=seed,
            output=output,
            predictions=predictions,
            predictions_file=predictions_file,
            replay=replay,
            now=now,
        )
    except R.RunnerError as exc:
        raise FailureStoreError(f"retry run failed: {exc}") from exc

    new_by_case: dict[str, Mapping[str, Any]] = {
        case["case_id"]: case for case in result.record.get("cases", [])
    }

    outcomes: list[RetryOutcome] = []
    for rec in store.failures:
        new_case = new_by_case.get(rec.case_id)
        if new_case is None:
            outcomes.append(
                RetryOutcome(
                    case_id=rec.case_id,
                    benchmark_id=rec.benchmark_id,
                    classification="unchanged",
                    stored_verdict="fail",
                    new_verdict="fail",
                    stored_score=rec.verifier_verdict.score,
                    new_score=None,
                    run_record_path=result.path,
                    reason="case not present in retry run",
                )
            )
            continue

        new_verdict = new_case.get("verdict", "fail")
        new_score = new_case.get("score")
        stored_score = rec.verifier_verdict.score

        if new_verdict == "pass":
            classification = "improved"
        elif (
            stored_score is not None
            and new_score is not None
            and new_score < stored_score
        ):
            classification = "regressed"
        else:
            classification = "unchanged"

        outcomes.append(
            RetryOutcome(
                case_id=rec.case_id,
                benchmark_id=rec.benchmark_id,
                classification=classification,
                stored_verdict="fail",
                new_verdict=new_verdict,
                stored_score=stored_score,
                new_score=new_score,
                run_record_path=result.path,
                reason=new_case.get("error"),
            )
        )
    return outcomes


# --- Hard-set export ---------------------------------------------------------


def _hard_set_benchmark_id(source_benchmark_id: str) -> str:
    """Derive a valid benchmark id for the exported hard-set subset."""
    # Keep the case-id pattern: lowercase alphanumerics, hyphens, underscores.
    raw = source_benchmark_id.lower()
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in raw)
    safe = safe.strip("-_")
    if not safe:
        safe = "hardset"
    return f"{safe}-hardset"


def export_hard_set(
    store_path: Path | str,
    output_dir: Path | str,
    *,
    benchmark_dir: Path | str | None = None,
) -> Path:
    """Turn curated failures into a runnable benchmark subset.

    Writes a new benchmark directory under ``output_dir`` containing a
    ``benchmark.yaml`` manifest and ``cases/<case-id>.yaml`` case files derived
    from the preserved failure records.  Each exported case preserves the
    original task input and expected value, and carries ``expected_metadata``
    / ``provenance`` linking it back to the source run-record so the hard set
    remains traceable to its origin failure cases.

    When ``benchmark_dir`` is provided, the exported manifest inherits the
    source benchmark's metric, task type, prompt template, and sampling config
    so the subset is directly runnable via ``ai-bench run``.  When omitted, a
    minimal manifest is synthesized from the failure records' determinant
    fields.

    Returns the exported benchmark directory path.
    """
    store = load_failure_store(store_path)
    if not store.failures:
        raise FailureStoreError("cannot export an empty failure store")

    source_manifest: Mapping[str, Any] | None = None
    if benchmark_dir is not None:
        try:
            manifest_handle = L.load_benchmark(benchmark_dir)
        except (L.LoadError, L.ValidationError) as exc:
            raise FailureStoreError(
                f"could not load source benchmark for export: {exc}"
            ) from exc
        source_manifest = manifest_handle.data

    output_dir = Path(output_dir)
    cases_dir = output_dir / "cases"
    cases_dir.mkdir(parents=True, exist_ok=True)

    # Group failures by benchmark id; a hard set is scoped to one benchmark.
    benchmark_ids = {rec.benchmark_id for rec in store.failures}
    if len(benchmark_ids) > 1:
        raise FailureStoreError(
            f"hard-set export requires a single benchmark; store contains: "
            f"{sorted(benchmark_ids)}"
        )
    source_benchmark_id = store.failures[0].benchmark_id
    new_benchmark_id = _hard_set_benchmark_id(source_benchmark_id)

    # Build the manifest.
    if source_manifest is not None:
        manifest = _manifest_from_source(source_manifest, new_benchmark_id, store)
    else:
        manifest = _manifest_from_failures(store, new_benchmark_id)

    manifest_path = output_dir / "benchmark.yaml"
    manifest_path.write_text(
        yaml.safe_dump(_clean_for_yaml(manifest), sort_keys=False),
        encoding="utf-8",
    )

    # Write case files.
    for rec in store.failures:
        case_doc = _case_from_failure(rec)
        case_path = cases_dir / f"{rec.case_id}.yaml"
        case_path.write_text(
            yaml.safe_dump(_clean_for_yaml(case_doc), sort_keys=False),
            encoding="utf-8",
        )

    return output_dir


def _manifest_from_source(
    source: Mapping[str, Any],
    new_id: str,
    store: T.FailureStore,
) -> dict[str, Any]:
    """Build an exported manifest inheriting the source benchmark's config."""
    out = dict(source)
    out["id"] = new_id
    out["name"] = f"{source.get('name', source.get('id', 'benchmark'))} (hard set)"
    out["description"] = (
        f"Hard-set export of preserved failure cases from benchmark "
        f"{store.failures[0].benchmark_id!r}. Curated from failure store; "
        f"provenance preserved per case via expected_metadata/provenance."
    )
    out["version"] = source.get("version", "0.1.0")
    out["case_glob"] = "cases/*.yaml"
    out["status"] = "experimental"
    # Drop contributor contact details that may not apply to the export.
    if "contributor" in out and isinstance(out["contributor"], Mapping):
        out["contributor"] = {
            "name": "ai-bench hard-set export",
            "contact": "https://example.org/ai-bench",
        }
    return out


def _manifest_from_failures(store: T.FailureStore, new_id: str) -> dict[str, Any]:
    """Synthesize a minimal manifest from failure-record determinant fields."""
    first = store.failures[0]
    return {
        "schema_version": T.SCHEMA_VERSION,
        "id": new_id,
        "name": f"{first.benchmark_id} (hard set)",
        "description": (
            f"Hard-set export of preserved failure cases from benchmark "
            f"{first.benchmark_id!r}. Synthesized from failure-store determinant "
            f"fields; provide --benchmark for full metric/prompt inheritance."
        ),
        "domain": "hard-set",
        "task_type": "text",
        "metric": {
            "verifier": _verifier_name_from_version(first.verifier_version),
            "params": dict(first.metric_params),
        },
        "version": first.manifest_version,
        "contributor": {
            "name": "ai-bench hard-set export",
            "contact": "https://example.org/ai-bench",
        },
        "license": "See source benchmark",
        "case_glob": "cases/*.yaml",
        "status": "experimental",
        "sampling": dict(first.sampling_params),
    }


def _verifier_name_from_version(verifier_version: str) -> str:
    """Extract the verifier name from a ``<name>@<version>`` string."""
    if "@" in verifier_version:
        return verifier_version.split("@", 1)[0]
    return verifier_version


def _case_from_failure(rec: T.FailureRecord) -> dict[str, Any]:
    """Build an exported case document from a preserved failure record."""
    task_input = rec.task_input
    if isinstance(task_input, Mapping):
        input_field: Any = dict(task_input)
    else:
        input_field = task_input

    case: dict[str, Any] = {
        "schema_version": T.SCHEMA_VERSION,
        "id": rec.case_id,
        "input": input_field,
        "expected": rec.expected,
        "difficulty": "hard",
        "provenance": {
            "source": "ai-bench-failure-store",
            "author": "ai-bench hard-set export",
            "license": "See source benchmark",
            "notes": (
                f"Preserved from run-record {rec.run_record_ref.run_id}; "
                f"dedup_key={rec.dedup_key}"
            ),
        },
    }
    if rec.expected is None:
        case["expected_metadata"] = rec.expected_metadata or {
            "reason": "preserved_failure_case",
            "source_run_record": rec.run_record_ref.run_id,
        }
    return case


def _clean_for_yaml(obj: Any) -> Any:
    """Return a YAML-safe, JSON-compatible copy of ``obj``."""
    return copy.deepcopy(L.canonicalize(obj))
