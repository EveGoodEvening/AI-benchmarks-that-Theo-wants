"""ai-bench: a small, credible benchmark suite and contribution path for community-created AI benchmarks.

This package is intentionally minimal at the skeleton stage (C01). Later
chunks add schemas, the loader/validator, the scoring/verifier engine, the
runner with model/agent adapters, reference benchmarks, the hermetic sandbox,
the failure store, and the contribution scaffold. This module only exposes
the package version so the CLI entry point and downstream modules can import
it without pulling in unimplemented behavior.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
