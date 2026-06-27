"""Typed/data contracts for ai-bench, frozen by chunk C02.

This module defines the v1 in-memory shapes for benchmark manifests, cases,
run-records, and the failure store. The shapes are deliberately aligned with
the JSON Schemas in ``schemas/`` and are asserted against schema fixtures in
``tests/test_schema.py`` so JSON Schema and runtime types cannot silently
drift.

C02 owns this file and the schemas. Downstream v1 chunks (C03-C12) consume
these contracts as-is; they must not add new ``schemas/*.schema.json`` files
or extend these schemas in-flight. Post-v1 schema evolution is owned by C13
via a versioned migration plan with compatibility tests, not by edits here.

The contracts here are dataclasses plus small enum/typing helpers. They do
NOT implement loader, validator, scoring, runner, sandbox, or failure-store
command behavior -- those land in later chunks. Only the shared contract
surface needed to keep schema and runtime types in sync is defined here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, Sequence

__all__ = [
    "SCHEMA_VERSION",
    "SchemaVersion",
    "TaskType",
    "BenchmarkStatus",
    "VerifierName",
    "CaseDifficulty",
    "ModelAdapter",
    "Verdict",
    "BenchmarkManifest",
    "Contributor",
    "MetricConfig",
    "PromptTemplate",
    "CaseDefinition",
    "CaseInput",
    "Provenance",
    "CaseVerifierOverride",
    "StateCheckSpec",
    "LLMJudgeConfig",
    "ToolAction",
    "RepoState",
    "CaseResult",
    "AggregateScore",
    "RunRecord",
    "BenchmarkRef",
    "ModelRef",
    "RunPrompt",
    "RunEnvironment",
    "RunVerifier",
    "FailureRecord",
    "FailureStore",
    "RunRecordRef",
    "FailureVerifierVerdict",
    "VERIFIER_NAMES",
    "TASK_TYPES",
    "BENCHMARK_STATUSES",
    "CASE_DIFFICULTIES",
    "MODEL_ADAPTERS",
    "VERDICTS",
]

# v1 schema version. All v1 schemas pin this constant. Bumping it is owned by
# C13's versioned migration plan, not by in-flight edits.
SCHEMA_VERSION: str = "1"

SchemaVersion = Literal["1"]

# Enumerations mirrored from the JSON Schemas. Kept as Literal aliases so the
# typed contracts and the schemas share the same vocabulary.
TaskType = Literal["text", "tool-task"]
BenchmarkStatus = Literal["experimental", "stable"]
VerifierName = Literal[
    "exact_match",
    "contains_any",
    "regex_match",
    "set_f1",
    "state_check",
    "llm_judge",
]
CaseDifficulty = Literal["trivial", "easy", "medium", "hard", "expert"]
ModelAdapter = Literal["text", "agent", "stub", "file", "replay"]
Verdict = Literal["pass", "fail"]

VERIFIER_NAMES: frozenset[str] = frozenset(
    {
        "exact_match",
        "contains_any",
        "regex_match",
        "set_f1",
        "state_check",
        "llm_judge",
    }
)
TASK_TYPES: frozenset[str] = frozenset({"text", "tool-task"})
BENCHMARK_STATUSES: frozenset[str] = frozenset({"experimental", "stable"})
CASE_DIFFICULTIES: frozenset[str] = frozenset(
    {"trivial", "easy", "medium", "hard", "expert"}
)
MODEL_ADAPTERS: frozenset[str] = frozenset({"text", "agent", "stub", "file", "replay"})
VERDICTS: frozenset[str] = frozenset({"pass", "fail"})

# Reserved case-level tag selecting a benchmark's smoke subset via --tag smoke.
SMOKE_TAG: str = "smoke"


# --- Benchmark manifest -----------------------------------------------------


@dataclass(frozen=True)
class Contributor:
    """Authorship/provenance metadata for a benchmark."""

    name: str
    contact: str | None = None
    url: str | None = None


@dataclass(frozen=True)
class MetricConfig:
    """Verifier/scorer configuration at the benchmark level."""

    verifier: VerifierName
    params: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PromptTemplate:
    """Optional pinned prompt template for reproducibility."""

    version: str
    template: str | None = None
    path: str | None = None


@dataclass(frozen=True)
class BenchmarkManifest:
    """In-memory shape of ``schemas/benchmark.schema.json``.

    ``status`` defaults to ``experimental`` and ``tags`` defaults to an empty
    tuple, matching the schema defaults. The loader (C03) is responsible for
    applying defaults when materializing from YAML; this dataclass records the
    canonical post-default shape.
    """

    schema_version: SchemaVersion
    id: str
    name: str
    description: str
    domain: str
    task_type: TaskType
    metric: MetricConfig
    version: str
    contributor: Contributor
    license: str
    case_glob: str
    tags: Sequence[str] = ()
    status: BenchmarkStatus = "experimental"
    prompt_template: PromptTemplate | None = None
    sampling: Mapping[str, Any] = field(default_factory=dict)


# --- Case definition --------------------------------------------------------


@dataclass(frozen=True)
class CaseInput:
    """Task input for a case.

    ``prompt`` is the text prompt; ``fixture`` is an optional fixture
    descriptor for tool-task benchmarks.
    """

    prompt: str | None = None
    fixture: str | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Provenance:
    """Origin/licensing metadata for a case."""

    source: str | None = None
    author: str | None = None
    license: str | None = None
    url: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class CaseVerifierOverride:
    """Per-case verifier override."""

    verifier: VerifierName
    params: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StateCheckSpec:
    """Expected repository state for the state_check verifier.

    Consumed by the state-check verifier implementation in C07.2; the shape is
    frozen here so C08 fixtures can target it without further schema changes.
    """

    files: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    git: Mapping[str, Any] = field(default_factory=dict)
    absent: Sequence[str] = ()


@dataclass(frozen=True)
class LLMJudgeConfig:
    """Pinned LLM-judge configuration. Required when verifier is llm_judge."""

    judge_model: str
    judge_prompt: str
    judge_seed: str | int
    judge_params: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CaseDefinition:
    """In-memory shape of ``schemas/case.schema.json``.

    ``expected`` is permitted to be ``None`` only for preserved failure cases,
    which must carry ``expected_metadata`` with a ``reason``. ``tags`` defaults
    to an empty tuple; the reserved ``smoke`` tag selects the smoke subset.
    """

    schema_version: SchemaVersion
    id: str
    input: str | CaseInput
    expected: Any = None
    expected_metadata: Mapping[str, Any] | None = None
    tags: Sequence[str] = ()
    difficulty: CaseDifficulty = "medium"
    provenance: Provenance | None = None
    verifier: CaseVerifierOverride | None = None
    state_check: StateCheckSpec | None = None
    llm_judge: LLMJudgeConfig | None = None
    notes: str | None = None


# --- Run record -------------------------------------------------------------


@dataclass(frozen=True)
class BenchmarkRef:
    """Benchmark identity captured at run time."""

    id: str
    version: str
    task_type: TaskType | None = None
    domain: str | None = None
    tags: Sequence[str] = ()
    status: BenchmarkStatus | None = None


@dataclass(frozen=True)
class ModelRef:
    """Model/adapter identity. For file predictions, id records the source."""

    id: str
    provider: str | None = None
    adapter: ModelAdapter | None = None


@dataclass(frozen=True)
class RunPrompt:
    """Pinned prompt used for a run."""

    version: str
    template: str | None = None
    path: str | None = None
    rendered: str | None = None


@dataclass(frozen=True)
class RunEnvironment:
    """Structured environment details backing ``environment_hash``."""

    sandbox_backend: str | None = None
    python: str | None = None
    os: str | None = None
    runner_version: str | None = None


@dataclass(frozen=True)
class RunVerifier:
    """Verifier configuration in effect for a run."""

    name: VerifierName | None = None
    version: str | None = None


@dataclass(frozen=True)
class ToolAction:
    """A single tool action in the run-record transcript.

    Fields are frozen by the C02 run-record schema. C05 implements against
    this shape; C07 must not extend it.
    """

    command: str
    argv: Sequence[str]
    cwd: str
    exit_code: int | None
    wall_clock_ms: int
    timeout: bool = False
    sandbox_boundary_violation: bool = False
    env_overrides: Mapping[str, str] = field(default_factory=dict)
    stdin: str | None = None
    stdout: str = ""
    stderr: str = ""
    violation_reason: str | None = None


@dataclass(frozen=True)
class RepoState:
    """Final repository state snapshot passed to the state-check verifier.

    Frozen by the C02 run-record schema; C05/C07 consume it as-is.
    """

    file_tree: Sequence[str] = ()
    git_status: str | None = None
    branches: Sequence[str] = ()
    commits: Sequence[Mapping[str, str]] = ()
    diff: str | None = None


@dataclass(frozen=True)
class CaseResult:
    """Per-case result in a run-record."""

    case_id: str
    verdict: Verdict
    score: float
    expected: Any = None
    observed: Any = None
    provenance: Mapping[str, Any] | None = None
    error: str | None = None
    transcript: Sequence[ToolAction] = ()
    final_repo_state: RepoState | None = None


@dataclass(frozen=True)
class AggregateScore:
    """Aggregate score over the selected cases."""

    metric: str
    value: float
    n_cases: int
    n_pass: int | None = None
    n_fail: int | None = None
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RunRecord:
    """In-memory shape of ``schemas/run-record.schema.json``.

    Volatile fields (``run_id``, ``started_at``, ``ended_at``) are documented
    as such and are NOT part of the reproducibility determinant set. The
    determinant set is: benchmark id + manifest/fixture version + prompt
    version + model id + sampling params + seed + metric params +
    environment hash (mirrored by the failure-store schema).
    """

    schema_version: SchemaVersion
    run_id: str
    benchmark: BenchmarkRef
    model: ModelRef
    prompt: RunPrompt
    sampling_params: Mapping[str, Any]
    seed: str | int | None
    fixture_version: str
    manifest_version: str
    environment_hash: str
    metric_params: Mapping[str, Any]
    cases: Sequence[CaseResult]
    aggregate: AggregateScore
    environment: RunEnvironment | None = None
    verifier: RunVerifier | None = None
    tag_filter: str | None = None
    started_at: str | None = None
    ended_at: str | None = None


# --- Failure store ----------------------------------------------------------


@dataclass(frozen=True)
class RunRecordRef:
    """Reference to the run-record a failure was preserved from."""

    run_id: str
    path: str | None = None


@dataclass(frozen=True)
class FailureVerifierVerdict:
    """The verifier verdict recorded for a preserved failure."""

    verdict: Literal["fail"]
    score: float | None = None
    reason: str | None = None


@dataclass(frozen=True)
class FailureRecord:
    """A preserved failure case with the full reproducibility determinant set.

    Deduplication is keyed by the determinant set (benchmark/case id,
    manifest/fixture version, prompt version, model id, sampling params, seed,
    verifier version, metric params, environment hash). Task/model/params/
    fixture-version alone is insufficient.
    """

    benchmark_id: str
    case_id: str
    manifest_version: str
    fixture_version: str
    prompt_version: str
    model_id: str
    sampling_params: Mapping[str, Any]
    seed: str | int | None
    verifier_version: str
    metric_params: Mapping[str, Any]
    environment_hash: str
    task_input: str | Mapping[str, Any]
    model_output: str | Mapping[str, Any] | Sequence[Any]
    verifier_verdict: FailureVerifierVerdict
    run_record_ref: RunRecordRef
    expected: Any = None
    expected_metadata: Mapping[str, Any] | None = None
    preserved_at: str | None = None
    dedup_key: str | None = None


@dataclass(frozen=True)
class FailureStore:
    """In-memory shape of ``schemas/failure-store.schema.json``."""

    schema_version: SchemaVersion
    storage_version: str
    failures: Sequence[FailureRecord] = ()
    benchmark_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
