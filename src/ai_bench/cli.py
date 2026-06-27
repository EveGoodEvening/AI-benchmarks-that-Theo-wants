"""Minimal CLI entry point for the ``ai-bench`` command.

This is the C01 skeleton: it provides a working ``ai-bench --help`` path and a
placeholder subcommand surface so later chunks can register real subcommands
(``validate`` in C03, ``run`` in C05, ``failures`` in C09) without renaming
the entry point or restructuring the parser.

No benchmark behavior is implemented here. Subcommands declared below are
intentionally no-op stubs that print an explicit "not implemented yet"
message and exit with a non-zero status, so the help surface is stable for
later chunks while never claiming functionality that does not exist.
"""
from __future__ import annotations

from ai_bench import __version__

import argparse
import sys
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

    # Placeholder subcommands. Real implementations land in later chunks:
    #   validate -> C03 (loader + validator + discovery)
    #   run      -> C05 (runner + model/agent adapters + run-records)
    #   failures -> C09 (failure-case preservation + retry + hard-set)
    # They are declared now only so the CLI surface is stable; they do not
    # claim later functionality exists.
    for name, help_text in (
        ("validate", "Validate benchmark definitions (planned, not implemented yet)."),
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        # No subcommand given: print help and exit with a non-zero status so
        # scripts can distinguish "asked for help" from a successful command.
        parser.print_help()
        return 1

    # All declared subcommands are placeholders in C01.
    print(
        f"ai-bench: '{args.command}' is not implemented yet.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
