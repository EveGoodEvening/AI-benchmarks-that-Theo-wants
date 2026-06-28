"""Template and contribution-workflow tests for chunk C10.

These tests exercise the contribution scaffold delivered by C10:

  * The template at ``benchmarks/_template/**`` is a valid benchmark: copying
    it to a temp dir and running the existing C03 ``ai-bench validate`` on the
    copy exits 0.
  * Mutating the copied manifest to violate the schema produces a clear,
    actionable validation failure (non-zero exit).
  * The template itself validates in place via ``ai-bench validate
    benchmarks/_template`` (C10 owns template validation; the release
    validate-all gate does not cover it).
  * The template ships at least one ``smoke``-tagged case.
  * The template is excluded from discovery and the release validate-all gate:
    ``ai-bench validate`` (no-arg) run at the repo root never lists
    ``_template`` or the template benchmark id, and ``discover_benchmarks``
    never returns the template manifest.
  * The template is excluded from the registry (covered in detail in
    test_registry.py, asserted here too for locality).

The existing ``ai-bench validate`` command (delivered in C03) is reused; C10
adds no new validate command.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from ai_bench import cli
from ai_bench import loader as L
from ai_bench import registry as REG

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = REPO_ROOT / "benchmarks" / "_template"


# --- Template is a valid benchmark ------------------------------------------


class TestTemplateValidates:
    def test_template_validates_in_place(self, capsys: pytest.CaptureFixture[str]) -> None:
        # C10 owns template validation. The release validate-all gate excludes
        # the template, so we validate it explicitly here.
        rc = cli.main(["validate", str(TEMPLATE_DIR)])
        out = capsys.readouterr().out
        assert rc == 0, f"template failed to validate:\n{out}"
        assert "OK" in out
        # The template manifest id is 'my-benchmark' (see benchmark.yaml).
        assert "my-benchmark" in out

    def test_template_has_one_case_and_smoke_subset(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = cli.main(["validate", str(TEMPLATE_DIR)])
        out = capsys.readouterr().out
        assert rc == 0
        # The template ships exactly one sample case, tagged smoke.
        assert "cases=1" in out
        assert "smoke=1" in out

    def test_template_loads_via_loader(self) -> None:
        manifest = L.load_benchmark(TEMPLATE_DIR)
        assert manifest.id == "my-benchmark"
        assert manifest.status == "experimental"
        cases = L.load_cases(manifest)
        assert len(cases) == 1
        case_path, case = cases[0]
        assert case["id"] == "sample-case"
        assert "smoke" in list(case.get("tags", []))

    def test_template_manifest_populates_tags_and_status(self) -> None:
        manifest = L.load_benchmark(TEMPLATE_DIR)
        # The plan requires the manifest stub to populate tags and status.
        assert manifest.tags == ["my-domain"]
        assert manifest.status == "experimental"


# --- Copy + validate workflow -----------------------------------------------


class TestCopyValidateWorkflow:
    def test_copy_template_validates_in_temp_dir(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # The one-command contributor path: copy the template, then validate.
        dest = tmp_path / "benchmarks" / "my-benchmark"
        dest.parent.mkdir(parents=True)
        shutil.copytree(TEMPLATE_DIR, dest)

        rc = cli.main(["validate", str(dest)])
        out = capsys.readouterr().out
        assert rc == 0, f"copied template failed to validate:\n{out}"
        assert "OK" in out
        assert "my-benchmark" in out

    def test_copy_template_add_case_still_validates(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # A contributor adds a second case; the benchmark still validates.
        dest = tmp_path / "benchmarks" / "my-benchmark"
        dest.parent.mkdir(parents=True)
        shutil.copytree(TEMPLATE_DIR, dest)

        (dest / "cases" / "second-case.yaml").write_text(
            """\
schema_version: "1"
id: second-case
input: |
  A second task input.
expected: "second-answer"
tags:
  - smoke
difficulty: easy
provenance:
  source: "original"
  author: "Contributor"
  license: "CC0-1.0"
""",
            encoding="utf-8",
        )

        rc = cli.main(["validate", str(dest)])
        out = capsys.readouterr().out
        assert rc == 0, out
        assert "cases=2" in out

    def test_mutated_manifest_fails_with_actionable_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Mutate the copied manifest to violate the schema and confirm a clear
        # failure. This is the plan's mutate-manifest scenario.
        dest = tmp_path / "benchmarks" / "my-benchmark"
        dest.parent.mkdir(parents=True)
        shutil.copytree(TEMPLATE_DIR, dest)

        manifest_path = dest / "benchmark.yaml"
        text = manifest_path.read_text(encoding="utf-8")
        # Remove the required `metric` block by blanking it out: replace the
        # verifier with an invalid enum value, which the schema rejects.
        mutated = text.replace("verifier: exact_match", "verifier: not-a-verifier")
        assert mutated != text, "mutation did not change the manifest text"
        manifest_path.write_text(mutated, encoding="utf-8")

        rc = cli.main(["validate", str(dest)])
        err = capsys.readouterr().err
        assert rc != 0
        assert "validation failed" in err
        # Actionable: mentions the verifier field and the bad value.
        assert "metric.verifier" in err or "not-a-verifier" in err

    def test_mutated_manifest_missing_required_field_fails(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Drop a required field entirely and confirm a clear failure.
        dest = tmp_path / "benchmarks" / "my-benchmark"
        dest.parent.mkdir(parents=True)
        shutil.copytree(TEMPLATE_DIR, dest)

        manifest_path = dest / "benchmark.yaml"
        text = manifest_path.read_text(encoding="utf-8")
        # Remove the `license` line.
        mutated = text.replace('license: CC0-1.0\n', '')
        assert mutated != text
        manifest_path.write_text(mutated, encoding="utf-8")

        rc = cli.main(["validate", str(dest)])
        err = capsys.readouterr().err
        assert rc != 0
        assert "validation failed" in err
        assert "license" in err


# --- Template exclusion from discovery and validate-all ---------------------


class TestTemplateExcluded:
    def test_discover_benchmarks_excludes_template(self) -> None:
        manifests = L.discover_benchmarks(REPO_ROOT)
        ids = {m.id for m in manifests}
        assert "my-benchmark" not in ids, "template leaked into discovery"
        # The real reference benchmarks are discovered.
        assert "description-label" in ids
        assert "git-tooling" in ids

    def test_validate_all_excludes_template(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # Run the release validate-all gate at the real repo root.
        monkeypatch.chdir(REPO_ROOT)
        rc = cli.main(["validate"])
        out = capsys.readouterr().out
        assert rc == 0
        # The template benchmark id must never appear in release output.
        assert "my-benchmark" not in out
        assert "_template" not in out
        # The real benchmarks are listed.
        assert "description-label" in out
        assert "git-tooling" in out

    def test_registry_excludes_template(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.chdir(REPO_ROOT)
        rc = cli.main(["registry"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "my-benchmark" not in out
        assert "_template" not in out
        assert "description-label" in out
        assert "git-tooling" in out

    def test_build_registry_excludes_template(self) -> None:
        entries = REG.build_registry(REPO_ROOT)
        ids = {e.id for e in entries}
        assert "my-benchmark" not in ids
        assert "description-label" in ids
        assert "git-tooling" in ids
