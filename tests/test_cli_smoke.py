"""Smoke test for the C01 skeleton.

This only verifies the skeleton contract that C01 owns:
  * the package imports and exposes a version,
  * the CLI exposes a ``--help`` path and a ``--version`` path,
  * placeholder subcommands report "not implemented yet" and exit non-zero.

It deliberately does not test any benchmark behavior (none exists yet).
"""

from __future__ import annotations

import subprocess
import sys

import pytest

import ai_bench
from ai_bench import cli


def test_package_exposes_version() -> None:
    assert isinstance(ai_bench.__version__, str)
    assert ai_bench.__version__  # non-empty


def test_cli_main_no_args_prints_help_and_returns_nonzero(capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli.main([])
    out = capsys.readouterr().out
    assert rc != 0
    assert "ai-bench" in out
    assert "command" in out.lower()


def test_cli_version_flag_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert ai_bench.__version__ in out


def test_cli_placeholder_subcommands_are_not_implemented(capsys: pytest.CaptureFixture[str]) -> None:
    # validate is implemented in C03; run and failures remain placeholder
    # stubs owned by later chunks (C05 and C09).
    for name in ("run", "failures"):
        rc = cli.main([name])
        err = capsys.readouterr().err
        assert rc != 0
        assert "not implemented yet" in err


def test_cli_help_subprocess_runs() -> None:
    # End-to-end: the installed console script (or module) must respond to --help.
    result = subprocess.run(
        [sys.executable, "-m", "ai_bench.cli", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "ai-bench" in result.stdout
