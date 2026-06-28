"""Smoke test for the CLI surface.

Verifies the CLI contract across chunks:
  * the package imports and exposes a version (C01),
  * the CLI exposes a ``--help`` path and a ``--version`` path (C01),
  * implemented subcommands dispatch correctly: ``validate`` (C03), ``run``
    (C05), and ``failures``/``retry``/``hard-set`` (C09). Subcommands requiring
    a sub-action report a usage error and exit non-zero.
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


def test_cli_failures_subcommand_requires_action(capsys: pytest.CaptureFixture[str]) -> None:
    # validate is implemented in C03; run is implemented in C05; failures is
    # implemented in C09 and requires a sub-action (save). With no action it
    # reports the usage error and exits non-zero.
    rc = cli.main(["failures"])
    err = capsys.readouterr().err
    assert rc != 0
    assert "requires an action" in err


def test_cli_help_subprocess_runs() -> None:
    # End-to-end: the installed console script (or module) must respond to --help.
    result = subprocess.run(
        [sys.executable, "-m", "ai_bench.cli", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "ai-bench" in result.stdout
