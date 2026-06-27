"""Validate CLI tests for chunk C03.

Covers both validate command forms delivered by C03:
  * ``ai-bench validate <benchmark>``: per-benchmark schema/loader gate.
  * ``ai-bench validate`` (no argument): release validate-all gate that
    auto-discovers every registered benchmark under ``benchmarks/`` (excluding
    ``benchmarks/_template/**``) and is expected to PASS on a healthy repo.

Release behavior is separated from negative fixture testing: the repo-root
no-argument command validates only real benchmarks and passes on a healthy
repo; invalid-fixture failure is tested via the explicit ``<benchmark>``
form scoped to the malformed fixture path, NOT via the release validate-all
against a tree containing malformed fixtures.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ai_bench import cli

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "loader"
VALID = FIXTURES / "valid_benchmark"
MALFORMED_MANIFEST = FIXTURES / "malformed_manifest"
MALFORMED_CASE = FIXTURES / "malformed_case"
TOOL_TASK = FIXTURES / "tool_task_benchmark"


# --- validate <benchmark> ---------------------------------------------------


class TestValidateOne:
    def test_valid_benchmark_exits_zero(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = cli.main(["validate", str(VALID)])
        out = capsys.readouterr().out
        assert rc == 0
        assert "OK" in out
        assert "loader-valid" in out
        # Reports case count and smoke subset size.
        assert "cases=" in out
        assert "smoke=" in out

    def test_tool_task_benchmark_exits_zero(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = cli.main(["validate", str(TOOL_TASK)])
        out = capsys.readouterr().out
        assert rc == 0
        assert "loader-tool-task" in out

    def test_malformed_manifest_exits_nonzero_with_actionable_error(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = cli.main(["validate", str(MALFORMED_MANIFEST)])
        err = capsys.readouterr().err
        assert rc != 0
        assert "validation failed" in err
        # Actionable: mentions the benchmark path and a schema failure.
        assert "malformed_manifest" in err

    def test_malformed_case_exits_nonzero_with_actionable_error(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = cli.main(["validate", str(MALFORMED_CASE)])
        err = capsys.readouterr().err
        assert rc != 0
        assert "validation failed" in err
        # Actionable: points at the case file / missing id field.
        assert "id" in err or "bad_case" in err

    def test_nonexistent_benchmark_exits_nonzero(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = cli.main(["validate", str(FIXTURES / "does_not_exist")])
        err = capsys.readouterr().err
        assert rc != 0
        assert "could not load" in err or "not found" in err

    def test_validate_help_lists_benchmark_argument(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit) as exc:
            cli.main(["validate", "--help"])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "benchmark" in out
        assert "validate" in out


# --- validate (no argument) -------------------------------------------------


class TestValidateAll:
    def test_validate_all_passes_on_healthy_repo(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = _make_healthy_repo(tmp_path)
        monkeypatch.chdir(root)
        rc = cli.main(["validate"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "All" in out
        assert "valid" in out.lower()
        # _template is excluded from discovery output.
        assert "_template" not in out

    def test_validate_all_reports_per_benchmark_summary(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = _make_healthy_repo(tmp_path)
        monkeypatch.chdir(root)
        rc = cli.main(["validate"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "real-a" in out
        assert "real-b" in out
        assert "OK" in out

    def test_validate_all_no_benchmarks_dir_exits_zero(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # A repo with zero registered benchmarks is healthy: before C06/C08
        # create real benchmarks there is nothing to validate, so the release
        # validate-all gate exits 0 with a clear message rather than failing.
        monkeypatch.chdir(tmp_path)
        rc = cli.main(["validate"])
        captured = capsys.readouterr()
        assert rc == 0
        assert "no benchmarks" in captured.out
        assert "nothing to validate" in captured.out

    def test_validate_all_empty_benchmarks_dir_exits_zero(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        (tmp_path / "benchmarks").mkdir()
        monkeypatch.chdir(tmp_path)
        rc = cli.main(["validate"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "no benchmarks discovered" in out

    def test_validate_all_excludes_template(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = _make_healthy_repo(tmp_path)
        monkeypatch.chdir(root)
        rc = cli.main(["validate"])
        out = capsys.readouterr().out
        assert rc == 0
        # The template benchmark id must never appear in release output.
        assert "_template" not in out
        assert "tmpl" not in out

    def test_validate_all_fails_when_a_real_benchmark_is_broken(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # A healthy repo plus one broken real benchmark: the release gate
        # fails because discovery must load each manifest to check unique
        # ids, so a malformed manifest surfaces as a discovery/validation
        # failure with a non-zero exit.
        root = _make_healthy_repo(tmp_path)
        broken = root / "benchmarks" / "broken"
        broken.mkdir()
        (broken / "benchmark.yaml").write_text(
            "schema_version: '1'\nid: broken\n", encoding="utf-8"
        )
        monkeypatch.chdir(root)
        rc = cli.main(["validate"])
        captured = capsys.readouterr()
        out, err = captured.out, captured.err
        assert rc != 0
        # The broken benchmark is reported either in the per-benchmark
        # summary (out) or as a discovery failure (err).
        combined = out + err
        assert "broken" in combined
        assert "fail" in combined.lower()


# --- Subprocess end-to-end (console script) ---------------------------------


class TestValidateCliSubprocess:
    def test_validate_valid_fixture_via_subprocess(self) -> None:
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-m", "ai_bench.cli", "validate", str(VALID)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "loader-valid" in result.stdout

    def test_validate_malformed_manifest_via_subprocess(self) -> None:
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-m", "ai_bench.cli", "validate", str(MALFORMED_MANIFEST)],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert "validation failed" in result.stderr


# --- Helpers ----------------------------------------------------------------


def _valid_manifest_dict(*, bid: str = "loader-valid") -> dict[str, object]:
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


def _valid_case_dict(*, cid: str = "case-1") -> dict[str, object]:
    return {
        "schema_version": "1",
        "id": cid,
        "input": "A description.",
        "expected": "label",
        "tags": ["smoke"],
        "difficulty": "easy",
        "provenance": {"source": "original", "license": "MIT"},
    }


def _make_healthy_repo(tmp_path: Path) -> Path:
    """A repo root with two real benchmarks and a _template dir (excluded)."""
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


def _yaml(obj: object) -> str:
    import yaml as _yaml_mod

    return _yaml_mod.safe_dump(obj, sort_keys=False)  # type: ignore[arg-type]
