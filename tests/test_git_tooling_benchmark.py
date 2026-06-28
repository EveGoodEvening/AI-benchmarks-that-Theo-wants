"""Benchmark-specific tests for the git-tooling reference benchmark (C08).

These tests exercise the checked-in ``benchmarks/git-tooling`` benchmark
directly: schema/loader validation, the smoke subset selector, the stub run
path, and the non-stub ``--replay`` path that scores real tool-action
transcripts through the real state_check verifier (C07.2). Acceptance is based
on schema-valid run-records and correct benchmark wiring, not on every
stub/sample verdict passing (per the C05 exit contract).
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
from ai_bench import cli
from ai_bench import loader as L
from ai_bench import runner as R

# Repository root: tests/test_git_tooling_benchmark.py -> <repo>
_REPO_ROOT = Path(__file__).resolve().parents[1]
_BENCHMARK_DIR = _REPO_ROOT / "benchmarks" / "git-tooling"

# The four smoke-tagged cases that make up the selectable smoke subset.
_SMOKE_IDS = {"init-repo", "create-branch", "stage-and-commit", "dirty-no-commit"}


def _load_cases() -> list[tuple[Path, dict]]:
    manifest = L.load_benchmark(_BENCHMARK_DIR)
    return L.load_cases(manifest)


def _validate_run_record(record: dict) -> None:
    schema = json.loads((_REPO_ROOT / "schemas" / "run-record.schema.json").read_text())
    jsonschema.Draft202012Validator(schema).validate(record)


def test_benchmark_validates_against_schemas() -> None:
    """Manifest and all cases validate via the C03 loader/schema gate."""
    manifest = L.load_benchmark(_BENCHMARK_DIR)
    cases = L.load_cases(manifest)
    assert manifest.id == "git-tooling"
    assert manifest.data["task_type"] == "tool-task"
    assert manifest.data["metric"]["verifier"] == "state_check"
    assert "tool-use" in list(manifest.tags)
    assert "git" in list(manifest.tags)
    assert manifest.data["status"] == "experimental"
    # 20-50 original cases per the C08 deliverable.
    assert 20 <= len(cases) <= 50


def test_cases_carry_provenance_and_license() -> None:
    """Every case carries provenance with source original and a license (C02 case schema)."""
    for _path, case in _load_cases():
        prov = case.get("provenance") or {}
        assert prov.get("source") == "original", case["id"]
        assert prov.get("license"), case["id"]


def test_cases_use_state_check_verifier() -> None:
    """Every case uses the per-case state_check verifier with a non-empty block."""
    for _path, case in _load_cases():
        verifier = case.get("verifier") or {}
        assert verifier.get("verifier") == "state_check", case["id"]
        state_check = case.get("state_check") or {}
        assert state_check, case["id"]
        # state_check must not rely on a sha256 content hash (state, not bytes).
        assert "sha256" not in state_check, case["id"]


def test_review_fix_cases_have_observable_state_targets() -> None:
    """C08 review fixes stay locked to state-check-observable outcomes."""
    cases = {case["id"]: case for _path, case in _load_cases()}

    revert_steps = [
        step.get("argv")
        for step in cases["revert-commit"]["input"]["script"]
        if step.get("command") == "git"
    ]
    assert ["commit", "-m", "add notes"] in revert_steps
    assert ["revert", "-n", "HEAD"] in revert_steps
    assert ["revert", "HEAD", "-m", "revert add notes"] not in revert_steps

    assert cases["checkout-orphan"]["state_check"]["git"]["current_branch"] == "orphan"
    assert cases["create-tag"]["state_check"]["git"]["tags"] == ["v1.0"]
    assert cases["switch-back"]["state_check"]["git"]["current_branch"] == "main"

    clean = cases["clean-untracked"]
    assert clean["input"]["fixture"] == "fixtures/clean-untracked"
    assert (_BENCHMARK_DIR / clean["input"]["fixture"] / "build.tmp").is_file()
    assert clean["state_check"]["absent"] == ["build.tmp"]

    assert (
        cases["restore-staged"]["state_check"]["files"]["README.md"]["contains"]
        == "changed"
    )
    assert cases["stash-pop"]["state_check"]["files"]["README.md"]["contains"] == "wip"
    assert cases["reset-soft"]["state_check"]["files"]["notes.md"]["contains"] == "reset"


def test_branch_sensitive_cases_lock_current_branch() -> None:
    """The five branch-sensitive cases assert an explicit final current_branch.

    create-branch ends on ``feature``; the other four (branch-list, cherry-pick,
    merge-fast-forward, merge-no-ff) switch back to / stay on ``main``. Each
    case's ``state_check.git.current_branch`` is locked, and the matching
    checked-in sample transcript's ``final_repo_state.current_branch`` agrees
    with the case expectation, so the real-verifier transcript-replay path
    scores them against the asserted branch rather than ignoring it.
    """
    cases = {case["id"]: case for _path, case in _load_cases()}
    expected = {
        "create-branch": "feature",
        "branch-list": "main",
        "cherry-pick": "main",
        "merge-fast-forward": "main",
        "merge-no-ff": "main",
    }
    for case_id, branch in expected.items():
        case = cases[case_id]
        git = case["state_check"]["git"]
        assert "current_branch" in git, case_id
        assert git["current_branch"] == branch, case_id
        # The asserted branch must be present in the branches list.
        assert branch in git["branches"], case_id

    transcripts = _BENCHMARK_DIR / "sample_transcripts"
    for case_id, branch in expected.items():
        transcript_path = transcripts / f"{case_id}.json"
        assert transcript_path.is_file(), case_id
        record = json.loads(transcript_path.read_text())
        assert record["case_id"] == case_id, case_id
        state = record["final_repo_state"]
        assert "current_branch" in state, case_id
        assert state["current_branch"] == branch, case_id
        # Transcript branch list must contain the asserted current branch.
        assert branch in state["branches"], case_id


def test_smoke_subset_is_non_empty_and_selectable() -> None:
    """The four smoke-tagged cases exist and --tag smoke selects only them."""
    cases = _load_cases()
    smoke_ids = [c["id"] for _, c in cases if "smoke" in list(c.get("tags", []))]
    assert set(smoke_ids) == _SMOKE_IDS

    output = _REPO_ROOT / "build" / "c08-smoke-record.json"
    output.parent.mkdir(exist_ok=True)
    try:
        result = R.run_benchmark(
            _BENCHMARK_DIR,
            tag="smoke",
            model="stub",
            output=output,
        )
    finally:
        # Keep the repo tree clean; the run-record is verification evidence,
        # not a checked-in artifact.
        if output.is_file():
            output.unlink()

    assert result.record["tag_filter"] == "smoke"
    assert result.record["aggregate"]["n_cases"] == len(smoke_ids)
    # Only smoke-tagged case ids appear in the run-record.
    assert {c["case_id"] for c in result.record["cases"]} == set(smoke_ids)


def test_stub_run_writes_schema_valid_record(tmp_path: Path) -> None:
    """Stub run exits 0 (no exception) and writes a schema-valid run-record.

    Stub runs use the real sandbox dispatcher and real state_check verifier,
    so some stub verdicts may fail; those are evaluation data, not a command
    failure (C05 exit contract).
    """
    output = tmp_path / "stub-record.json"
    result = R.run_benchmark(_BENCHMARK_DIR, model="stub", output=output)
    assert output.is_file()
    _validate_run_record(result.record)
    assert result.record["aggregate"]["n_cases"] == len(_load_cases())


def test_non_stub_replay_scores_real_transcripts(tmp_path: Path) -> None:
    """The checked-in sample_transcripts are scored by the real state_check verifier.

    The run-record records the replay source as the model id, is schema-valid,
    covers all 24 cases, and records the intended 23 pass / 1 fail accounting:
    only the deliberate ``dirty-no-commit`` miss fails, proving the
    real-verifier transcript-replay acceptance path.
    """
    transcripts = _BENCHMARK_DIR / "sample_transcripts"
    assert transcripts.is_dir(), "sample_transcripts directory must be checked in"

    output = tmp_path / "replay-record.json"
    result = R.run_benchmark(
        _BENCHMARK_DIR,
        replay=transcripts,
        output=output,
    )
    assert output.is_file()
    _validate_run_record(result.record)

    assert result.record["model"]["adapter"] == "replay"
    assert result.record["model"]["id"].startswith("replay:")
    aggregate = result.record["aggregate"]
    assert aggregate["n_cases"] == 24
    assert aggregate["n_pass"] == 23
    assert aggregate["n_fail"] == 1
    verdicts = {c["case_id"]: c["verdict"] for c in result.record["cases"]}
    assert verdicts["dirty-no-commit"] == "fail"


def test_smoke_replay_verdicts_match_readme(tmp_path: Path) -> None:
    """The smoke subset replayed through the real verifier matches the README claim.

    The README states only ``dirty-no-commit`` is an intentional smoke failure.
    Under the real transcript-replay path (not the stub fake snapshot), the
    three other smoke cases pass and ``dirty-no-commit`` fails because its
    working tree is left dirty (``status_clean: true`` is violated), not
    because a file is missing.
    """
    transcripts = _BENCHMARK_DIR / "sample_transcripts"
    output = tmp_path / "smoke-replay-record.json"
    result = R.run_benchmark(
        _BENCHMARK_DIR,
        tag="smoke",
        replay=transcripts,
        output=output,
    )
    aggregate = result.record["aggregate"]
    assert aggregate["n_cases"] == len(_SMOKE_IDS)
    assert aggregate["n_pass"] == 3
    assert aggregate["n_fail"] == 1
    assert aggregate["value"] == pytest.approx(0.75)
    verdicts = {c["case_id"]: c["verdict"] for c in result.record["cases"]}
    # Only dirty-no-commit is the intentional smoke failure.
    assert verdicts["init-repo"] == "pass"
    assert verdicts["create-branch"] == "pass"
    assert verdicts["stage-and-commit"] == "pass"
    assert verdicts["dirty-no-commit"] == "fail"
    # dirty-no-commit fails due to dirty status, not a missing file: notes.md
    # is present in the file_tree but the working tree is not clean.
    dirty = next(c for c in result.record["cases"] if c["case_id"] == "dirty-no-commit")
    state = dirty.get("final_repo_state") or {}
    assert "notes.md" in state.get("file_tree", [])
    assert state.get("git_status", "").strip() != ""

def test_cli_validate_one_exits_zero() -> None:
    """``ai-bench validate benchmarks/git-tooling`` exits 0."""
    assert cli.main(["validate", str(_BENCHMARK_DIR)]) == 0


def test_cli_run_replay_exits_zero(tmp_path: Path) -> None:
    """``ai-bench run --replay`` exits 0 per the C05 exit contract."""
    output = tmp_path / "cli-replay-record.json"
    rc = cli.main(
        [
            "run",
            str(_BENCHMARK_DIR),
            "--replay",
            str(_BENCHMARK_DIR / "sample_transcripts"),
            "--output",
            str(output),
        ]
    )
    assert rc == 0
    assert output.is_file()
