"""Loader/validator tests for chunk C03.

Covers:
  * Safe YAML/JSON loading (``yaml.safe_load`` only; unsafe loaders never used).
  * Manifest + case schema validation (including benchmark ``tags``/``status``
    and the reserved case ``smoke`` tag).
  * ``discover_benchmarks(root)`` glob discovery with unique-id checks,
    excluding ``benchmarks/_template/**``.
  * ``load_cases(benchmark)`` safe case glob resolution (cannot escape the
    benchmark directory) and tag-based subset selection (``smoke`` and
    arbitrary tags).
  * Deterministic canonical serialization across repeated loads.
  * Actionable per-file/per-field errors for malformed manifests/cases,
    duplicate case ids, and escape-attempt globs.

No real benchmarks, scoring engine, runner, sandbox, or failure store are
exercised here -- those are owned by later chunks.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from ai_bench import loader as L

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "loader"
VALID = FIXTURES / "valid_benchmark"
MALFORMED_MANIFEST = FIXTURES / "malformed_manifest"
MALFORMED_CASE = FIXTURES / "malformed_case"
DUPLICATE_CASE_IDS = FIXTURES / "duplicate_case_ids"
ESCAPE_GLOB = FIXTURES / "escape_glob"
TOOL_TASK = FIXTURES / "tool_task_benchmark"


# --- Safe loading -----------------------------------------------------------


class TestSafeLoading:
    def test_load_yaml_uses_safe_load(self, tmp_path: Path) -> None:
        # A YAML document with a Python-specific tag must NOT be loaded into a
        # Python object; safe_load refuses it.
        p = tmp_path / "bad.yaml"
        p.write_text("!!python/object/apply:os.system ['echo hi']\n", encoding="utf-8")
        with pytest.raises(L.LoadError):
            L.load_yaml(p)

    def test_load_yaml_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(L.LoadError, match="file not found"):
            L.load_yaml(tmp_path / "missing.yaml")

    def test_load_json_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(L.LoadError, match="file not found"):
            L.load_json(tmp_path / "missing.json")

    def test_load_json_parse_error(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.json"
        p.write_text("{not json", encoding="utf-8")
        with pytest.raises(L.LoadError, match="JSON parse error"):
            L.load_json(p)

    def test_load_yaml_parse_error(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.yaml"
        p.write_text(":\n  - [unterminated\n", encoding="utf-8")
        with pytest.raises(L.LoadError, match="YAML parse error"):
            L.load_yaml(p)

    def test_load_schema_returns_dict(self) -> None:
        schema = L.load_schema("benchmark.schema.json")
        assert isinstance(schema, dict)
        assert schema["type"] == "object"


# --- Manifest validation ----------------------------------------------------


class TestManifestValidation:
    def test_valid_manifest_loads(self) -> None:
        manifest = L.load_benchmark(VALID)
        assert manifest.id == "loader-valid"
        assert manifest.status == "experimental"
        assert manifest.tags == ["recreation", "spatial-reasoning"]
        assert manifest.case_glob == "cases/*.yaml"

    def test_malformed_manifest_raises_validation_error(self) -> None:
        with pytest.raises(L.ValidationError) as exc:
            L.load_benchmark(MALFORMED_MANIFEST)
        # Actionable: multiple missing required fields reported.
        errs = exc.value.errors
        assert len(errs) >= 1
        assert any("required" in e.message.lower() for e in errs if isinstance(e, jsonschema.ValidationError))

    def test_unknown_status_rejected(self, tmp_path: Path) -> None:
        bdir = _make_benchmark_dir(
            tmp_path,
            manifest_overrides={"status": "draft"},
        )
        with pytest.raises(L.ValidationError) as exc:
            L.load_benchmark(bdir)
        errs = exc.value.errors
        assert any("draft" in e.message for e in errs if isinstance(e, jsonschema.ValidationError))

    def test_status_defaults_to_experimental_when_omitted(self, tmp_path: Path) -> None:
        bdir = _make_benchmark_dir(tmp_path, manifest_overrides={"status": None})
        manifest = L.load_benchmark(bdir)
        # The schema default is applied by the validator? No -- jsonschema
        # validation does not apply defaults. The Manifest.status property
        # falls back to "experimental" when the field is absent.
        assert manifest.status == "experimental"

    def test_malformed_tags_rejected(self, tmp_path: Path) -> None:
        bdir = _make_benchmark_dir(
            tmp_path,
            manifest_overrides={"tags": ["recreation", "recreation"]},  # not unique
        )
        with pytest.raises(L.ValidationError):
            L.load_benchmark(bdir)

    def test_missing_manifest_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(L.BenchmarkLoadError, match="no benchmark"):
            L.load_benchmark(tmp_path)

    def test_nonexistent_dir_raises(self, tmp_path: Path) -> None:
        with pytest.raises(L.BenchmarkLoadError, match="benchmark directory not found"):
            L.load_benchmark(tmp_path / "does_not_exist")

    def test_manifest_not_a_mapping(self, tmp_path: Path) -> None:
        bdir = tmp_path / "bm"
        bdir.mkdir()
        (bdir / "benchmark.yaml").write_text("- just\n- a list\n", encoding="utf-8")
        with pytest.raises(L.ValidationError, match="manifest must be a mapping"):
            L.load_benchmark(bdir)


# --- Case validation --------------------------------------------------------


class TestCaseValidation:
    def test_valid_cases_load(self) -> None:
        manifest = L.load_benchmark(VALID)
        cases = L.load_cases(manifest)
        ids = sorted(case["id"] for _, case in cases)
        assert ids == ["regular-case", "smoke-case"]

    def test_malformed_case_raises(self) -> None:
        manifest = L.load_benchmark(MALFORMED_CASE)
        with pytest.raises(L.ValidationError) as exc:
            L.load_cases(manifest)
        msg = L.format_validation_errors(exc.value)
        assert "id" in msg  # actionable: points at the missing id field

    def test_duplicate_case_ids_raise(self) -> None:
        manifest = L.load_benchmark(DUPLICATE_CASE_IDS)
        with pytest.raises(L.ValidationError) as exc:
            L.load_cases(manifest)
        assert any("duplicate case id" in str(e) for e in exc.value.errors)

    def test_no_case_files_raises(self, tmp_path: Path) -> None:
        bdir = _make_benchmark_dir(tmp_path, with_cases=False)
        manifest = L.load_benchmark(bdir)
        with pytest.raises(L.BenchmarkLoadError, match="no case files matched"):
            L.load_cases(manifest)

    def test_case_not_a_mapping(self, tmp_path: Path) -> None:
        bdir = _make_benchmark_dir(tmp_path, with_cases=False)
        cases_dir = bdir / "cases"
        cases_dir.mkdir()
        (cases_dir / "bad.yaml").write_text("- a\n- list\n", encoding="utf-8")
        manifest = L.load_benchmark(bdir)
        with pytest.raises(L.ValidationError) as exc:
            L.load_cases(manifest)
        assert any("case must be a mapping" in str(e) for e in exc.value.errors)

    def test_smoke_tag_reserved_and_selectable(self) -> None:
        manifest = L.load_benchmark(VALID)
        all_cases = L.load_cases(manifest)
        smoke_cases = L.load_cases(manifest, tag="smoke")
        assert len(all_cases) == 2
        assert len(smoke_cases) == 1
        assert smoke_cases[0][1]["id"] == "smoke-case"
        assert "smoke" in smoke_cases[0][1]["tags"]

    def test_arbitrary_tag_selection(self) -> None:
        manifest = L.load_benchmark(VALID)
        geo = L.load_cases(manifest, tag="geography")
        assert len(geo) == 1
        assert geo[0][1]["id"] == "regular-case"

    def test_select_cases_helper_filters_in_memory(self) -> None:
        manifest = L.load_benchmark(VALID)
        all_cases = L.load_cases(manifest)
        assert len(L.select_cases(all_cases, tag=None)) == 2
        assert len(L.select_cases(all_cases, tag="smoke")) == 1
        assert len(L.select_cases(all_cases, tag="nonexistent")) == 0

    def test_tool_task_case_with_null_expected_loads(self) -> None:
        manifest = L.load_benchmark(TOOL_TASK)
        cases = L.load_cases(manifest)
        assert len(cases) == 1
        case = cases[0][1]
        assert case["expected"] is None
        assert case["expected_metadata"]["reason"] == "preserved_failure_case"
        assert "state_check" in case

    def test_state_check_case_requires_state_check_block(self, tmp_path: Path) -> None:
        bdir = _make_benchmark_dir(
            tmp_path,
            manifest_overrides={
                "task_type": "tool-task",
                "metric": {"verifier": "state_check", "params": {}},
                "id": "tool-bm",
            },
            with_cases=False,
        )
        cases_dir = bdir / "cases"
        cases_dir.mkdir()
        (cases_dir / "c.yaml").write_text(
            _yaml(
                {
                    "schema_version": "1",
                    "id": "c1",
                    "input": {"prompt": "do thing", "fixture": "fixtures/r"},
                    "expected": "ok",
                    "tags": ["smoke"],
                    "difficulty": "easy",
                    "provenance": {"source": "original", "license": "MIT"},
                    "verifier": {"verifier": "state_check", "params": {}},
                }
            ),
            encoding="utf-8",
        )
        manifest = L.load_benchmark(bdir)
        with pytest.raises(L.ValidationError):
            L.load_cases(manifest)


# --- Safe case glob resolution ----------------------------------------------


class TestCaseGlobSafety:
    def test_escape_glob_rejected(self) -> None:
        manifest = L.load_benchmark(ESCAPE_GLOB)
        with pytest.raises(L.BenchmarkLoadError, match="escape"):
            L.load_cases(manifest)

    def test_absolute_glob_rejected(self, tmp_path: Path) -> None:
        bdir = _make_benchmark_dir(
            tmp_path,
            manifest_overrides={"case_glob": "/etc/hosts"},
        )
        manifest = L.load_benchmark(bdir)
        with pytest.raises(L.BenchmarkLoadError, match="absolute"):
            L.load_cases(manifest)

    def test_glob_confined_to_benchmark_dir(self, tmp_path: Path) -> None:
        # A glob that would match files outside the benchmark dir must not
        # return those files even if they exist on disk.
        bdir = _make_benchmark_dir(tmp_path, manifest_overrides={"id": "confined"})
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "leak.yaml").write_text(
            _yaml(
                {
                    "schema_version": "1",
                    "id": "leak",
                    "input": "x",
                    "expected": "y",
                    "tags": ["smoke"],
                    "difficulty": "easy",
                    "provenance": {"source": "original", "license": "MIT"},
                }
            ),
            encoding="utf-8",
        )
        manifest = L.load_benchmark(bdir)
        # The valid cases dir exists; the outside file must not be picked up.
        cases = L.load_cases(manifest)
        assert all("leak" != c["id"] for _, c in cases)


# --- Discovery --------------------------------------------------------------


class TestDiscovery:
    def test_discover_excludes_template(self, tmp_path: Path) -> None:
        root = _make_repo_with_benchmarks(tmp_path)
        manifests = L.discover_benchmarks(root)
        ids = [m.id for m in manifests]
        assert "_template" not in ids
        assert "real-a" in ids
        assert "real-b" in ids

    def test_discover_sorted_by_id(self, tmp_path: Path) -> None:
        root = _make_repo_with_benchmarks(tmp_path)
        manifests = L.discover_benchmarks(root)
        ids = [m.id for m in manifests]
        assert ids == sorted(ids)

    def test_discover_empty_when_no_benchmarks_dir(self, tmp_path: Path) -> None:
        assert L.discover_benchmarks(tmp_path) == []

    def test_discover_duplicate_benchmark_ids_raise(self, tmp_path: Path) -> None:
        root = tmp_path
        bdir = root / "benchmarks"
        bdir.mkdir()
        for sub in ("a", "b"):
            d = bdir / sub
            d.mkdir()
            (d / "benchmark.yaml").write_text(
                _yaml(_valid_manifest_dict(bid="dup-id")),
                encoding="utf-8",
            )
            (d / "cases").mkdir()
            (d / "cases" / "c.yaml").write_text(
                _yaml(_valid_case_dict(cid="c1")), encoding="utf-8"
            )
        with pytest.raises(L.ValidationError) as exc:
            L.discover_benchmarks(root)
        assert any("duplicate benchmark id" in str(e) for e in exc.value.errors)

    def test_discover_skips_directories_without_manifest(self, tmp_path: Path) -> None:
        root = tmp_path
        bdir = root / "benchmarks"
        bdir.mkdir()
        (bdir / "not_a_benchmark").mkdir()
        (bdir / "not_a_benchmark" / "random.txt").write_text("hi", encoding="utf-8")
        assert L.discover_benchmarks(root) == []

    def test_template_subdirectory_not_descended(self, tmp_path: Path) -> None:
        # Even a nested _template directory must be pruned.
        root = tmp_path
        bdir = root / "benchmarks"
        bdir.mkdir()
        nested = bdir / "group" / "_template"
        nested.mkdir(parents=True)
        (nested / "benchmark.yaml").write_text(
            _yaml(_valid_manifest_dict(bid="nested-template")),
            encoding="utf-8",
        )
        (nested / "cases").mkdir()
        (nested / "cases" / "c.yaml").write_text(
            _yaml(_valid_case_dict(cid="c1")), encoding="utf-8"
        )
        manifests = L.discover_benchmarks(root)
        assert all(not m.id.endswith("template") for m in manifests)


# --- Canonical serialization ------------------------------------------------


class TestCanonicalization:
    def test_canonical_is_deterministic_for_manifest(self) -> None:
        m1 = L.load_benchmark(VALID)
        m2 = L.load_benchmark(VALID)
        assert L.canonical_json(m1.data) == L.canonical_json(m2.data)

    def test_canonical_is_deterministic_for_cases(self) -> None:
        manifest = L.load_benchmark(VALID)
        cases1 = L.load_cases(manifest)
        cases2 = L.load_cases(manifest)
        for (p1, c1), (p2, c2) in zip(cases1, cases2):
            assert p1 == p2
            assert L.canonical_json(c1) == L.canonical_json(c2)

    def test_canonical_drops_none_entries(self) -> None:
        out = L.canonicalize({"a": 1, "b": None, "c": [1, None, 2]})
        assert out == {"a": 1, "c": [1, None, 2]}

    def test_canonical_sorts_dict_keys(self) -> None:
        out = L.canonicalize({"b": 1, "a": 2})
        assert list(out.keys()) == ["a", "b"]

    def test_canonical_sorts_sets(self) -> None:
        out = L.canonicalize({"s": {3, 1, 2}})
        assert out == {"s": [1, 2, 3]}

    def test_canonical_preserves_list_order(self) -> None:
        out = L.canonicalize({"tags": ["smoke", "geo"]})
        assert out == {"tags": ["smoke", "geo"]}

    def test_canonical_handles_dataclass(self) -> None:
        from ai_bench import types as T

        contrib = T.Contributor(name="x")
        out = L.canonicalize(contrib)
        assert out == {"name": "x"}

    def test_canonical_json_is_sorted_and_stable(self) -> None:
        text = L.canonical_json({"b": 1, "a": {"y": 2, "x": 1}})
        assert text == json.dumps({"a": {"x": 1, "y": 2}, "b": 1}, sort_keys=True, ensure_ascii=False)


# --- Whole-benchmark validation --------------------------------------------


class TestValidateBenchmark:
    def test_valid_benchmark_returns_manifest(self) -> None:
        manifest = L.validate_benchmark(VALID)
        assert manifest.id == "loader-valid"

    def test_malformed_manifest_raises(self) -> None:
        with pytest.raises(L.ValidationError):
            L.validate_benchmark(MALFORMED_MANIFEST)

    def test_malformed_case_raises(self) -> None:
        with pytest.raises(L.ValidationError):
            L.validate_benchmark(MALFORMED_CASE)

    def test_format_validation_errors_is_actionable(self) -> None:
        try:
            L.validate_benchmark(MALFORMED_CASE)
            assert False, "expected ValidationError"
        except L.ValidationError as exc:
            text = L.format_validation_errors(exc)
            assert "validation failed" in text
            # Mentions the file and the missing field.
            assert "bad_case" in text or "id" in text


# --- Helpers ----------------------------------------------------------------


def _valid_manifest_dict(*, bid: str = "loader-valid") -> dict[str, Any]:
    return {
        "schema_version": "1",
        "id": bid,
        "name": "Test benchmark",
        "description": "A test benchmark.",
        "domain": "recreation",
        "task_type": "text",
        "metric": {"verifier": "exact_match", "params": {"case_sensitive": False}},
        "version": "0.1.0",
        "contributor": {"name": "AI-bench contributors", "contact": "https://example.org"},
        "license": "MIT",
        "case_glob": "cases/*.yaml",
        "tags": ["recreation"],
        "status": "experimental",
    }


def _valid_case_dict(*, cid: str = "case-1") -> dict[str, Any]:
    return {
        "schema_version": "1",
        "id": cid,
        "input": "A description.",
        "expected": "label",
        "tags": ["smoke"],
        "difficulty": "easy",
        "provenance": {"source": "original", "license": "MIT"},
    }


def _make_benchmark_dir(
    tmp_path: Path,
    *,
    manifest_overrides: dict[str, Any] | None = None,
    with_cases: bool = True,
) -> Path:
    """Create a minimal valid benchmark dir under tmp_path.

    When ``with_cases`` is True (default), a ``cases/`` directory with one
    valid case is created. When False, no cases directory is created (used by
    tests that need an empty or custom cases layout).

    ``manifest_overrides`` keys override or remove (value ``None``) fields in
    the base valid manifest.
    """
    bdir = tmp_path / "bm"
    bdir.mkdir()
    manifest = _valid_manifest_dict()
    if manifest_overrides:
        for k, v in manifest_overrides.items():
            if v is None:
                manifest.pop(k, None)
            else:
                manifest[k] = v
    (bdir / "benchmark.yaml").write_text(_yaml(manifest), encoding="utf-8")
    if with_cases:
        cases_dir = bdir / "cases"
        cases_dir.mkdir()
        (cases_dir / "case_1.yaml").write_text(_yaml(_valid_case_dict()), encoding="utf-8")
    return bdir


def _make_repo_with_benchmarks(tmp_path: Path) -> Path:
    """Create a fake repo root with two real benchmarks and a _template dir."""
    root = tmp_path
    bdir = root / "benchmarks"
    bdir.mkdir()
    for bid, sub in (("real-a", "a"), ("real-b", "b")):
        d = bdir / sub
        d.mkdir()
        (d / "benchmark.yaml").write_text(
            _yaml(_valid_manifest_dict(bid=bid)), encoding="utf-8"
        )
        (d / "cases").mkdir()
        (d / "cases" / "c.yaml").write_text(
            _yaml(_valid_case_dict(cid=f"{bid}-c1")), encoding="utf-8"
        )
    # Template directory that must be excluded.
    tmpl = bdir / "_template"
    tmpl.mkdir()
    (tmpl / "benchmark.yaml").write_text(
        _yaml(_valid_manifest_dict(bid="_template")), encoding="utf-8"
    )
    (tmpl / "cases").mkdir()
    (tmpl / "cases" / "c.yaml").write_text(
        _yaml(_valid_case_dict(cid="tmpl-c1")), encoding="utf-8"
    )
    return root


def _yaml(obj: Any) -> str:
    import yaml as _yaml_mod

    return _yaml_mod.safe_dump(obj, sort_keys=False)
