"""Registry tests for chunk C10.

These tests exercise the auto-discovered benchmark registry delivered by C10:

  * ``build_registry(root)`` discovers real benchmarks under
    ``<root>/benchmarks`` and excludes ``benchmarks/_template/**``.
  * The registry lists the reference benchmarks (``description-label`` and
    ``git-tooling``) with metadata sourced from their manifests; additional
    valid community benchmarks are permitted without test edits.
  * Registry fields (``id``, ``domain``, ``tags``, ``contributor``,
    ``license``, ``status``, ``version``) are read from the manifest, never
    inferred.
  * Duplicate benchmark ids are rejected (reuses C03 discovery's unique-id
    check).
  * ``ai-bench registry`` CLI prints a human-readable table; ``--json`` emits
    a JSON-serializable index array.
  * The registry is sorted by benchmark id for deterministic output.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_bench import cli
from ai_bench import loader as L
from ai_bench import registry as REG

REPO_ROOT = Path(__file__).resolve().parents[1]


# --- build_registry against the real repo -----------------------------------


class TestBuildRegistry:
    def test_lists_reference_benchmarks(self) -> None:
        entries = REG.build_registry(REPO_ROOT)
        ids = [e.id for e in entries]
        assert ids == sorted(ids), "registry must be sorted by id"
        # Reference benchmarks must be present; additional valid benchmarks
        # are allowed so future community contributions don't break this test.
        assert "description-label" in ids
        assert "git-tooling" in ids
        assert "_template" not in ids

    def test_excludes_template(self) -> None:
        entries = REG.build_registry(REPO_ROOT)
        ids = {e.id for e in entries}
        assert "my-benchmark" not in ids

    def test_sources_metadata_from_manifests(self) -> None:
        entries = {e.id: e for e in REG.build_registry(REPO_ROOT)}

        desc = entries["description-label"]
        assert desc.domain == "recreation"
        assert desc.status == "experimental"
        assert desc.version == "0.1.0"
        assert desc.license == "CC0-1.0"
        assert desc.contributor == "AI-bench contributors"
        assert "recreation" in desc.tags
        assert "spatial-reasoning" in desc.tags

        git = entries["git-tooling"]
        assert git.domain == "tool-use"
        assert git.status == "experimental"
        assert git.version == "0.1.0"
        assert git.license == "CC0-1.0"
        assert "tool-use" in git.tags
        assert "git" in git.tags

    def test_entries_are_json_serializable(self) -> None:
        entries = REG.build_registry(REPO_ROOT)
        index = [e.to_dict() for e in entries]
        # Must round-trip through json.dumps without error.
        text = json.dumps(index, sort_keys=True)
        parsed = json.loads(text)
        assert isinstance(parsed, list)
        assert {"description-label", "git-tooling"}.issubset(
            {row["id"] for row in parsed}
        )

    def test_registry_index_returns_dicts(self) -> None:
        index = REG.registry_index(REPO_ROOT)
        assert isinstance(index, list)
        assert all(isinstance(row, dict) for row in index)
        assert {"description-label", "git-tooling"}.issubset(
            {row["id"] for row in index}
        )

    def test_dir_field_points_at_benchmark_directory(self) -> None:
        entries = {e.id: e for e in REG.build_registry(REPO_ROOT)}
        assert Path(entries["description-label"].dir).is_dir()
        assert Path(entries["git-tooling"].dir).is_dir()


# --- Duplicate id rejection -------------------------------------------------


class TestDuplicateIds:
    def test_duplicate_benchmark_ids_rejected(self, tmp_path: Path) -> None:
        # Two real benchmarks with the same id must fail discovery (and thus
        # registry build), reusing the C03 unique-id check.
        root = tmp_path
        bdir = root / "benchmarks"
        bdir.mkdir()
        for sub in ("a", "b"):
            d = bdir / sub
            d.mkdir()
            (d / "benchmark.yaml").write_text(
                _valid_manifest_yaml(bid="dup-id"),
                encoding="utf-8",
            )
            (d / "cases").mkdir()
            (d / "cases" / "c.yaml").write_text(
                _valid_case_yaml(cid=f"{sub}-c1"),
                encoding="utf-8",
            )

        with pytest.raises(L.ValidationError) as excinfo:
            REG.build_registry(root)
        details = L.format_validation_errors(excinfo.value)
        assert "duplicate benchmark id" in details


# --- CLI --------------------------------------------------------------------


class TestRegistryCli:
    def test_registry_table_lists_reference_benchmarks(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.chdir(REPO_ROOT)
        rc = cli.main(["registry"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "description-label" in out
        assert "git-tooling" in out
        assert "_template" not in out
        assert "my-benchmark" not in out
        # Table header is present.
        assert "id" in out
        assert "domain" in out
        assert "status" in out

    def test_registry_json_lists_reference_benchmarks(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.chdir(REPO_ROOT)
        rc = cli.main(["registry", "--json"])
        out = capsys.readouterr().out
        assert rc == 0
        parsed = json.loads(out)
        assert isinstance(parsed, list)
        ids = {row["id"] for row in parsed}
        # Reference benchmarks must be present; additional benchmarks allowed.
        assert {"description-label", "git-tooling"}.issubset(ids)
        assert "_template" not in ids
        # JSON entries carry the sourced metadata fields.
        desc = next(row for row in parsed if row["id"] == "description-label")
        assert desc["domain"] == "recreation"
        assert desc["status"] == "experimental"
        assert "spatial-reasoning" in desc["tags"]

    def test_registry_root_flag(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # --root overrides cwd-based discovery.
        root = _make_repo_with_one_benchmark(tmp_path)
        rc = cli.main(["registry", "--root", str(root)])
        out = capsys.readouterr().out
        assert rc == 0
        assert "solo-bench" in out

    def test_registry_empty_repo_exits_zero(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / "benchmarks").mkdir()
        rc = cli.main(["registry", "--root", str(tmp_path)])
        out = capsys.readouterr().out
        assert rc == 0
        assert "no registered benchmarks" in out


# --- format_registry --------------------------------------------------------


class TestFormatRegistry:
    def test_empty_registry_message(self) -> None:
        text = REG.format_registry([])
        assert "no registered benchmarks" in text

    def test_header_always_present(self) -> None:
        text = REG.format_registry([])
        assert "id" in text
        assert "domain" in text


# --- Helpers ----------------------------------------------------------------


def _valid_manifest_yaml(*, bid: str) -> str:
    import yaml as _yaml

    return _yaml.safe_dump(
        {
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
        },
        sort_keys=False,
    )


def _valid_case_yaml(*, cid: str) -> str:
    import yaml as _yaml

    return _yaml.safe_dump(
        {
            "schema_version": "1",
            "id": cid,
            "input": "A description.",
            "expected": "label",
            "tags": ["smoke"],
            "difficulty": "easy",
            "provenance": {"source": "original", "license": "MIT"},
        },
        sort_keys=False,
    )


def _make_repo_with_one_benchmark(tmp_path: Path) -> Path:
    root = tmp_path
    bdir = root / "benchmarks" / "solo"
    bdir.mkdir(parents=True)
    (bdir / "benchmark.yaml").write_text(
        _valid_manifest_yaml(bid="solo-bench"), encoding="utf-8"
    )
    (bdir / "cases").mkdir()
    (bdir / "cases" / "c.yaml").write_text(
        _valid_case_yaml(cid="solo-c1"), encoding="utf-8"
    )
    return root
