"""CLI entry point for the ``ai-bench`` command.

The ``ai-bench validate`` subcommand (both the ``<benchmark>`` and no-argument
validate-all forms) is implemented in C03. The ``run`` and ``failures``
subcommands remain placeholder stubs owned by later chunks (C05 and C09
respectively); they are declared so the CLI surface stays stable.

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

from ai_bench import __version__
from ai_bench import loader as L

import argparse
import sys
from pathlib import Path
from typing import Sequence


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

    # Placeholder subcommands owned by later chunks:
    #   run      -> C05 (runner + model/agent adapters + run-records)
    #   failures -> C09 (failure-case preservation + retry + hard-set)
    # They are declared now only so the CLI surface is stable; they do not
    # claim later functionality exists.
    for name, help_text in (
        ("run", "Run a benchmark and record results (planned, not implemented yet)."),
        ("failures", "Preserve and retry failure cases (planned, not implemented yet)."),
    ):
        sub = subparsers.add_parser(name, help=help_text)
        # Keep argument surface minimal; later chunks own their own arguments.
        sub.add_argument(
            "--not-implemented",
            action="store_true",
            help=argparse.SUPPRESS,
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

    # run / failures remain placeholder stubs owned by later chunks.
    print(
        f"ai-bench: '{args.command}' is not implemented yet.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
