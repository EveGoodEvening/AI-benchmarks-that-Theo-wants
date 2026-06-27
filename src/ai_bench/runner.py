"""Benchmark runner, offline prediction/replay paths, and run-record emission.

Chunk C05 wires together the C03 loader, C04 scoring engine, C05 model/agent
adapter contracts, and C02 run-record schema validation.  C07 plugs the
enforced sandboxed dispatcher (from ``ai_bench.sandbox``) into the C05
agent-adapter contract and hands the final repo-state snapshot to the real
state-check verifier implemented in C07.2.  The runner does not implement
real benchmarks or failure-store persistence.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from ai_bench import loader as L
from ai_bench import models as M
from ai_bench import run_records as RR
from ai_bench import sandbox as SB
from ai_bench import scoring as S
from ai_bench import types as T

__all__ = [
    "RunnerError",
    "RunResult",
    "C05StubStateCheckVerifier",
    "run_benchmark",
]


class RunnerError(Exception):
    """Raised for runner infrastructure failures (non-zero CLI exit)."""


@dataclass(frozen=True)
class RunResult:
    """Result returned by ``run_benchmark`` after a schema-valid write."""

    record: dict[str, Any]
    path: Path


class C05StubStateCheckVerifier:
    """Explicit fake state-check verifier for C05 replay/adapter plumbing.

    This is not the real repo-state verifier.  It only runs when verifier params
    opt in with ``c05_stub_state_check`` and returns the requested deterministic
    pass/fail verdict.  C07 owns the enforced sandbox and real state-check
    semantics.
    """

    def check(
        self,
        spec: T.StateCheckSpec,
        state: T.RepoState,
        params: Mapping[str, Any],
    ) -> S.VerifierResult:
        del spec
        raw = params.get("c05_stub_state_check")
        if raw is None:
            raise S.VerifierConfigurationError(
                "state_check has no C07 implementation registered; C05 only "
                "allows the explicit fake verifier when metric params include "
                "c05_stub_state_check"
            )
        if isinstance(raw, bool):
            passed = raw
        elif isinstance(raw, str) and raw in {"pass", "fail"}:
            passed = raw == "pass"
        else:
            raise S.VerifierConfigurationError(
                "c05_stub_state_check must be true/false or 'pass'/'fail'"
            )
        return S.VerifierResult(
            verdict="pass" if passed else "fail",
            score=1.0 if passed else 0.0,
            reason="C05 fake state-check verifier; real verifier is owned by C07",
            details={
                "c05_stub_state_check": raw,
                "file_tree_size": len(state.file_tree),
                "commit_count": len(state.commits),
            },
        )


def run_benchmark(
    benchmark_dir: Path | str,
    *,
    tag: str | None = None,
    model: str = "stub",
    seed: str | int | None = 0,
    output: Path | str | None = None,
    predictions: Path | str | None = None,
    predictions_file: Path | str | None = None,
    replay: Path | str | None = None,
    text_adapter: M.TextModelAdapter | None = None,
    agent_adapter: M.AgentAdapter | None = None,
    dispatcher: M.CommandDispatcher | None = None,
    state_check_verifier: S.StateCheckVerifier | None = None,
    now: Callable[[], str] = RR.utc_now,
) -> RunResult:
    """Run a benchmark and write a schema-valid run-record.

    Process-exit semantics are implemented by the CLI around this function:
    returning successfully means selected cases were loaded, evaluated, scored,
    and written to a schema-valid run-record.  Failed per-case verdicts remain
    data in the record and do not raise.  Load, adapter, replay, verifier, or
    run-record failures raise ``RunnerError`` and should map to non-zero exit.
    """

    mode_count = sum(p is not None for p in (predictions, predictions_file, replay))
    if mode_count > 1:
        raise RunnerError("choose only one of --predictions, --predictions-file, or --replay")

    manifest_handle = _load_manifest(benchmark_dir)
    selected_rows = _load_selected_cases(manifest_handle, tag)
    manifest = _manifest_from_mapping(manifest_handle.data)
    cases = [_case_from_mapping(row) for _, row in selected_rows]

    if manifest.task_type == "text":
        if replay is not None:
            raise RunnerError("--replay is only valid for tool-task benchmarks")
        record_cases, aggregate, model_ref, sandbox_backend, rendered_prompts = _run_text_cases(
            manifest_handle,
            manifest,
            cases,
            model=model,
            seed=seed,
            predictions=Path(predictions) if predictions is not None else None,
            predictions_file=Path(predictions_file) if predictions_file is not None else None,
            text_adapter=text_adapter,
        )
    elif manifest.task_type == "tool-task":
        if predictions is not None or predictions_file is not None:
            raise RunnerError("--predictions/--predictions-file are only valid for text benchmarks")
        record_cases, aggregate, model_ref, sandbox_backend, rendered_prompts = _run_tool_cases(
            manifest_handle,
            manifest,
            cases,
            model=model,
            seed=seed,
            replay=Path(replay) if replay is not None else None,
            agent_adapter=agent_adapter,
            dispatcher=dispatcher,
            state_check_verifier=state_check_verifier,
        )
    else:  # pragma: no cover - schema prevents this
        raise RunnerError(f"unsupported task_type {manifest.task_type!r}")

    if len(record_cases) != len(cases):
        raise RunnerError(
            f"internal runner error: evaluated {len(record_cases)} of {len(cases)} selected case(s)"
        )
    if aggregate.n_cases != len(cases):
        raise RunnerError(
            f"internal runner error: aggregate scored {aggregate.n_cases} of {len(cases)} selected case(s)"
        )

    started_at = now()
    ended_at = now()
    environment = RR.default_environment(sandbox_backend=sandbox_backend)
    env_hash = RR.environment_hash(environment)
    prompt = _run_prompt(manifest, rendered_prompts)
    metric_params = _metric_params(manifest, cases)
    run_id = RR.build_run_id(
        {
            "benchmark": manifest.id,
            "version": manifest.version,
            "task_type": manifest.task_type,
            "model": RR.record_to_dict(
                _minimal_record_for_model(model_ref, manifest, prompt, seed, env_hash, metric_params)
            )["model"],
            "sampling_params": dict(manifest.sampling),
            "seed": seed,
            "environment_hash": env_hash,
            "metric_params": metric_params,
            "tag_filter": tag,
            "case_ids": [c.id for c in cases],
        },
        started_at=started_at,
    )
    record = T.RunRecord(
        schema_version=T.SCHEMA_VERSION,  # type: ignore[arg-type]
        run_id=run_id,
        benchmark=T.BenchmarkRef(
            id=manifest.id,
            version=manifest.version,
            task_type=manifest.task_type,
            domain=manifest.domain,
            tags=tuple(manifest.tags),
            status=manifest.status,
        ),
        model=model_ref,
        prompt=prompt,
        sampling_params=dict(manifest.sampling),
        seed=seed,
        fixture_version=manifest.version,
        manifest_version=manifest.version,
        environment_hash=env_hash,
        environment=environment,
        metric_params=metric_params,
        verifier=_run_verifier(manifest),
        tag_filter=tag,
        cases=tuple(record_cases),
        aggregate=aggregate,
        started_at=started_at,
        ended_at=ended_at,
    )

    try:
        data = RR.validate_run_record(record)
        output_path = Path(output) if output is not None else Path("run-records") / f"{run_id}.json"
        written = RR.write_run_record(data, output_path)
    except RR.RunRecordError as exc:
        raise RunnerError(str(exc)) from exc
    return RunResult(record=data, path=written)


def _load_manifest(benchmark_dir: Path | str) -> L.Manifest:
    try:
        return L.load_benchmark(benchmark_dir)
    except (L.LoadError, L.ValidationError) as exc:
        raise RunnerError(str(exc)) from exc


def _load_selected_cases(manifest: L.Manifest, tag: str | None) -> list[tuple[Path, Mapping[str, Any]]]:
    try:
        rows = L.load_cases(manifest, tag=tag)
    except (L.LoadError, L.ValidationError) as exc:
        raise RunnerError(str(exc)) from exc
    if not rows:
        label = f" tagged {tag!r}" if tag is not None else ""
        raise RunnerError(f"no selected{label} cases for benchmark {manifest.id!r}")
    return rows


def _run_text_cases(
    manifest_handle: L.Manifest,
    manifest: T.BenchmarkManifest,
    cases: Sequence[T.CaseDefinition],
    *,
    model: str,
    seed: str | int | None,
    predictions: Path | None,
    predictions_file: Path | None,
    text_adapter: M.TextModelAdapter | None,
) -> tuple[list[T.CaseResult], T.AggregateScore, T.ModelRef, str | None, list[str]]:
    prompts = [_render_case_prompt(manifest, case, benchmark_dir=manifest_handle.dir) for case in cases]
    if predictions is not None:
        observed_by_id = _load_predictions_dir(predictions, cases)
        model_ref = T.ModelRef(id=f"file:{predictions}", adapter="file")
    elif predictions_file is not None:
        observed_by_id = _load_predictions_file(predictions_file, cases)
        model_ref = T.ModelRef(id=f"file:{predictions_file}", adapter="file")
    else:
        adapter = text_adapter
        if adapter is None:
            if model != "stub":
                raise RunnerError(
                    "C05 has no live provider adapters; use --model stub, --predictions, or --predictions-file"
                )
            adapter = M.StubTextModel()
        observed_by_id = {}
        for case, prompt in zip(cases, prompts, strict=True):
            try:
                observed_by_id[case.id] = adapter.generate(
                    prompt,
                    params=dict(manifest.sampling),
                    seed=seed,
                )
            except Exception as exc:  # adapter failures are infrastructure failures
                raise RunnerError(f"text adapter failed for case {case.id!r}: {exc}") from exc
        model_ref = T.ModelRef(
            id=adapter.model_id,
            provider=adapter.provider,
            adapter=adapter.adapter_kind,
        )

    verdicts, aggregate = _score_cases(cases, observed_by_id, manifest=manifest)
    case_results = [
        T.CaseResult(
            case_id=v.case_id,
            verdict=v.verdict,
            score=v.score,
            expected=v.expected,
            observed=str(observed_by_id[v.case_id]),
            provenance=_provenance_to_dict(_case_by_id(cases, v.case_id).provenance),
            error=v.error,
        )
        for v in verdicts
    ]
    return case_results, aggregate, model_ref, None, prompts


def _run_tool_cases(
    manifest_handle: L.Manifest,
    manifest: T.BenchmarkManifest,
    cases: Sequence[T.CaseDefinition],
    *,
    model: str,
    seed: str | int | None,
    replay: Path | None,
    agent_adapter: M.AgentAdapter | None,
    dispatcher: M.CommandDispatcher | None,
    state_check_verifier: S.StateCheckVerifier | None,
) -> tuple[list[T.CaseResult], T.AggregateScore, T.ModelRef, str | None, list[str]]:
    del seed
    prompts = [_render_case_prompt(manifest, case, benchmark_dir=manifest_handle.dir) for case in cases]
    if replay is not None:
        replayed = _load_replay_dir(replay, cases)
        observed_by_id = {cid: state for cid, (_, state) in replayed.items()}
        model_ref = T.ModelRef(id=f"replay:{replay}", adapter="replay")
        sandbox_backend = "replay-no-exec"
        with _state_check_context(_state_check_impl(manifest, cases, state_check_verifier)):
            verdicts, aggregate = _score_cases(cases, observed_by_id, manifest=manifest)
        case_results = [
            T.CaseResult(
                case_id=v.case_id,
                verdict=v.verdict,
                score=v.score,
                expected=v.expected,
                provenance=_provenance_to_dict(_case_by_id(cases, v.case_id).provenance),
                error=v.error,
                transcript=tuple(replayed[v.case_id][0]),
                final_repo_state=replayed[v.case_id][1],
            )
            for v in verdicts
        ]
        return case_results, aggregate, model_ref, sandbox_backend, prompts

    adapter = agent_adapter
    if adapter is None:
        if model != "stub":
            raise RunnerError(
                "C05 has no live agent adapters; use --model stub or --replay"
            )
        adapter = M.StubAgent()
    active_dispatcher = dispatcher or SB.select_dispatcher()
    observed_by_id: dict[str, T.RepoState] = {}
    transcripts: dict[str, tuple[T.ToolAction, ...]] = {}
    for case, prompt in zip(cases, prompts, strict=True):
        with _sandbox_for_case(manifest_handle, case) as sandbox:
            try:
                actions = tuple(
                    adapter.actions(prompt, params=dict(manifest.sampling), sandbox=sandbox)
                )
                rows = tuple(
                    active_dispatcher.dispatch(action, sandbox=sandbox) for action in actions
                )
                state = active_dispatcher.snapshot(sandbox=sandbox, transcript=rows)
            except Exception as exc:
                raise RunnerError(f"agent/dispatcher failed for case {case.id!r}: {exc}") from exc
        observed_by_id[case.id] = state
        transcripts[case.id] = rows

    with _state_check_context(_state_check_impl(manifest, cases, state_check_verifier)):
        verdicts, aggregate = _score_cases(cases, observed_by_id, manifest=manifest)
    case_results = [
        T.CaseResult(
            case_id=v.case_id,
            verdict=v.verdict,
            score=v.score,
            expected=v.expected,
            provenance=_provenance_to_dict(_case_by_id(cases, v.case_id).provenance),
            error=v.error,
            transcript=transcripts[v.case_id],
            final_repo_state=observed_by_id[v.case_id],
        )
        for v in verdicts
    ]
    return (
        case_results,
        aggregate,
        T.ModelRef(id=adapter.model_id, provider=adapter.provider, adapter=adapter.adapter_kind),
        active_dispatcher.backend_id,
        prompts,
    )


def _score_cases(
    cases: Sequence[T.CaseDefinition],
    observed_by_id: Mapping[str, Any],
    *,
    manifest: T.BenchmarkManifest,
) -> tuple[list[S.CaseVerdict], T.AggregateScore]:
    try:
        return S.score_cases(
            cases,
            observed_by_id,
            metric=manifest.metric,
            benchmark_llm_judge=manifest.llm_judge,
        )
    except NotImplementedError as exc:
        raise RunnerError(str(exc)) from exc
    except S.VerifierError as exc:
        raise RunnerError(f"verifier failed: {exc}") from exc
    except Exception as exc:
        raise RunnerError(f"scoring failed: {exc}") from exc


def _load_predictions_dir(path: Path, cases: Sequence[T.CaseDefinition]) -> dict[str, str]:
    if not path.is_dir():
        raise RunnerError(f"prediction directory not found: {path}")
    out: dict[str, str] = {}
    for case in cases:
        candidates = (path / f"{case.id}.txt", path / case.id)
        found = next((p for p in candidates if p.is_file()), None)
        if found is None:
            raise RunnerError(
                f"missing prediction for case {case.id!r}: expected {candidates[0]}"
            )
        try:
            out[case.id] = found.read_text(encoding="utf-8")
        except OSError as exc:
            raise RunnerError(f"could not read prediction {found}: {exc}") from exc
    return out


def _load_predictions_file(path: Path, cases: Sequence[T.CaseDefinition]) -> dict[str, str]:
    if not path.is_file():
        raise RunnerError(f"prediction file not found: {path}")
    try:
        if path.suffix == ".jsonl":
            raw: dict[str, str] = {}
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if not line.strip():
                    continue
                item = json.loads(line)
                if not isinstance(item, Mapping):
                    raise RunnerError(f"{path}:{lineno}: JSONL prediction must be an object")
                cid = item.get("case_id")
                pred = item.get("prediction", item.get("observed"))
                if not isinstance(cid, str) or not isinstance(pred, str):
                    raise RunnerError(
                        f"{path}:{lineno}: prediction object requires string case_id and prediction"
                    )
                raw[cid] = pred
        else:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(loaded, Mapping):
                raise RunnerError("prediction file must be a JSON object mapping case id to text")
            raw = {str(k): _prediction_text(v, key=str(k)) for k, v in loaded.items()}
    except json.JSONDecodeError as exc:
        raise RunnerError(f"could not parse prediction file {path}: {exc}") from exc
    except OSError as exc:
        raise RunnerError(f"could not read prediction file {path}: {exc}") from exc

    missing = [case.id for case in cases if case.id not in raw]
    if missing:
        raise RunnerError(f"prediction file missing case(s): {', '.join(missing)}")
    return {case.id: raw[case.id] for case in cases}


def _prediction_text(value: Any, *, key: str) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        pred = value.get("prediction", value.get("observed"))
        if isinstance(pred, str):
            return pred
    raise RunnerError(f"prediction for case {key!r} must be text")


def _load_replay_dir(
    path: Path,
    cases: Sequence[T.CaseDefinition],
) -> dict[str, tuple[tuple[T.ToolAction, ...], T.RepoState]]:
    if not path.is_dir():
        raise RunnerError(f"replay transcript directory not found: {path}")
    out: dict[str, tuple[tuple[T.ToolAction, ...], T.RepoState]] = {}
    for case in cases:
        out[case.id] = _load_replay_case(path, case.id)
    return out


def _load_replay_case(path: Path, case_id: str) -> tuple[tuple[T.ToolAction, ...], T.RepoState]:
    json_path = path / f"{case_id}.json"
    jsonl_path = path / f"{case_id}.jsonl"
    if json_path.is_file():
        try:
            raw = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RunnerError(f"could not read replay transcript {json_path}: {exc}") from exc
        transcript_raw, state_raw = _split_replay_json(raw, source=json_path, case_id=case_id)
    elif jsonl_path.is_file():
        try:
            transcript_raw = [
                json.loads(line)
                for line in jsonl_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        except (OSError, json.JSONDecodeError) as exc:
            raise RunnerError(f"could not read replay transcript {jsonl_path}: {exc}") from exc
        state_raw = None
    else:
        raise RunnerError(
            f"missing replay transcript for case {case_id!r}: expected {json_path} or {jsonl_path}"
        )

    if not isinstance(transcript_raw, list):
        raise RunnerError(f"replay transcript for case {case_id!r} must be an array")
    try:
        transcript = tuple(RR.tool_action_from_mapping(a) for a in transcript_raw)
    except RR.RunRecordValidationError as exc:
        raise RunnerError(f"invalid replay transcript for case {case_id!r}: {exc}") from exc

    if state_raw is None:
        state_path = path / f"{case_id}.state.json"
        if state_path.is_file():
            try:
                state_raw = json.loads(state_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise RunnerError(f"could not read replay state {state_path}: {exc}") from exc
    if state_raw is None:
        state = _materialize_replay_state(transcript)
    elif isinstance(state_raw, Mapping):
        try:
            state = RR.repo_state_from_mapping(state_raw)
        except RR.RunRecordValidationError as exc:
            raise RunnerError(f"invalid replay final_repo_state for case {case_id!r}: {exc}") from exc
    else:
        raise RunnerError(f"replay final_repo_state for case {case_id!r} must be an object")
    return transcript, state


def _split_replay_json(
    raw: Any,
    *,
    source: Path,
    case_id: str,
) -> tuple[Any, Any | None]:
    if isinstance(raw, list):
        return raw, None
    if not isinstance(raw, Mapping):
        raise RunnerError(f"{source}: replay JSON must be an object or transcript array")
    raw_case_id = raw.get("case_id")
    if raw_case_id is not None and raw_case_id != case_id:
        raise RunnerError(f"{source}: case_id {raw_case_id!r} does not match expected {case_id!r}")
    transcript = raw.get("transcript", raw.get("actions"))
    if transcript is None:
        raise RunnerError(f"{source}: replay object requires transcript or actions")
    return transcript, raw.get("final_repo_state")


def _materialize_replay_state(transcript: Sequence[T.ToolAction]) -> T.RepoState:
    """Materialize a best-effort final repo state from a replay transcript.

    Only successful ``file.write`` actions contribute to the file tree: writes
    with a non-zero exit code (including an unknown/``None`` exit code), a
    timeout, or a sandbox boundary violation are ignored since they may not
    have produced a file.  The written path (``argv[0]``) is normalized
    against the action's relative ``cwd`` so a write executed from a
    subdirectory is recorded at its in-sandbox location.
    Paths that cannot be normalized to a clean relative in-sandbox path are
    skipped rather than recorded with a misleading absolute or escaping path.
    """
    file_tree: list[str] = []
    for action in transcript:
        if action.command != "file.write" or not action.argv:
            continue
        if action.exit_code != 0:
            continue
        if action.timeout or action.sandbox_boundary_violation:
            continue
        normalized = _normalize_sandbox_path(str(action.argv[0]), cwd=action.cwd)
        if normalized is not None:
            file_tree.append(normalized)
    return T.RepoState(
        file_tree=tuple(sorted(set(file_tree))),
        git_status="",
        branches=("main",),
        commits=({"sha": "c05replay", "subject": "C05 replay snapshot"},),
        diff="",
    )


def _normalize_sandbox_path(path: str, *, cwd: str) -> str | None:
    """Normalize a tool-action path against its relative cwd into an in-sandbox path.

    Returns a POSIX-style relative path with no ``..`` segments that escape the
    sandbox root, or ``None`` if the path is absolute or escapes the sandbox.
    The sandbox root is implicit (the dispatcher executes inside it), so an
    absolute path is treated as untrustworthy and rejected rather than stripped.
    """
    if not path:
        return None
    p = Path(path)
    if p.is_absolute():
        return None
    base = Path(cwd) if cwd else Path(".")
    if base.is_absolute():
        return None
    joined = base / path
    parts: list[str] = []
    for part in joined.parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                return None
            parts.pop()
            continue
        parts.append(part)
    if not parts:
        return None
    return "/".join(parts)


@contextmanager
def _sandbox_for_case(manifest: L.Manifest, case: T.CaseDefinition) -> Iterable[M.SandboxHandle]:
    with tempfile.TemporaryDirectory(prefix=f"ai-bench-{case.id}-") as tmp:
        root = Path(tmp)
        fixture_path = _copy_fixture_if_present(manifest, case, root)
        metadata: dict[str, Any] = {}
        if isinstance(case.input, T.CaseInput):
            if "script" in case.input.extra:
                metadata["stub_actions"] = case.input.extra["script"]
        yield M.SandboxHandle(
            root=root,
            case_id=case.id,
            fixture_path=fixture_path,
            allowed_commands=("git", "file.write", "file.read"),
            env_allowlist=(),
            default_timeout_ms=10_000,
            metadata=metadata,
        )


def _copy_fixture_if_present(manifest: L.Manifest, case: T.CaseDefinition, root: Path) -> Path | None:
    if not isinstance(case.input, T.CaseInput) or not case.input.fixture:
        return None
    fixture = Path(case.input.fixture)
    if fixture.is_absolute():
        raise RunnerError(f"case {case.id!r} fixture path must be relative")
    base = manifest.dir.resolve()
    source = (base / fixture).resolve()
    try:
        source.relative_to(base)
    except ValueError:
        raise RunnerError(f"case {case.id!r} fixture path escapes benchmark directory")
    if not source.exists():
        raise RunnerError(f"case {case.id!r} fixture not found: {source}")
    _reject_unsafe_fixture(source, base=base, case_id=case.id)
    if source.is_dir():
        shutil.copytree(source, root, dirs_exist_ok=True)
    else:
        target = root / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return source


def _reject_unsafe_fixture(source: Path, *, base: Path, case_id: str) -> None:
    """Reject fixtures that contain symlinks or resolved paths escaping ``base``.

    ``shutil.copytree`` follows nested symlinks, which can copy host data
    outside the benchmark directory into the sandbox.  Walk the fixture tree
    first and fail the run if any entry is a symlink or resolves outside the
    benchmark directory.  The top-level ``source`` is checked too.
    """
    if source.is_symlink():
        raise RunnerError(
            f"case {case_id!r} fixture {source} is a symlink; symlinks are not allowed"
        )
    try:
        source.resolve().relative_to(base)
    except ValueError:
        raise RunnerError(
            f"case {case_id!r} fixture {source} resolves outside the benchmark directory"
        ) from None
    if not source.is_dir():
        return
    for entry in _walk_fixture(source):
        if entry.is_symlink():
            raise RunnerError(
                f"case {case_id!r} fixture contains symlink {entry}; symlinks are not allowed"
            )
        try:
            entry.resolve().relative_to(base)
        except ValueError:
            raise RunnerError(
                f"case {case_id!r} fixture entry {entry} resolves outside the benchmark directory"
            ) from None


def _walk_fixture(root: Path) -> Iterable[Path]:
    """Yield every path beneath ``root`` (files, dirs, and their contents)."""
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            yield Path(dirpath, name)


def _state_check_impl(
    manifest: T.BenchmarkManifest,
    cases: Sequence[T.CaseDefinition],
    explicit: S.StateCheckVerifier | None,
) -> S.StateCheckVerifier | None:
    if explicit is not None:
        return explicit
    if _uses_c05_stub_state_check(manifest, cases):
        return C05StubStateCheckVerifier()
    # C07.2: register the real repo-state verifier for tool-task cases that
    # do not opt into the C05 fake. This is the real-verifier acceptance that
    # C05 deliberately deferred; the verifier operates on the C02 RepoState
    # snapshot and does not touch the sandbox.
    return S.RepoStateVerifier()


def _uses_c05_stub_state_check(
    manifest: T.BenchmarkManifest,
    cases: Sequence[T.CaseDefinition],
) -> bool:
    for case in cases:
        params = dict(manifest.metric.params)
        if case.verifier is not None:
            params.update(case.verifier.params)
        if "c05_stub_state_check" in params:
            return True
    return False


@contextmanager
def _state_check_context(impl: S.StateCheckVerifier | None) -> Iterable[None]:
    if impl is None:
        yield
        return
    previous = getattr(S, "_state_check_impl", None)
    S.register_state_check_verifier(impl)
    try:
        yield
    finally:
        setattr(S, "_state_check_impl", previous)


def _manifest_from_mapping(data: Mapping[str, Any]) -> T.BenchmarkManifest:
    return T.BenchmarkManifest(
        schema_version=data["schema_version"],
        id=str(data["id"]),
        name=str(data["name"]),
        description=str(data["description"]),
        domain=str(data["domain"]),
        task_type=data["task_type"],
        metric=_metric_from_mapping(data["metric"]),
        version=str(data["version"]),
        contributor=_contributor_from_mapping(data["contributor"]),
        license=str(data["license"]),
        case_glob=str(data["case_glob"]),
        tags=tuple(data.get("tags", ())),
        status=data.get("status", "experimental"),
        prompt_template=_prompt_template_from_mapping(data.get("prompt_template")),
        sampling=dict(data.get("sampling", {})),
        llm_judge=_llm_judge_from_mapping(data.get("llm_judge")),
    )


def _metric_from_mapping(data: Mapping[str, Any]) -> T.MetricConfig:
    return T.MetricConfig(
        verifier=data["verifier"],
        params=dict(data.get("params", {})),
    )


def _contributor_from_mapping(data: Mapping[str, Any]) -> T.Contributor:
    return T.Contributor(
        name=str(data["name"]),
        contact=data.get("contact"),
        url=data.get("url"),
    )


def _prompt_template_from_mapping(data: Any) -> T.PromptTemplate | None:
    if data is None:
        return None
    return T.PromptTemplate(
        version=str(data["version"]),
        template=data.get("template"),
        path=data.get("path"),
    )


def _llm_judge_from_mapping(data: Any) -> T.LLMJudgeConfig | None:
    if data is None:
        return None
    return T.LLMJudgeConfig(
        judge_model=str(data["judge_model"]),
        judge_prompt=str(data["judge_prompt"]),
        judge_seed=data["judge_seed"],
        judge_params=dict(data.get("judge_params", {})),
    )


def _case_from_mapping(data: Mapping[str, Any]) -> T.CaseDefinition:
    return T.CaseDefinition(
        schema_version=data["schema_version"],
        id=str(data["id"]),
        input=_case_input_from_mapping(data["input"]),
        expected=data.get("expected"),
        expected_metadata=data.get("expected_metadata"),
        tags=tuple(data.get("tags", ())),
        difficulty=data.get("difficulty", "medium"),
        provenance=_provenance_from_mapping(data.get("provenance")),
        verifier=_verifier_override_from_mapping(data.get("verifier")),
        state_check=_state_check_from_mapping(data.get("state_check")),
        llm_judge=_llm_judge_from_mapping(data.get("llm_judge")),
        notes=data.get("notes"),
    )


def _case_input_from_mapping(data: Any) -> str | T.CaseInput:
    if isinstance(data, str):
        return data
    if not isinstance(data, Mapping):  # schema prevents this
        return str(data)
    extra = {str(k): v for k, v in data.items() if k not in {"prompt", "fixture"}}
    return T.CaseInput(
        prompt=data.get("prompt"),
        fixture=data.get("fixture"),
        extra=extra,
    )


def _provenance_from_mapping(data: Any) -> T.Provenance | None:
    if data is None:
        return None
    return T.Provenance(
        source=data.get("source"),
        author=data.get("author"),
        license=data.get("license"),
        url=data.get("url"),
        notes=data.get("notes"),
    )


def _provenance_to_dict(provenance: T.Provenance | None) -> dict[str, Any] | None:
    if provenance is None:
        return None
    out: dict[str, Any] = {}
    if provenance.source is not None:
        out["source"] = provenance.source
    if provenance.author is not None:
        out["author"] = provenance.author
    if provenance.license is not None:
        out["license"] = provenance.license
    if provenance.url is not None:
        out["url"] = provenance.url
    if provenance.notes is not None:
        out["notes"] = provenance.notes
    return out


def _verifier_override_from_mapping(data: Any) -> T.CaseVerifierOverride | None:
    if data is None:
        return None
    return T.CaseVerifierOverride(
        verifier=data["verifier"],
        params=dict(data.get("params", {})),
    )


def _state_check_from_mapping(data: Any) -> T.StateCheckSpec | None:
    if data is None:
        return None
    return T.StateCheckSpec(
        files=dict(data.get("files", {})),
        git=dict(data.get("git", {})),
        absent=tuple(data.get("absent", ())),
    )


def _render_case_prompt(
    manifest: T.BenchmarkManifest,
    case: T.CaseDefinition,
    *,
    benchmark_dir: Path | None = None,
) -> str:
    if isinstance(case.input, str):
        input_text = case.input
    elif case.input.prompt is not None:
        input_text = case.input.prompt
    else:
        input_text = L.canonical_json({"fixture": case.input.fixture, **dict(case.input.extra)})
    tmpl = _resolve_prompt_template(manifest, benchmark_dir=benchmark_dir, case_id=case.id)
    if tmpl is None:
        return input_text
    try:
        return tmpl.format(input=input_text, case_id=case.id)
    except Exception as exc:
        raise RunnerError(f"could not render prompt for case {case.id!r}: {exc}") from exc


def _resolve_prompt_template(
    manifest: T.BenchmarkManifest,
    *,
    benchmark_dir: Path | None,
    case_id: str,
) -> str | None:
    """Resolve the prompt template text from an inline string or a file path.

    ``prompt_template.template`` (inline) takes precedence when present.  When
    only ``prompt_template.path`` is set, the file is loaded relative to the
    benchmark directory and confined to it.  A path-only template without a
    benchmark directory, an absolute/escaping path, or a missing/unreadable
    file is a runner infrastructure failure.
    """
    pt = manifest.prompt_template
    if pt is None:
        return None
    if pt.template is not None:
        return pt.template
    if pt.path is None:
        return None
    if benchmark_dir is None:
        raise RunnerError(
            f"prompt_template.path set for case {case_id!r} but no benchmark "
            "directory is available to resolve it"
        )
    path = Path(pt.path)
    if path.is_absolute():
        raise RunnerError(
            f"prompt_template.path for case {case_id!r} must be relative: {pt.path!r}"
        )
    base = Path(benchmark_dir).resolve()
    resolved = (base / path).resolve()
    try:
        resolved.relative_to(base)
    except ValueError:
        raise RunnerError(
            f"prompt_template.path for case {case_id!r} escapes benchmark directory: {pt.path!r}"
        ) from None
    if not resolved.is_file():
        raise RunnerError(
            f"prompt_template.path for case {case_id!r} not found: {resolved}"
        )
    try:
        return resolved.read_text(encoding="utf-8")
    except OSError as exc:
        raise RunnerError(
            f"could not read prompt_template.path for case {case_id!r}: {exc}"
        ) from exc


def _run_prompt(manifest: T.BenchmarkManifest, rendered_prompts: Sequence[str]) -> T.RunPrompt:
    if manifest.prompt_template is not None:
        return T.RunPrompt(
            version=manifest.prompt_template.version,
            template=manifest.prompt_template.template,
            path=manifest.prompt_template.path,
            rendered=rendered_prompts[0] if len(rendered_prompts) == 1 else None,
        )
    return T.RunPrompt(
        version=manifest.version,
        template=None,
        path=None,
        rendered=rendered_prompts[0] if len(rendered_prompts) == 1 else None,
    )


def _metric_params(manifest: T.BenchmarkManifest, cases: Sequence[T.CaseDefinition]) -> dict[str, Any]:
    out = dict(manifest.metric.params)
    overrides: dict[str, Any] = {}
    for case in cases:
        if case.verifier is None:
            continue
        overrides[case.id] = {
            "verifier": case.verifier.verifier,
            "params": dict(case.verifier.params),
        }
    if overrides:
        out["_case_overrides"] = overrides
    return out


def _run_verifier(manifest: T.BenchmarkManifest) -> T.RunVerifier:
    judge = None
    if manifest.llm_judge is not None:
        judge = T.RunJudgeConfig(
            judge_model=manifest.llm_judge.judge_model,
            judge_prompt=manifest.llm_judge.judge_prompt,
            judge_seed=manifest.llm_judge.judge_seed,
            judge_params=dict(manifest.llm_judge.judge_params),
        )
    return T.RunVerifier(
        name=manifest.metric.verifier,
        version=S.VERIFIER_VERSION,
        judge_config=judge,
    )


def _case_by_id(cases: Sequence[T.CaseDefinition], case_id: str) -> T.CaseDefinition:
    for case in cases:
        if case.id == case_id:
            return case
    raise RunnerError(f"internal runner error: missing case {case_id!r}")


def _minimal_record_for_model(
    model_ref: T.ModelRef,
    manifest: T.BenchmarkManifest,
    prompt: T.RunPrompt,
    seed: str | int | None,
    env_hash: str,
    metric_params: Mapping[str, Any],
) -> T.RunRecord:
    return T.RunRecord(
        schema_version=T.SCHEMA_VERSION,  # type: ignore[arg-type]
        run_id="run-id-placeholder",
        benchmark=T.BenchmarkRef(
            id=manifest.id,
            version=manifest.version,
            task_type=manifest.task_type,
        ),
        model=model_ref,
        prompt=prompt,
        sampling_params=dict(manifest.sampling),
        seed=seed,
        fixture_version=manifest.version,
        manifest_version=manifest.version,
        environment_hash=env_hash,
        metric_params=dict(metric_params),
        verifier=_run_verifier(manifest),
        cases=(),
        aggregate=T.AggregateScore(metric=manifest.metric.verifier, value=0.0, n_cases=0),
    )
