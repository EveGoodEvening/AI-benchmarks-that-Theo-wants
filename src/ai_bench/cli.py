"""CLI entry point for the ``ai-bench`` command.

The ``ai-bench validate`` subcommand (both the ``<benchmark>`` and no-argument
validate-all forms) is implemented in C03.  The ``ai-bench run`` subcommand is
implemented in C05: it loads a benchmark, selects cases, evaluates via the
stub/text-file/replay adapter paths, scores with the C04 verifiers, and writes
a schema-valid run-record.  The ``failures save``, ``retry``, and
``hard-set export`` subcommands are implemented in C09: they preserve failed
cases into a versioned failure store, replay stored failures, and export
curated failures as a runnable benchmark subset.

C03 validate behavior:
  * ``ai-bench validate <benchmark>`` loads a benchmark directory, validates
    its manifest and all cases against the JSON Schemas, and reports
    actionable per-file/per-field errors. Schema-and-loader validation gate
    only; no smoke run and no template/registry/contribution workflow.
  * ``ai-bench validate`` (no argument) is the release validate-all gate.
    Run at the repository root, it auto-discovers every registered benchmark
    via ``discover_benchmarks(root)`` (excluding ``benchmarks/_template/**``)
    and validates each against the JSON Schemas, reporting a per-benchmark
    pass/fail summary and an overall exit code. It validates only real
    benchmarks and is expected to PASS on a healthy repo; malformed-fixture
    rejection is tested separately via ``tests/test_validate_cli.py``.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from ai_bench import __version__
from ai_bench import failures as F
from ai_bench import loader as L
from ai_bench import runner as R


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-bench",
        description=(
            "A small, credible benchmark suite and contribution path for "
            "community-created AI benchmarks."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(
        dest="command",
        metavar="<command>",
        help="Benchmark suite command (see `ai-bench <command> --help`).",
    )

    # validate: implemented in C03 (loader + validator + discovery).
    validate = subparsers.add_parser(
        "validate",
        help="Validate benchmark definitions against the v1 schemas.",
        description=(
            "Validate benchmark manifests and cases against the v1 JSON "
            "Schemas. With a <benchmark> path, validate that single "
            "benchmark directory. With no argument, auto-discover and "
            "validate every registered benchmark under benchmarks/ "
            "(excluding benchmarks/_template/**)."
        ),
    )
    validate.add_argument(
        "benchmark",
        nargs="?",
        default=None,
        help=(
            "Path to a benchmark directory to validate. If omitted, "
            "validate all discovered benchmarks (release validate-all gate)."
        ),
    )

    # run: implemented in C05 (runner + adapters + run-records).
    run = subparsers.add_parser(
        "run",
        help="Run a benchmark and write a schema-valid run-record.",
        description=(
            "Run selected benchmark cases, score them with the C04 verifier, "
            "and write a C02 schema-valid run-record. Exit 0 means evaluation, "
            "scoring, and run-record writing succeeded, even when case "
            "verdicts fail."
        ),
    )
    run.add_argument("benchmark", help="Path to the benchmark directory to run.")
    run.add_argument(
        "--model",
        default="stub",
        help="Model/adapter id. C05 supports 'stub' unless using --predictions/--replay.",
    )
    run.add_argument("--tag", default=None, help="Only run cases carrying this tag, e.g. smoke.")
    run.add_argument("--seed", default=0, help="Seed pinned into the run-record.")
    run.add_argument(
        "--output",
        "-o",
        default=None,
        help="Run-record JSON output path (default: run-records/<run-id>.json).",
    )
    offline = run.add_mutually_exclusive_group()
    offline.add_argument(
        "--predictions",
        default=None,
        help="Directory of per-case text prediction files (<case-id>.txt).",
    )
    offline.add_argument(
        "--predictions-file",
        default=None,
        help="JSON/JSONL mapping case ids to text predictions.",
    )
    offline.add_argument(
        "--replay",
        default=None,
        help="Directory of per-case tool-action transcripts for tool-task replay.",
    )

    # failures: implemented in C09 (failure preservation + retry + hard-set).
    failures = subparsers.add_parser(
        "failures",
        help="Preserve and inspect benchmark failure cases.",
        description=(
            "Preserve failed benchmark cases into a versioned failure store "
            "conforming to schemas/failure-store.schema.json. Subcommand "
            "'save' extracts failed cases from a C05 run-record."
        ),
    )
    failures_sub = failures.add_subparsers(
        dest="failures_action",
        metavar="<action>",
        help="Failure-store action (see `ai-bench failures <action> --help`).",
    )
    failures_save = failures_sub.add_parser(
        "save",
        help="Preserve failed cases from a run-record into a failure store.",
        description=(
            "Extract cases with failed verifier verdicts from a schema-valid "
            "C05 run-record and create or update a versioned failure store. "
            "Provide --benchmark to load per-case task input from disk for "
            "full reproducibility."
        ),
    )
    failures_save.add_argument(
        "run_record",
        help="Path to a schema-valid run-record JSON produced by `ai-bench run`.",
    )
    failures_save.add_argument(
        "--store",
        required=True,
        help="Path to the failure-store JSON to create or update.",
    )
    failures_save.add_argument(
        "--benchmark",
        default=None,
        help=(
            "Path to the benchmark directory used to load per-case task input. "
            "Recommended for full reproducibility."
        ),
    )

    # retry: implemented in C09 (replay stored failures).
    retry = subparsers.add_parser(
        "retry",
        help="Replay stored failures and report improved/regressed/unchanged.",
        description=(
            "Re-run a benchmark whose failures were preserved in a failure "
            "store and classify each stored failure as improved, regressed, or "
            "unchanged based on verifier verdicts."
        ),
    )
    retry.add_argument("store", help="Path to the failure-store JSON to retry.")
    retry.add_argument(
        "--benchmark",
        required=True,
        help="Path to the benchmark directory to re-run.",
    )
    retry.add_argument(
        "--output",
        "-o",
        default=None,
        help="Run-record JSON output path for the retry run.",
    )
    retry.add_argument(
        "--model",
        default="stub",
        help="Model/adapter id for the retry run (default: stub).",
    )
    retry.add_argument("--seed", default=0, help="Seed pinned into the retry run-record.")
    retry_offline = retry.add_mutually_exclusive_group()
    retry_offline.add_argument(
        "--predictions",
        default=None,
        help="Directory of per-case text prediction files for the retry run.",
    )
    retry_offline.add_argument(
        "--predictions-file",
        default=None,
        help="JSON/JSONL mapping case ids to text predictions for the retry run.",
    )
    retry_offline.add_argument(
        "--replay",
        default=None,
        help="Directory of per-case tool-action transcripts for the retry run.",
    )

    # hard-set: implemented in C09 (export curated failures as a benchmark subset).
    hard_set = subparsers.add_parser(
        "hard-set",
        help="Turn curated failures into a runnable benchmark subset.",
        description=(
            "Export a curated failure store as a runnable benchmark subset. "
            "The exported benchmark preserves provenance back to the original "
            "failure cases."
        ),
    )
    hard_set_sub = hard_set.add_subparsers(
        dest="hard_set_action",
        metavar="<action>",
        help="Hard-set action (see `ai-bench hard-set <action> --help`).",
    )
    hard_set_export = hard_set_sub.add_parser(
        "export",
        help="Export a failure store as a runnable benchmark directory.",
        description=(
            "Write a runnable benchmark directory (manifest + cases) derived "
            "from a preserved failure store. Provide --benchmark to inherit "
            "the source benchmark's metric, prompt template, and sampling "
            "config so the subset is directly runnable via `ai-bench run`."
        ),
    )
    hard_set_export.add_argument("store", help="Path to the failure-store JSON to export.")
    hard_set_export.add_argument(
        "--output",
        "-o",
        required=True,
        help="Output directory for the exported benchmark subset.",
    )
    hard_set_export.add_argument(
        "--benchmark",
        default=None,
        help=(
            "Path to the source benchmark directory to inherit metric/prompt/"
            "sampling config from. Recommended for a directly runnable subset."
        ),
    )
    return parser


def _repo_root_for_discovery() -> Path:
    """Return the repository root used for no-argument validate-all.

    Defaults to the current working directory. The release validate-all gate
    is run at the repository root by convention; this keeps the command
    location-independent while still discovering under ``<cwd>/benchmarks``.
    """
    return Path.cwd().resolve()


def _cmd_validate(benchmark: str | None) -> int:
    """Implement ``ai-bench validate [<benchmark>]``.

    Returns a process exit code: 0 on success, non-zero on any validation or
    load failure.
    """
    if benchmark is not None:
        return _cmd_validate_one(Path(benchmark))
    return _cmd_validate_all()


def _cmd_validate_one(benchmark_dir: Path) -> int:
    """Validate a single benchmark directory.

    Loads the manifest and all cases in one pass each, so validation work is
    not duplicated. ``validate_benchmark`` is the public gate used elsewhere;
    here we expand the steps to produce a per-benchmark summary.
    """
    try:
        manifest = L.load_benchmark(benchmark_dir)
    except L.ValidationError as exc:
        print(f"ai-bench: validation failed for {benchmark_dir}:", file=sys.stderr)
        print(L.format_validation_errors(exc), file=sys.stderr)
        return 1
    except L.LoadError as exc:
        print(f"ai-bench: could not load {benchmark_dir}: {exc}", file=sys.stderr)
        return 1

    try:
        cases = L.load_cases(manifest)
    except L.ValidationError as exc:
        print(f"ai-bench: validation failed for {benchmark_dir}:", file=sys.stderr)
        print(L.format_validation_errors(exc), file=sys.stderr)
        return 1
    except L.LoadError as exc:
        print(f"ai-bench: could not load cases for {benchmark_dir}: {exc}", file=sys.stderr)
        return 1

    n_cases = len(cases)
    smoke = sum(
        1 for _, case in cases if L._SMOKE_TAG in list(case.get("tags", []))
    )
    print(
        f"OK: benchmark {manifest.id!r} ({manifest.dir}) "
        f"status={manifest.status} cases={n_cases} smoke={smoke}"
    )
    return 0


def _cmd_validate_all() -> int:
    """Validate all discovered benchmarks (release validate-all gate).

    A repository with zero registered benchmarks is healthy: before C06/C08
    create real benchmarks there is nothing to validate, so the release
    validate-all gate exits 0 with a clear message rather than failing.
    Malformed-fixture rejection is exercised only via the explicit
    ``ai-bench validate <benchmark>`` form, whose non-zero exit behavior is
    unchanged.
    """
    root = _repo_root_for_discovery()
    benchmarks_root = root / "benchmarks"

    try:
        manifests = L.discover_benchmarks(root)
    except L.ValidationError as exc:
        print("ai-bench: benchmark discovery failed:", file=sys.stderr)
        print(L.format_validation_errors(exc), file=sys.stderr)
        return 1
    except L.LoadError as exc:
        print(f"ai-bench: benchmark discovery failed: {exc}", file=sys.stderr)
        return 1

    if not manifests:
        if benchmarks_root.is_dir():
            print(f"ai-bench: no benchmarks discovered under {benchmarks_root}")
        else:
            print(
                f"ai-bench: no benchmarks/ directory found under {root} "
                "(zero registered benchmarks; nothing to validate)"
            )
        return 0

    results: list[tuple[str, bool, str]] = []
    overall_ok = True
    for manifest in manifests:
        try:
            cases = L.load_cases(manifest)
        except (L.ValidationError, L.LoadError) as exc:
            overall_ok = False
            msg = (
                L.format_validation_errors(exc)
                if isinstance(exc, L.ValidationError)
                else str(exc)
            )
            results.append((manifest.id, False, msg))
            continue
        smoke = sum(
            1 for _, case in cases if L._SMOKE_TAG in list(case.get("tags", []))
        )
        results.append(
            (manifest.id, True, f"cases={len(cases)} smoke={smoke}")
        )

    width = max((len(bid) for bid, _, _ in results), default=0)
    for bid, ok, msg in results:
        status = "OK  " if ok else "FAIL"
        print(f"{status} {bid:<{width}}  {msg}")

    if overall_ok:
        print(f"\nAll {len(results)} benchmark(s) valid.")
        return 0
    failed = sum(1 for _, ok, _ in results if not ok)
    print(f"\n{failed}/{len(results)} benchmark(s) failed.", file=sys.stderr)
    return 1


def _cmd_run(args: argparse.Namespace) -> int:
    """Implement ``ai-bench run`` with C05 process-exit semantics."""
    try:
        result = R.run_benchmark(
            args.benchmark,
            tag=args.tag,
            model=args.model,
            seed=args.seed,
            output=args.output,
            predictions=args.predictions,
            predictions_file=args.predictions_file,
            replay=args.replay,
        )
    except R.RunnerError as exc:
        print(f"ai-bench: run failed: {exc}", file=sys.stderr)
        return 1

    aggregate = result.record["aggregate"]
    print(
        "OK: run "
        f"{result.record['run_id']} benchmark={result.record['benchmark']['id']} "
        f"cases={aggregate['n_cases']} pass={aggregate.get('n_pass', 0)} "
        f"fail={aggregate.get('n_fail', 0)} record={result.path}"
    )
    return 0

def _cmd_failures_save(args: argparse.Namespace) -> int:
    """Implement ``ai-bench failures save <run-record> --store <failure-store>``."""
    try:
        store = F.save_failures(
            args.run_record,
            args.store,
            benchmark_dir=args.benchmark,
        )
    except F.FailureStoreError as exc:
        print(f"ai-bench: failures save failed: {exc}", file=sys.stderr)
        return 1

    n = len(store.failures)
    print(
        f"OK: failures save store={args.store} failures={n} "
        f"benchmark={store.benchmark_id or '<mixed>'}"
    )
    return 0


def _cmd_retry(args: argparse.Namespace) -> int:
    """Implement ``ai-bench retry <failure-store> --benchmark <dir>``."""
    try:
        outcomes = F.retry_failures(
            args.store,
            args.benchmark,
            output=args.output,
            model=args.model,
            seed=args.seed,
            predictions=args.predictions,
            predictions_file=args.predictions_file,
            replay=args.replay,
        )
    except F.FailureStoreError as exc:
        print(f"ai-bench: retry failed: {exc}", file=sys.stderr)
        return 1

    counts = {"improved": 0, "regressed": 0, "unchanged": 0}
    for outcome in outcomes:
        counts[outcome.classification] = counts.get(outcome.classification, 0) + 1
        print(
            f"  {outcome.case_id}: {outcome.classification} "
            f"(stored={outcome.stored_verdict} new={outcome.new_verdict})"
        )
    print(
        f"OK: retry store={args.store} benchmark={args.benchmark} "
        f"cases={len(outcomes)} improved={counts['improved']} "
        f"regressed={counts['regressed']} unchanged={counts['unchanged']}"
    )
    return 0


def _cmd_hard_set_export(args: argparse.Namespace) -> int:
    """Implement ``ai-bench hard-set export <failure-store> --output <dir>``."""
    try:
        exported = F.export_hard_set(
            args.store,
            args.output,
            benchmark_dir=args.benchmark,
        )
    except F.FailureStoreError as exc:
        print(f"ai-bench: hard-set export failed: {exc}", file=sys.stderr)
        return 1

    print(f"OK: hard-set export output={exported}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        # No subcommand given: print help and exit with a non-zero status so
        # scripts can distinguish "asked for help" from a successful command.
        parser.print_help()
        return 1

    if args.command == "validate":
        return _cmd_validate(args.benchmark)
    if args.command == "run":
        return _cmd_run(args)
    if args.command == "failures":
        if args.failures_action == "save":
            return _cmd_failures_save(args)
        print(
            "ai-bench: 'failures' requires an action (save). See `ai-bench failures --help`.",
            file=sys.stderr,
        )
        return 2
    if args.command == "retry":
        return _cmd_retry(args)
    if args.command == "hard-set":
        if args.hard_set_action == "export":
            return _cmd_hard_set_export(args)
        print(
            "ai-bench: 'hard-set' requires an action (export). See `ai-bench hard-set --help`.",
            file=sys.stderr,
        )
        return 2

    print(f"ai-bench: unknown command {args.command!r}.", file=sys.stderr)
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
