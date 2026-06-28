"""Repository-wide benchmark conformance tests (chunk C11).

These are the v1 integration-gate conformance tests. They validate every real
benchmark manifest and case against the JSON Schemas via the C03 loader,
excluding ``benchmarks/_template/**`` (template validation is owned by C10).
They also include mutation-style assertions that corrupt a manifest fixture
and confirm validation fails, so the suite proves the gate can break.

Conformance here is schema/loader conformance: a benchmark "conforms" when its
manifest and all cases validate, its cases resolve safely inside its directory,
and its smoke subset is non-empty. Scoring behavior is exercised in
``tests/test_smoke.py``.

The C05 process-exit contract is respected: ``ai-bench validate`` exits 0 on a
healthy repo and non-zero on a broken one, and these tests assert that
distinction rather than treating validation as a soft warning.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from ai_bench import cli
from ai_bench import loader as L

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = REPO_ROOT / "schemas"


# --- Parametrized conformance over every real benchmark ---------------------


def _real_benchmark_paths() -> list[Path]:
    """Discovered real benchmark dirs, excluding ``benchmarks/_template/**``.

    Computed at collection time so parametrization covers exactly the set the
    release validate-all gate would cover. Sorted by id for stable ids.
    """
    manifests = L.discover_benchmarks(REPO_ROOT)
    dirs = [m.dir for m in manifests]
    dirs.sort(key=lambda p: p.name)
    return dirs


def _benchmark_id(path: Path) -> str:
    return path.name


@pytest.mark.parametrize(
    "benchmark_dir",
    _real_benchmark_paths(),
    ids=[_benchmark_id(p) for p in _real_benchmark_paths()],
)
def test_benchmark_manifest_and_cases_validate(benchmark_dir: Path) -> None:
    """Every real benchmark's manifest and all cases validate against schemas."""
    manifest = L.validate_benchmark(benchmark_dir)
    cases = L.load_cases(manifest)
    assert cases, f"benchmark {manifest.id} has no cases"
    # Every benchmark must declare at least one smoke-tagged case so the
    # C05 ``--tag smoke`` selector has a non-empty subset (C11 smoke gate).
    smoke_ids = [c["id"] for _, c in cases if "smoke" in list(c.get("tags", []))]
    assert smoke_ids, f"benchmark {manifest.id} has no smoke-tagged cases"


@pytest.mark.parametrize(
    "benchmark_dir",
    _real_benchmark_paths(),
    ids=[_benchmark_id(p) for p in _real_benchmark_paths()],
)
def test_benchmark_cli_validate_one_exits_zero(benchmark_dir: Path) -> None:
    """``ai-bench validate <benchmark>`` exits 0 for every real benchmark."""
    assert cli.main(["validate", str(benchmark_dir)]) == 0


@pytest.mark.parametrize(
    "benchmark_dir",
    _real_benchmark_paths(),
    ids=[_benchmark_id(p) for p in _real_benchmark_paths()],
)
def test_benchmark_case_glob_confined_to_benchmark_dir(benchmark_dir: Path) -> None:
    """Case files resolve inside the benchmark directory (C03 path safety)."""
    manifest = L.load_benchmark(benchmark_dir)
    cases = L.load_cases(manifest)
    bench_root = benchmark_dir.resolve()
    for case_path, _case in cases:
        resolved = case_path.resolve()
        assert bench_root in resolved.parents or resolved == bench_root, (
            f"case {case_path} escapes benchmark dir {benchmark_dir}"
        )


# --- Release validate-all gate ---------------------------------------------


class TestValidateAllGate:
    def test_validate_all_passes_on_real_repo(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The no-arg release validate-all gate passes on the real repo.

        It validates only real registered benchmarks (excluding
        ``benchmarks/_template/**``) and is expected to PASS on a healthy repo.
        """
        monkeypatch.chdir(REPO_ROOT)
        rc = cli.main(["validate"])
        out = capsys.readouterr().out
        assert rc == 0
        # Reference benchmarks appear; the template never does.
        assert "description-label" in out
        assert "git-tooling" in out
        assert "_template" not in out

    def test_validate_all_excludes_template(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The template benchmark id never appears in release validate-all."""
        monkeypatch.chdir(REPO_ROOT)
        rc = cli.main(["validate"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "_template" not in out
        assert "my-benchmark" not in out  # template manifest id


# --- Mutation-style failure coverage ---------------------------------------


class TestMutationValidationFailure:
    """Corrupt a manifest/case fixture and confirm validation fails closed.

    These prove the conformance gate can break: a mutated benchmark must fail
    schema/loader validation with a non-zero exit, not silently pass. Uses a
    temp copy so the real benchmark tree is never mutated.
    """

    def test_corrupted_manifest_fails_validate_one(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        src = REPO_ROOT / "benchmarks" / "description-label"
        dest = tmp_path / "description-label"
        shutil.copytree(src, dest)
        manifest_path = dest / "benchmark.yaml"
        # Remove a required field (id) to break the benchmark schema.
        text = manifest_path.read_text(encoding="utf-8")
        assert "id:" in text
        mutated = text.replace("id: description-label", "id: \n", 1)
        manifest_path.write_text(mutated, encoding="utf-8")

        rc = cli.main(["validate", str(dest)])
        captured = capsys.readouterr()
        assert rc != 0
        # A validation failure must surface an actionable message.
        assert captured.err or captured.out

    def test_corrupted_manifest_fails_validate_all(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A repo with one healthy and one broken benchmark fails validate-all."""
        # Healthy benchmark copy.
        src = REPO_ROOT / "benchmarks" / "description-label"
        healthy = tmp_path / "benchmarks" / "description-label"
        healthy.parent.mkdir(parents=True)
        shutil.copytree(src, healthy)
        # Broken benchmark with an invalid manifest.
        broken = tmp_path / "benchmarks" / "broken"
        broken.mkdir()
        (broken / "benchmark.yaml").write_text(
            "schema_version: '1'\nid: broken\n", encoding="utf-8"
        )

        monkeypatch.chdir(tmp_path)
        rc = cli.main(["validate"])
        captured = capsys.readouterr()
        assert rc != 0
        combined = captured.out + captured.err
        assert "broken" in combined
        assert "fail" in combined.lower()

    def test_corrupted_case_fails_validate_one(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A case missing a required field fails benchmark validation."""
        src = REPO_ROOT / "benchmarks" / "description-label"
        dest = tmp_path / "description-label"
        shutil.copytree(src, dest)
        cases_dir = dest / "cases"
        a_case = next(cases_dir.glob("*.yaml"))
        text = a_case.read_text(encoding="utf-8")
        # Remove the required ``id`` field to break the case schema.
        import yaml as _yaml

        data = _yaml.safe_load(text)
        assert "id" in data, "fixture case must have an id to mutate"
        del data["id"]
        a_case.write_text(_yaml.safe_dump(data), encoding="utf-8")

        rc = cli.main(["validate", str(dest)])
        assert rc != 0

    def test_template_is_not_validated_by_conformance(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Conformance discovery excludes ``benchmarks/_template/**``.

        The template is validated separately by C10 tests; the release
        validate-all gate must not list or validate it.
        """
        monkeypatch.chdir(REPO_ROOT)
        rc = cli.main(["validate"])
        out = capsys.readouterr().out
        assert rc == 0
        # The template directory name and its manifest id must be absent.
        assert "_template" not in out
        assert "my-benchmark" not in out
