"""Benchmark loader, validator, and discovery for ai-bench (chunk C03).

This module is the schema/loader gate delivered by C03. It loads benchmark
manifests and case files from disk using ``yaml.safe_load`` exclusively,
validates them against the v1 JSON Schemas frozen by C02, discovers benchmark
directories, resolves case globs safely (case files cannot escape the benchmark
directory), and provides tag-based subset selection plus deterministic
canonical serialization for stable comparisons.

Scope (C03):
  * Safe YAML/JSON loading.
  * Manifest + case schema validation (including benchmark ``tags``/``status``
    and the reserved case ``smoke`` tag).
  * ``discover_benchmarks(root)`` glob discovery with unique-id checks,
    excluding ``benchmarks/_template/**`` so the contribution template is never
    registered or conformance-tested as a real benchmark.
  * ``load_cases(benchmark)`` resolving ``case_glob`` safely inside the
    benchmark directory, with tag-based subset selection support.
  * Deterministic canonical serialization helper.
  * Actionable, per-file/per-field validation errors.

Non-goals (owned by later chunks): scoring/verifier engine (C04), runner/model
adapters/run-records (C05), sandbox (C07), failure store (C09), template/
registry/contribution workflow (C10). This module does not run benchmarks,
score outputs, or touch the failure store.
"""

from __future__ import annotations

import copy
import glob as _glob
import json
import os
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

import jsonschema
import yaml

from ai_bench import types as T

__all__ = [
    "SCHEMAS_DIR",
    "LoadError",
    "ValidationError",
    "BenchmarkLoadError",
    "load_yaml",
    "load_json",
    "load_schema",
    "canonicalize",
    "validate_manifest",
    "validate_case",
    "Manifest",
    "load_benchmark",
    "load_cases",
    "select_cases",
    "discover_benchmarks",
    "validate_benchmark",
    "format_validation_errors",
]


# --- Constants --------------------------------------------------------------


# Repository root as seen from this module: ``src/ai_bench/loader.py`` ->
# ``<repo>/src/ai_bench/loader.py`` -> repo root is three parents up.
_REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMAS_DIR: Path = _REPO_ROOT / "schemas"

# The contribution template directory is excluded from discovery and the
# release validate-all gate. Template validation is owned by C10.
_TEMPLATE_DIR_NAME = "_template"

# Manifest filename looked for inside each benchmark directory.
MANIFEST_FILENAME = "benchmark.yaml"

# Reserved case-level tag selecting a benchmark's smoke subset via --tag smoke.
# Mirrored from ``ai_bench.types.SMOKE_TAG`` to keep this module self-contained
# for tag validation.
_SMOKE_TAG = T.SMOKE_TAG


# --- Exceptions -------------------------------------------------------------


class LoadError(Exception):
    """Base class for loader errors. Carries an actionable message."""


class ValidationError(LoadError):
    """One or more schema/loader validation errors for a benchmark.

    The ``errors`` attribute holds a list of ``jsonschema.ValidationError``
    instances (or equivalent structured errors). ``format_validation_errors``
    renders them into actionable per-file/per-field text.
    """

    def __init__(
        self,
        message: str,
        *,
        errors: Sequence[jsonschema.ValidationError] | Sequence[str] | None = None,
        source: str | None = None,
    ) -> None:
        super().__init__(message)
        self.errors: list[Any] = list(errors) if errors is not None else []
        self.source = source


class BenchmarkLoadError(LoadError):
    """A benchmark directory could not be loaded (missing manifest, I/O, etc)."""


# --- Safe loading -----------------------------------------------------------


def load_yaml(path: Path | str) -> Any:
    """Load a YAML file using ``yaml.safe_load`` exclusively.

    Unsafe YAML loaders (``yaml.load`` without ``SafeLoader`` /
    ``yaml.unsafe_load`` / ``yaml.full_load``) are never used anywhere in this
    module. Benchmark definitions are human-editable YAML validated by JSON
    Schema; runtime code must use ``yaml.safe_load`` only.
    """
    p = Path(path)
    try:
        with p.open("r", encoding="utf-8") as fh:
            return yaml.safe_load(fh)
    except FileNotFoundError as exc:
        raise LoadError(f"file not found: {p}") from exc
    except yaml.YAMLError as exc:
        raise LoadError(f"YAML parse error in {p}: {exc}") from exc
    except OSError as exc:
        raise LoadError(f"could not read {p}: {exc}") from exc


def load_json(path: Path | str) -> Any:
    """Load a JSON file (used for schemas and JSON benchmark definitions)."""
    p = Path(path)
    try:
        with p.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError as exc:
        raise LoadError(f"file not found: {p}") from exc
    except json.JSONDecodeError as exc:
        raise LoadError(f"JSON parse error in {p}: {exc}") from exc
    except OSError as exc:
        raise LoadError(f"could not read {p}: {exc}") from exc


# Schema cache keyed by schema filename so repeated validation does not re-read
# and re-compile schemas.
_schema_cache: dict[str, jsonschema.Draft202012Validator] = {}


def load_schema(name: str) -> dict[str, Any]:
    """Load a JSON Schema document from the ``schemas/`` directory by name."""
    return load_json(SCHEMAS_DIR / name)  # type: ignore[no-any-return]


def _validator(name: str) -> jsonschema.Draft202012Validator:
    """Return a cached ``Draft202012Validator`` for the named schema file."""
    cached = _schema_cache.get(name)
    if cached is not None:
        return cached
    schema = load_schema(name)
    validator = jsonschema.Draft202012Validator(schema)
    _schema_cache[name] = validator
    return validator


# --- Canonical serialization ------------------------------------------------


def canonicalize(obj: Any) -> Any:
    """Return a deterministic, JSON-compatible canonical form of ``obj``.

    Used for stable comparisons across repeated loads. The canonical form:
      * Converts dataclass instances to dicts (recursively).
      * Sorts dict keys.
      * Sorts list elements ONLY when explicitly tagged as set-like via a
        ``frozenset``/``set`` input (plain lists preserve order, since case
        order and tag order are meaningful in fixtures).
      * Preserves ``None`` as JSON ``null`` so explicit fixture fields such as
        ``expected: null`` remain semantically visible.
      * Produces a stable JSON-serializable structure.

    Determinism is asserted by ``tests/test_loader.py``: canonicalizing the
    same manifest/case twice yields byte-identical JSON via ``json.dumps`` with
    ``sort_keys=True``.
    """
    return _canonicalize(obj)


def _canonicalize(obj: Any) -> Any:
    if is_dataclass(obj) and not isinstance(obj, type):
        return _canonicalize(asdict(obj))
    if isinstance(obj, Mapping):
        return {
            str(key): _canonicalize(obj[key])
            for key in sorted(obj.keys(), key=lambda k: str(k))
        }
    if isinstance(obj, (frozenset, set)):
        return sorted(_canonicalize(v) for v in obj)
    if isinstance(obj, (list, tuple)):
        return [_canonicalize(v) for v in obj]
    return obj


def canonical_json(obj: Any) -> str:
    """Render the canonical form of ``obj`` as deterministic JSON text."""
    return json.dumps(canonicalize(obj), sort_keys=True, ensure_ascii=False)


# --- Validation -------------------------------------------------------------


def _format_path(path: Sequence[str | int]) -> str:
    if not path:
        return "(root)"
    parts: list[str] = []
    for elem in path:
        if isinstance(elem, int):
            parts.append(f"[{elem}]")
        else:
            parts.append(f".{elem}" if parts else str(elem))
    return "".join(parts)


def _jsonschema_error_lines(error: jsonschema.ValidationError) -> list[str]:
    """Render a schema error plus nested context into path-qualified lines."""
    lines = [f"{_format_path(list(error.absolute_path))}: {error.message}"]
    nested = sorted(
        error.context,
        key=lambda e: (
            tuple(str(part) for part in e.absolute_path),
            tuple(str(part) for part in e.schema_path),
            e.message,
        ),
    )
    for child in nested:
        for line in _jsonschema_error_lines(child):
            if line not in lines:
                lines.append(line)
    return lines


def _validation_error_detail_lines(error: ValidationError) -> list[str]:
    """Render nested validation details without the top-level summary line."""
    lines: list[str] = []
    for e in error.errors:
        if isinstance(e, jsonschema.ValidationError):
            lines.extend(_jsonschema_error_lines(e))
        else:
            lines.append(str(e))
    return lines


def _schema_errors(
    schema_name: str, instance: Any
) -> list[jsonschema.ValidationError]:
    return list(_validator(schema_name).iter_errors(instance))


def validate_manifest(manifest: Mapping[str, Any]) -> None:
    """Validate a benchmark manifest against ``benchmark.schema.json``.

    Raises ``ValidationError`` with all schema errors if invalid. Benchmark
    ``tags``/``status`` and the manifest shape are enforced by the schema.
    """
    errors = _schema_errors("benchmark.schema.json", dict(manifest))
    if errors:
        raise ValidationError(
            f"manifest schema validation failed with {len(errors)} error(s)",
            errors=errors,
        )


def validate_case(case: Mapping[str, Any]) -> None:
    """Validate a single case against ``case.schema.json``.

    Raises ``ValidationError`` with all schema errors if invalid. The reserved
    ``smoke`` tag and case shape are enforced by the schema.
    """
    errors = _schema_errors("case.schema.json", dict(case))
    if errors:
        raise ValidationError(
            f"case schema validation failed with {len(errors)} error(s)",
            errors=errors,
        )


def _validate_tag_values(tags: Sequence[Any] | None, source: str) -> None:
    """Enforce tag value shape beyond the schema (defensive).

    The schema already constrains tag items to ``^[a-z0-9][a-z0-9_-]*$`` and
    uniqueness. This is a thin guard so loader-level tag handling fails with an
    actionable message if a non-list tags field slips through.
    """
    if tags is None:
        return
    if not isinstance(tags, list):
        raise ValidationError(
            f"{source}: 'tags' must be a list, got {type(tags).__name__}",
            errors=[f"{source}: tags must be a list"],
        )
    for tag in tags:
        if not isinstance(tag, str):
            raise ValidationError(
                f"{source}: tag values must be strings, got {type(tag).__name__}",
                errors=[f"{source}: tag {tag!r} is not a string"],
            )


# --- Benchmark loading ------------------------------------------------------


class Manifest:
    """A loaded, validated benchmark manifest paired with its directory.

    This is a thin loader-level handle consumed by ``load_cases`` and the
    validate CLI. It intentionally does not materialize the full
    ``ai_bench.types.BenchmarkManifest`` dataclass (that mapping is owned by
    consumers that need typed access); the loader keeps the schema-validated
    dict form so it can be canonicalized and compared deterministically.
    """

    __slots__ = ("dir", "data", "path")

    def __init__(self, dir: Path, data: Mapping[str, Any], path: Path) -> None:
        self.dir = dir
        self.data = dict(data)
        self.path = path

    @property
    def id(self) -> str:
        return str(self.data["id"])

    @property
    def case_glob(self) -> str:
        return str(self.data["case_glob"])

    @property
    def tags(self) -> list[str]:
        return list(self.data.get("tags", []))

    @property
    def status(self) -> str:
        return str(self.data.get("status", "experimental"))

    def canonical(self) -> str:
        return canonical_json(self.data)


def load_benchmark(benchmark_dir: Path | str) -> Manifest:
    """Load and validate a benchmark manifest from ``benchmark_dir``.

    Looks for ``benchmark.yaml`` (or ``benchmark.json``) inside the directory,
    loads it safely, validates it against ``benchmark.schema.json``, and
    returns a ``Manifest`` handle. Raises ``BenchmarkLoadError`` if the
    directory or manifest is missing, and ``ValidationError`` on schema
    failure.
    """
    bdir = Path(benchmark_dir).resolve()
    if not bdir.is_dir():
        raise BenchmarkLoadError(f"benchmark directory not found: {bdir}")

    manifest_path = bdir / MANIFEST_FILENAME
    if not manifest_path.exists():
        manifest_path = bdir / "benchmark.json"
    if not manifest_path.exists():
        raise BenchmarkLoadError(
            f"no benchmark.yaml/benchmark.json found in {bdir}"
        )

    if manifest_path.suffix == ".json":
        raw = load_json(manifest_path)
    else:
        raw = load_yaml(manifest_path)

    if not isinstance(raw, dict):
        raise ValidationError(
            f"{manifest_path}: manifest must be a mapping, got {type(raw).__name__}",
            source=str(manifest_path),
        )

    validate_manifest(raw)
    _validate_tag_values(raw.get("tags"), str(manifest_path))
    return Manifest(dir=bdir, data=raw, path=manifest_path)


# --- Safe case glob resolution ----------------------------------------------


def _resolve_case_glob(benchmark_dir: Path, case_glob: str) -> list[Path]:
    """Resolve ``case_glob`` to case files, confined to ``benchmark_dir``.

    Safety: the glob is resolved relative to the benchmark directory and the
    resulting paths are checked to ensure they remain inside the benchmark
    directory. Patterns containing ``..`` segments or absolute paths are
    rejected before resolution so case globs cannot escape the benchmark
    directory.
    """
    if not case_glob:
        raise BenchmarkLoadError("case_glob is empty")

    # Reject absolute globs and parent-escape segments up front.
    if os.path.isabs(case_glob):
        raise BenchmarkLoadError(
            f"case_glob must be relative to the benchmark directory, got absolute: {case_glob!r}"
        )
    # Normalize for inspection without resolving symlinks yet.
    norm = os.path.normpath(case_glob)
    if norm.startswith("..") or os.path.split(norm)[0] == ".." or f"{os.sep}..{os.sep}" in f"{os.sep}{norm}{os.sep}":
        raise BenchmarkLoadError(
            f"case_glob cannot escape the benchmark directory: {case_glob!r}"
        )

    base = benchmark_dir.resolve()
    # Use a glob rooted at base so matches are always under base.
    pattern = str(base / case_glob)
    matches = sorted(
        Path(m) for m in _glob.glob(pattern, recursive=True) if Path(m).is_file()
    )

    # Defense-in-depth: confirm every match is inside base after resolution.
    for m in matches:
        try:
            mr = m.resolve()
        except OSError as exc:
            raise BenchmarkLoadError(
                f"could not resolve case path {m}: {exc}"
            ) from exc
        try:
            mr.relative_to(base)
        except ValueError:
            raise BenchmarkLoadError(
                f"case glob escaped benchmark directory: {m} is not under {base}"
            )
    return matches


def load_cases(
    benchmark: Manifest | Path | str,
    *,
    tag: str | None = None,
) -> list[tuple[Path, Mapping[str, Any]]]:
    """Load and validate all cases for a benchmark.

    If ``benchmark`` is a ``Manifest``, its directory and ``case_glob`` are
    used directly. If it is a path, the benchmark is loaded first.

    Cases are resolved via ``_resolve_case_glob`` (confined to the benchmark
    directory), loaded with ``yaml.safe_load``/JSON, and validated against
    ``case.schema.json``. Duplicate case ids within a benchmark raise
    ``ValidationError``.

    When ``tag`` is given (e.g. ``"smoke"``), only cases carrying that tag in
    their ``tags`` array are returned. Tag selection is case-sensitive and
    matches the reserved ``smoke`` tag exactly.
    """
    if isinstance(benchmark, Manifest):
        manifest = benchmark
    else:
        manifest = load_benchmark(benchmark)

    case_paths = _resolve_case_glob(manifest.dir, manifest.case_glob)
    if not case_paths:
        raise BenchmarkLoadError(
            f"no case files matched case_glob {manifest.case_glob!r} in {manifest.dir}"
        )

    cases: list[tuple[Path, Mapping[str, Any]]] = []
    seen_ids: dict[str, Path] = {}
    errors: list[str] = []

    for cp in case_paths:
        try:
            if cp.suffix == ".json":
                raw = load_json(cp)
            else:
                raw = load_yaml(cp)
        except LoadError as exc:
            errors.append(f"{cp}: {exc}")
            continue

        if not isinstance(raw, dict):
            errors.append(f"{cp}: case must be a mapping, got {type(raw).__name__}")
            continue

        try:
            validate_case(raw)
        except ValidationError as exc:
            for e in exc.errors:
                if isinstance(e, jsonschema.ValidationError):
                    for detail in _jsonschema_error_lines(e):
                        errors.append(f"{cp}: {detail}")
                else:
                    errors.append(f"{cp}: {e}")
            continue

        _validate_tag_values(raw.get("tags"), str(cp))

        case_id = str(raw["id"])
        if case_id in seen_ids:
            errors.append(
                f"duplicate case id {case_id!r}: defined in {seen_ids[case_id]} and {cp}"
            )
            continue
        seen_ids[case_id] = cp

        if tag is not None and tag not in list(raw.get("tags", [])):
            continue

        cases.append((cp, dict(raw)))

    if errors:
        raise ValidationError(
            f"case validation failed with {len(errors)} error(s)",
            errors=errors,
        )
    return cases


def select_cases(
    cases: Sequence[tuple[Path, Mapping[str, Any]]],
    *,
    tag: str | None = None,
) -> list[tuple[Path, Mapping[str, Any]]]:
    """Filter an already-loaded list of cases by ``tag``.

    ``tag=None`` returns all cases. This mirrors the ``tag`` argument of
    ``load_cases`` for callers that load once and select many times.
    """
    if tag is None:
        return list(cases)
    return [
        (path, case)
        for path, case in cases
        if tag in list(case.get("tags", []))
    ]


# --- Discovery --------------------------------------------------------------


def discover_benchmarks(root: Path | str) -> list[Manifest]:
    """Discover benchmark directories under ``root``.

    A benchmark directory is any directory under ``<root>/benchmarks/**`` that
    contains a ``benchmark.yaml`` (or ``benchmark.json``) manifest. The
    contribution template at ``benchmarks/_template/**`` is excluded so it is
    never registered or conformance-tested as a real benchmark; template
    validation is owned by C10.

    Each discovered benchmark is loaded and schema-validated. Duplicate
    benchmark ids across discovered directories raise ``ValidationError``.

    Returns a list of ``Manifest`` objects sorted by benchmark id for
    deterministic output.
    """
    root_path = Path(root).resolve()
    benchmarks_root = root_path / "benchmarks"
    if not benchmarks_root.is_dir():
        return []

    discovered: list[Manifest] = []
    seen_ids: dict[str, Path] = {}
    load_errors: list[str] = []

    # Walk benchmarks/** skipping directories named _template relative to the
    # benchmarks root. The relative check is deliberate: a caller's repo path
    # may itself live under an unrelated ancestor named "_template".
    for dirpath, dirnames, filenames in os.walk(benchmarks_root):
        if _TEMPLATE_DIR_NAME in dirnames:
            dirnames.remove(_TEMPLATE_DIR_NAME)
        d = Path(dirpath)
        rel = d.relative_to(benchmarks_root)
        if _TEMPLATE_DIR_NAME in rel.parts:
            continue

        manifest_name: str | None = None
        for cand in (MANIFEST_FILENAME, "benchmark.json"):
            if cand in filenames:
                manifest_name = cand
                break
        if manifest_name is None:
            continue

        try:
            manifest = load_benchmark(d)
        except ValidationError as exc:
            error_source = d / manifest_name
            details = _validation_error_detail_lines(exc)
            if details:
                load_errors.extend(
                    f"{error_source}: {detail}" for detail in details
                )
            else:
                load_errors.append(f"{error_source}: {exc}")
            continue
        except BenchmarkLoadError as exc:
            load_errors.append(f"{d}: {exc}")
            continue

        bid = manifest.id
        if bid in seen_ids:
            load_errors.append(
                f"duplicate benchmark id {bid!r}: defined in {seen_ids[bid]} and {manifest.dir}"
            )
            continue
        seen_ids[bid] = manifest.dir
        discovered.append(manifest)

    if load_errors:
        raise ValidationError(
            f"benchmark discovery failed with {len(load_errors)} error(s)",
            errors=load_errors,
        )

    discovered.sort(key=lambda m: m.id)
    return discovered


# --- Whole-benchmark validation --------------------------------------------


def validate_benchmark(benchmark_dir: Path | str) -> Manifest:
    """Validate a benchmark's manifest AND all its cases against the schemas.

    This is the loader-level gate used by ``ai-bench validate <benchmark>``.
    It loads the manifest, validates it, resolves the case glob safely, loads
    every case, validates each against ``case.schema.json``, and checks for
    duplicate case ids. On any failure it raises ``ValidationError`` with
    actionable per-file/per-field errors. On success it returns the loaded
    ``Manifest``.
    """
    manifest = load_benchmark(benchmark_dir)
    # load_cases performs case glob resolution, per-case schema validation,
    # duplicate-id checks, and tag shape guards. We call it without a tag
    # filter so the whole benchmark is validated.
    load_cases(manifest)
    return manifest


# --- Error formatting -------------------------------------------------------


def format_validation_errors(error: ValidationError) -> str:
    """Render a ``ValidationError`` into actionable per-file/per-field lines."""
    lines: list[str] = [str(error)]
    for detail in _validation_error_detail_lines(error):
        lines.append(f"  - {detail}")
    return "\n".join(lines)
