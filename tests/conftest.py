"""Shared pytest fixtures for the ai-bench test suite (chunk C11).

Provides repo-root discovery and a parametrized list of every real benchmark
directory (excluding ``benchmarks/_template/**``) so conformance and smoke
suites iterate over the same discovered set without re-implementing discovery.

These fixtures are intentionally thin: they reuse the C03 loader discovery and
C10 registry that already exclude the contribution template, so the C11
suite-wide gate stays aligned with the release validate-all command.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ai_bench import loader as L
from ai_bench import registry as REG

# Repository root: tests/conftest.py -> <repo>
REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """Absolute path to the repository root."""
    return REPO_ROOT


@pytest.fixture(scope="session")
def real_benchmark_dirs() -> list[Path]:
    """Every real benchmark directory, excluding ``benchmarks/_template/**``.

    Discovery reuses ``loader.discover_benchmarks`` (the same path used by the
    no-argument ``ai-bench validate`` release gate), so the conformance and
    smoke suites can never pick up the contribution template. Sorted by
    benchmark id for deterministic parametrization.
    """
    manifests = L.discover_benchmarks(REPO_ROOT)
    dirs = [m.dir for m in manifests]
    dirs.sort(key=lambda p: p.name)
    return dirs


@pytest.fixture(scope="session")
def real_benchmark_ids() -> list[str]:
    """Benchmark ids for every real benchmark, excluding the template."""
    entries = REG.build_registry(REPO_ROOT)
    return [e.id for e in entries]
