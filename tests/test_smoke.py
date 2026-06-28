"""Repository-wide smoke tests for every real benchmark (chunk C11).

These are the v1 integration-gate smoke tests. For every real benchmark
(excluding ``benchmarks/_template/**``) they exercise:

  * the durable ``--tag smoke`` selector from C05 via a stub model run, proving
    each benchmark has a non-empty ``smoke``-tagged subset that produces a
    schema-valid run-record (failed verdicts are evaluation data, not command
    failures, per the C05 exit contract);
  * the non-stub offline scoring paths required in CI:
      - ``--predictions`` for the text benchmark (``description-label``),
      - ``--replay`` for the tool-task benchmark (``git-tooling``),
    so CI proves real outputs/transcripts are scored by the real verifiers,
    not only deterministic stubs;
  * the C05 process-exit contract: a scored failed-verdict sample exits 0 with
    a schema-valid run-record, and a deliberately invalid run input exits
    non-zero.

No live API keys, network, or host mutation are required. Run-records produced
here are written to ``tmp_path`` and validated against
``schemas/run-record.schema.json``.
"""

from __future__ import annotations

import json

from pathlib import Path

import jsonschema
import pytest

from ai_bench import cli
from ai_bench import loader as L
from ai_bench import runner as R

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = REPO_ROOT / "schemas"


def _real_benchmark_paths() -> list[Path]:
    """Discovered real benchmark dirs, excluding ``benchmarks/_template/**``."""
    manifests = L.discover_benchmarks(REPO_ROOT)
    dirs = [m.dir for m in manifests]
    dirs.sort(key=lambda p: p.name)
    return dirs


def _benchmark_id(path: Path) -> str:
    return path.name


def _validate_run_record(record: dict) -> None:
    """Validate a run-record dict against the C02 run-record schema."""
    schema = json.loads((SCHEMAS_DIR / "run-record.schema.json").read_text())
    jsonschema.Draft202012Validator(schema).validate(record)


# --- Stub smoke run for every real benchmark -------------------------------


@pytest.mark.parametrize(
    "benchmark_dir",
    _real_benchmark_paths(),
    ids=[_benchmark_id(p) for p in _real_benchmark_paths()],
)
def test_stub_smoke_run_exits_zero_with_schema_valid_record(
    benchmark_dir: Path,
    tmp_path: Path,
) -> None:
    """``ai-bench run <benchmark> --tag smoke --model stub`` exits 0.

    The smoke subset must be non-empty and produce a schema-valid run-record.
    Failed case verdicts from the stub are evaluation data, not command
    failures (C05 exit contract).
    """
    output = tmp_path / "smoke-record.json"
    rc = cli.main(
        [
            "run",
            str(benchmark_dir),
            "--tag",
            "smoke",
            "--model",
            "stub",
            "--output",
            str(output),
        ]
    )
    assert rc == 0
    assert output.is_file()
    record = json.loads(output.read_text(encoding="utf-8"))
    _validate_run_record(record)
    assert record["tag_filter"] == "smoke"
    aggregate = record["aggregate"]
    assert aggregate["n_cases"] >= 1, "smoke subset must be non-empty"


@pytest.mark.parametrize(
    "benchmark_dir",
    _real_benchmark_paths(),
    ids=[_benchmark_id(p) for p in _real_benchmark_paths()],
)
def test_stub_smoke_subset_matches_tagged_cases(
    benchmark_dir: Path,
    tmp_path: Path,
) -> None:
    """The smoke run covers exactly the ``smoke``-tagged cases."""
    manifest = L.load_benchmark(benchmark_dir)
    cases = L.load_cases(manifest)
    smoke_ids = {c["id"] for _, c in cases if "smoke" in list(c.get("tags", []))}
    assert smoke_ids, f"benchmark {manifest.id} has no smoke-tagged cases"

    output = tmp_path / "smoke-subset-record.json"
    result = R.run_benchmark(
        benchmark_dir, tag="smoke", model="stub", output=output
    )
    assert {c["case_id"] for c in result.record["cases"]} == smoke_ids


# --- Non-stub offline scoring paths (required in CI) -----------------------


class TestNonStubOfflineScoring:
    """CI must exercise the non-stub offline scoring paths, not only stubs."""

    def test_description_label_predictions_scores_real_outputs(
        self,
        tmp_path: Path,
    ) -> None:
        """``--predictions`` scores checked-in real text predictions.

        Uses the real C04 text verifiers (not a stub), writes a schema-valid
        run-record, and requires no API key/network. The model id records the
        file prediction source.
        """
        bench = REPO_ROOT / "benchmarks" / "description-label"
        preds = bench / "sample_predictions"
        assert preds.is_dir(), "sample_predictions must be checked in"

        output = tmp_path / "pred-record.json"
        rc = cli.main(
            ["run", str(bench), "--predictions", str(preds), "--output", str(output)]
        )
        assert rc == 0
        assert output.is_file()
        record = json.loads(output.read_text(encoding="utf-8"))
        _validate_run_record(record)
        assert record["model"]["adapter"] == "file"
        assert record["model"]["id"].startswith("file:")
        assert record["aggregate"]["n_cases"] >= 1

    def test_git_tooling_replay_scores_real_transcripts(
        self,
        tmp_path: Path,
    ) -> None:
        """``--replay`` scores checked-in real agent transcripts.

        Uses the real state-check verifier from C07.2 (not a stub), writes a
        schema-valid run-record, and requires no API key/network/host
        mutation. The model id records the replay source.
        """
        bench = REPO_ROOT / "benchmarks" / "git-tooling"
        transcripts = bench / "sample_transcripts"
        assert transcripts.is_dir(), "sample_transcripts must be checked in"

        output = tmp_path / "replay-record.json"
        rc = cli.main(
            ["run", str(bench), "--replay", str(transcripts), "--output", str(output)]
        )
        assert rc == 0
        assert output.is_file()
        record = json.loads(output.read_text(encoding="utf-8"))
        _validate_run_record(record)
        assert record["model"]["adapter"] == "replay"
        assert record["model"]["id"].startswith("replay:")
        assert record["aggregate"]["n_cases"] >= 1


# --- C05 exit-contract assertions ------------------------------------------


class TestExitContract:
    """CI/test assertions relying on C05 exit semantics.

    A scored failed-verdict sample exits 0 with a schema-valid run-record; a
    deliberately invalid run input exits non-zero. This distinction is what
    the C11/CI gate relies on instead of treating a low score as a broken
    command.
    """

    def test_stub_smoke_failed_verdicts_exit_zero(
        self,
        tmp_path: Path,
    ) -> None:
        """A stub smoke run with failed verdicts still exits 0.

        The stub model is expected to fail most description-label verdicts;
        those failures are evaluation data, not a process failure.
        """
        bench = REPO_ROOT / "benchmarks" / "description-label"
        output = tmp_path / "stub-fail-record.json"
        rc = cli.main(
            ["run", str(bench), "--tag", "smoke", "--model", "stub", "--output", str(output)]
        )
        assert rc == 0
        assert output.is_file()
        record = json.loads(output.read_text(encoding="utf-8"))
        _validate_run_record(record)
        # The stub is expected to produce at least one failed verdict; that
        # must not turn the command into a failure.
        assert record["aggregate"]["n_cases"] >= 1

    def test_invalid_run_input_exits_non_zero(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A non-existent benchmark directory exits non-zero.

        This is a validation/load failure (not a scored verdict), so it must
        fail the process per the C05 exit contract.
        """
        missing = tmp_path / "does-not-exist"
        rc = cli.main(["run", str(missing), "--model", "stub"])
        assert rc != 0
        err = capsys.readouterr().err
        assert err

    def test_replay_on_text_benchmark_exits_non_zero(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """``--replay`` on a text benchmark is a misuse and exits non-zero.

        ``--replay`` is only valid for tool-task benchmarks; using it on a
        text benchmark is a runner configuration error, not a scored verdict.
        """
        bench = REPO_ROOT / "benchmarks" / "description-label"
        rc = cli.main(
            ["run", str(bench), "--replay", str(tmp_path), "--output", str(tmp_path / "x.json")]
        )
        assert rc != 0

    def test_predictions_on_tool_benchmark_exits_non_zero(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """``--predictions`` on a tool-task benchmark is a misuse and exits non-zero."""
        bench = REPO_ROOT / "benchmarks" / "git-tooling"
        rc = cli.main(
            ["run", str(bench), "--predictions", str(tmp_path), "--output", str(tmp_path / "x.json")]
        )
        assert rc != 0


# --- Subprocess end-to-end smoke (console script) -------------------------


class TestSmokeSubprocess:
    """End-to-end smoke via the installed console script, mirroring CI steps."""

    def test_validate_all_via_subprocess(self) -> None:
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-m", "ai_bench.cli", "validate"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert "description-label" in result.stdout
        assert "git-tooling" in result.stdout
        assert "_template" not in result.stdout

    def test_stub_smoke_description_label_via_subprocess(
        self, tmp_path: Path
    ) -> None:
        import subprocess
        import sys

        output = tmp_path / "subprocess-smoke.json"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "ai_bench.cli",
                "run",
                str(REPO_ROOT / "benchmarks" / "description-label"),
                "--tag",
                "smoke",
                "--model",
                "stub",
                "--output",
                str(output),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert output.is_file()
