"""Run-record construction, serialization, and validation (chunk C05).

The JSON shape is frozen by ``schemas/run-record.schema.json`` from C02.  This
module converts the runtime dataclasses from ``ai_bench.types`` into that JSON
shape, validates records before writing, and preserves the tool-action
transcript/final-repo-state fields that later chunks consume.
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import jsonschema

from ai_bench import __version__
from ai_bench import types as T
from ai_bench.loader import canonical_json, canonicalize, load_schema

__all__ = [
    "RunRecordError",
    "RunRecordValidationError",
    "RUN_RECORD_SCHEMA_NAME",
    "utc_now",
    "default_environment",
    "environment_hash",
    "build_run_id",
    "record_to_dict",
    "validate_run_record",
    "write_run_record",
    "tool_action_from_mapping",
    "repo_state_from_mapping",
]

RUN_RECORD_SCHEMA_NAME = "run-record.schema.json"


class RunRecordError(Exception):
    """Base error for run-record serialization and I/O failures."""


class RunRecordValidationError(RunRecordError):
    """Raised when a run-record does not conform to the C02 schema."""

    def __init__(self, message: str, *, errors: Sequence[str] = ()) -> None:
        super().__init__(message)
        self.errors = tuple(errors)


@dataclass(frozen=True)
class _SchemaPieces:
    schema: Mapping[str, Any]
    validator: jsonschema.Draft202012Validator


_schema_pieces: _SchemaPieces | None = None


def _schema() -> _SchemaPieces:
    global _schema_pieces
    if _schema_pieces is None:
        schema = load_schema(RUN_RECORD_SCHEMA_NAME)
        validator = jsonschema.Draft202012Validator(
            schema,
            format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER,
        )
        _schema_pieces = _SchemaPieces(schema=schema, validator=validator)
    return _schema_pieces


def utc_now() -> str:
    """Return an RFC3339/JSON-Schema date-time string in UTC."""

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def default_environment(*, sandbox_backend: str | None) -> T.RunEnvironment:
    """Build deterministic environment metadata for a run-record.

    The environment intentionally excludes volatile paths such as the output
    run-record location.  C07 may pass a concrete sandbox backend id here; C05
    uses ``None`` for text/file runs and explicit fake/replay labels for
    non-executing tool-task plumbing.
    """

    return T.RunEnvironment(
        sandbox_backend=sandbox_backend,
        python=f"{sys.version_info.major}.{sys.version_info.minor}",
        os=platform.system().lower() or None,
        runner_version=__version__,
    )


def environment_hash(environment: T.RunEnvironment | Mapping[str, Any]) -> str:
    """Return a deterministic hash of non-volatile environment details."""

    if isinstance(environment, T.RunEnvironment):
        payload = _environment_to_dict(environment)
    else:
        payload = {str(k): v for k, v in environment.items() if v is not None}
    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def build_run_id(payload: Mapping[str, Any], *, started_at: str) -> str:
    """Build a compact run id from volatile time plus deterministic payload."""

    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()[:12]
    safe_time = (
        started_at.replace("-", "")
        .replace(":", "")
        .replace(".", "")
        .replace("+", "")
    )
    return f"run-{safe_time}-{digest}"


def record_to_dict(record: T.RunRecord | Mapping[str, Any]) -> dict[str, Any]:
    """Convert a run-record dataclass or mapping into schema JSON."""

    if isinstance(record, Mapping):
        return dict(record)

    out: dict[str, Any] = {
        "schema_version": record.schema_version,
        "run_id": record.run_id,
        "benchmark": _benchmark_to_dict(record.benchmark),
        "model": _model_to_dict(record.model),
        "prompt": _prompt_to_dict(record.prompt),
        "sampling_params": dict(record.sampling_params),
        "seed": record.seed,
        "fixture_version": record.fixture_version,
        "manifest_version": record.manifest_version,
        "environment_hash": record.environment_hash,
        "metric_params": dict(record.metric_params),
        "verifier": _verifier_to_dict(record.verifier),
        "tag_filter": record.tag_filter,
        "cases": [_case_result_to_dict(c) for c in record.cases],
        "aggregate": _aggregate_to_dict(record.aggregate),
    }
    if record.environment is not None:
        out["environment"] = _environment_to_dict(record.environment)
    if record.started_at is not None:
        out["started_at"] = record.started_at
    if record.ended_at is not None:
        out["ended_at"] = record.ended_at
    return out


def validate_run_record(record: T.RunRecord | Mapping[str, Any]) -> dict[str, Any]:
    """Validate a run-record against ``schemas/run-record.schema.json``.

    Returns the JSON dict on success so callers can write exactly what was
    validated.  On failure, raises ``RunRecordValidationError`` with compact,
    path-qualified errors.
    """

    data = record_to_dict(record)
    errors = sorted(_schema().validator.iter_errors(data), key=_error_sort_key)
    if errors:
        lines = [_format_error(e) for e in errors]
        raise RunRecordValidationError(
            f"run-record failed schema validation with {len(lines)} error(s)",
            errors=lines,
        )
    return data


def write_run_record(record: T.RunRecord | Mapping[str, Any], path: Path | str) -> Path:
    """Validate and write a run-record JSON file."""

    data = validate_run_record(record)
    output = Path(path)
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except (OSError, TypeError) as exc:
        raise RunRecordError(f"could not write run-record {output}: {exc}") from exc
    return output


def tool_action_from_mapping(data: Mapping[str, Any]) -> T.ToolAction:
    """Materialize one C02 transcript row from replay JSON."""

    required = (
        "command",
        "argv",
        "cwd",
        "env_overrides",
        "stdin",
        "stdout",
        "stderr",
        "exit_code",
        "wall_clock_ms",
        "timeout",
        "sandbox_boundary_violation",
    )
    missing = [name for name in required if name not in data]
    if missing:
        raise RunRecordValidationError(
            f"tool action missing required field(s): {', '.join(missing)}"
        )
    command = data["command"]
    argv = data["argv"]
    cwd = data["cwd"]
    env = data["env_overrides"]
    stdin = data["stdin"]
    stdout = data["stdout"]
    stderr = data["stderr"]
    exit_code = data["exit_code"]
    wall_clock_ms = data["wall_clock_ms"]
    timeout = data["timeout"]
    violation = data["sandbox_boundary_violation"]
    violation_reason = data.get("violation_reason")

    if not isinstance(command, str) or not command:
        raise RunRecordValidationError("tool action command must be a non-empty string")
    if not isinstance(argv, list) or any(not isinstance(a, str) for a in argv):
        raise RunRecordValidationError(f"tool action {command!r} argv must be a string array")
    if not isinstance(cwd, str):
        raise RunRecordValidationError(f"tool action {command!r} cwd must be a string")
    if not isinstance(env, Mapping) or any(
        not isinstance(k, str) or not isinstance(v, str) for k, v in env.items()
    ):
        raise RunRecordValidationError(
            f"tool action {command!r} env_overrides must map strings to strings"
        )
    if stdin is not None and not isinstance(stdin, str):
        raise RunRecordValidationError(f"tool action {command!r} stdin must be string or null")
    if exit_code is not None and not isinstance(exit_code, int):
        raise RunRecordValidationError(f"tool action {command!r} exit_code must be integer or null")
    if not isinstance(wall_clock_ms, int) or wall_clock_ms < 0:
        raise RunRecordValidationError(
            f"tool action {command!r} wall_clock_ms must be a non-negative integer"
        )
    if not isinstance(timeout, bool):
        raise RunRecordValidationError(f"tool action {command!r} timeout must be a boolean")
    if not isinstance(violation, bool):
        raise RunRecordValidationError(
            f"tool action {command!r} sandbox_boundary_violation must be a boolean"
        )
    if violation_reason is not None and not isinstance(violation_reason, str):
        raise RunRecordValidationError(
            f"tool action {command!r} violation_reason must be string or null"
        )
    return T.ToolAction(
        command=command,
        argv=tuple(argv),
        cwd=cwd,
        env_overrides={str(k): str(v) for k, v in env.items()},
        stdin=stdin,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        wall_clock_ms=wall_clock_ms,
        timeout=timeout,
        sandbox_boundary_violation=violation,
        violation_reason=violation_reason,
    )


def repo_state_from_mapping(data: Mapping[str, Any]) -> T.RepoState:
    """Materialize a C02 final repo-state snapshot from replay JSON."""

    required = ("file_tree", "git_status", "branches", "commits", "diff")
    missing = [name for name in required if name not in data]
    if missing:
        raise RunRecordValidationError(
            f"repo state missing required field(s): {', '.join(missing)}"
        )
    file_tree = data["file_tree"]
    git_status = data["git_status"]
    branches = data["branches"]
    commits = data["commits"]
    diff = data["diff"]
    if not isinstance(file_tree, list) or any(not isinstance(p, str) for p in file_tree):
        raise RunRecordValidationError("repo state file_tree must be a string array")
    if not isinstance(git_status, str):
        raise RunRecordValidationError("repo state git_status must be a string")
    if not isinstance(branches, list) or any(not isinstance(b, str) for b in branches):
        raise RunRecordValidationError("repo state branches must be a string array")
    if not isinstance(commits, list):
        raise RunRecordValidationError("repo state commits must be an array")
    normalized_commits: list[dict[str, str]] = []
    for item in commits:
        if not isinstance(item, Mapping):
            raise RunRecordValidationError("repo state commits entries must be mappings")
        sha = item.get("sha")
        subject = item.get("subject")
        if not isinstance(sha, str) or not isinstance(subject, str):
            raise RunRecordValidationError("repo state commits entries require string sha and subject")
        normalized_commits.append({"sha": sha, "subject": subject})
    if not isinstance(diff, str):
        raise RunRecordValidationError("repo state diff must be a string")
    current_branch = data.get("current_branch")
    if current_branch is not None and not isinstance(current_branch, str):
        raise RunRecordValidationError("repo state current_branch must be a string or null")
    tags = data["tags"] if "tags" in data else ()
    if not isinstance(tags, (list, tuple)) or any(not isinstance(t, str) for t in tags):
        raise RunRecordValidationError("repo state tags must be a string array")
    return T.RepoState(
        file_tree=tuple(file_tree),
        git_status=git_status,
        branches=tuple(branches),
        commits=tuple(normalized_commits),
        diff=diff,
        current_branch=current_branch,
        tags=tuple(tags),
    )


def _benchmark_to_dict(ref: T.BenchmarkRef) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": ref.id,
        "version": ref.version,
        "task_type": ref.task_type,
    }
    if ref.domain is not None:
        out["domain"] = ref.domain
    if ref.tags:
        out["tags"] = list(ref.tags)
    if ref.status is not None:
        out["status"] = ref.status
    return out


def _model_to_dict(ref: T.ModelRef) -> dict[str, Any]:
    out: dict[str, Any] = {"id": ref.id}
    if ref.provider is not None:
        out["provider"] = ref.provider
    if ref.adapter is not None:
        out["adapter"] = ref.adapter
    return out


def _prompt_to_dict(prompt: T.RunPrompt) -> dict[str, Any]:
    out: dict[str, Any] = {"version": prompt.version}
    if prompt.template is not None:
        out["template"] = prompt.template
    if prompt.path is not None:
        out["path"] = prompt.path
    if prompt.rendered is not None:
        out["rendered"] = prompt.rendered
    return out


def _environment_to_dict(environment: T.RunEnvironment) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if environment.sandbox_backend is not None:
        out["sandbox_backend"] = environment.sandbox_backend
    if environment.python is not None:
        out["python"] = environment.python
    if environment.os is not None:
        out["os"] = environment.os
    if environment.runner_version is not None:
        out["runner_version"] = environment.runner_version
    return out


def _judge_to_dict(config: T.RunJudgeConfig) -> dict[str, Any]:
    return {
        "judge_model": config.judge_model,
        "judge_prompt": config.judge_prompt,
        "judge_params": dict(config.judge_params),
        "judge_seed": config.judge_seed,
    }


def _verifier_to_dict(verifier: T.RunVerifier) -> dict[str, Any]:
    out: dict[str, Any] = {"name": verifier.name}
    if verifier.version is not None:
        out["version"] = verifier.version
    if verifier.judge_config is not None:
        out["judge_config"] = _judge_to_dict(verifier.judge_config)
    return out


def _tool_action_to_dict(action: T.ToolAction) -> dict[str, Any]:
    out: dict[str, Any] = {
        "command": action.command,
        "argv": list(action.argv),
        "cwd": action.cwd,
        "env_overrides": dict(action.env_overrides),
        "stdin": action.stdin,
        "stdout": action.stdout,
        "stderr": action.stderr,
        "exit_code": action.exit_code,
        "wall_clock_ms": action.wall_clock_ms,
        "timeout": action.timeout,
        "sandbox_boundary_violation": action.sandbox_boundary_violation,
    }
    if action.violation_reason is not None:
        out["violation_reason"] = action.violation_reason
    return out


def _repo_state_to_dict(state: T.RepoState) -> dict[str, Any]:
    out: dict[str, Any] = {
        "file_tree": list(state.file_tree),
        "git_status": state.git_status,
        "branches": list(state.branches),
        "commits": [dict(c) for c in state.commits],
        "diff": state.diff,
    }
    if state.current_branch is not None:
        out["current_branch"] = state.current_branch
    if state.tags:
        out["tags"] = list(state.tags)
    return out


def _case_result_to_dict(result: T.CaseResult) -> dict[str, Any]:
    out: dict[str, Any] = {
        "case_id": result.case_id,
        "verdict": result.verdict,
        "score": result.score,
        "error": result.error,
    }
    if result.expected is not None:
        out["expected"] = canonicalize(result.expected)
    if result.observed is not None:
        out["observed"] = canonicalize(result.observed)
    if result.provenance is not None:
        out["provenance"] = canonicalize(dict(result.provenance))
    if result.transcript:
        out["transcript"] = [_tool_action_to_dict(a) for a in result.transcript]
    if result.final_repo_state is not None:
        out["final_repo_state"] = _repo_state_to_dict(result.final_repo_state)
        out.setdefault("transcript", [])
    return out


def _aggregate_to_dict(aggregate: T.AggregateScore) -> dict[str, Any]:
    out: dict[str, Any] = {
        "metric": aggregate.metric,
        "value": aggregate.value,
        "n_cases": aggregate.n_cases,
    }
    if aggregate.n_pass is not None:
        out["n_pass"] = aggregate.n_pass
    if aggregate.n_fail is not None:
        out["n_fail"] = aggregate.n_fail
    if aggregate.details:
        out["details"] = canonicalize(dict(aggregate.details))
    return out


def _error_sort_key(error: jsonschema.ValidationError) -> tuple[str, str]:
    path = ".".join(str(p) for p in error.absolute_path)
    return (path, error.message)


def _format_error(error: jsonschema.ValidationError) -> str:
    path = ".".join(str(p) for p in error.absolute_path) or "<root>"
    return f"{path}: {error.message}"
