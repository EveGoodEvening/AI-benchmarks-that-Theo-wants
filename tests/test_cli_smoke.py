"""Smoke test for the CLI surface.

Verifies the CLI contract across chunks:
  * the package imports and exposes a version (C01),
  * the CLI exposes a ``--help`` path and a ``--version`` path (C01),
  * placeholder subcommands report "not implemented yet" and exit non-zero
    (only ``failures`` remains a placeholder, owned by C09; ``validate`` is
    implemented in C03 and ``run`` in C05).
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
    # validate is implemented in C03; run is implemented in C05 (requires a
    # benchmark argument, so it no longer reports "not implemented yet").
    # failures remains a placeholder stub owned by C09.
    for name in ("failures",):
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
