"""Test package for the ai-bench suite.

C01 only needs a valid, importable test layout so ``uv run pytest -q`` can
collect a smoke test. Later chunks add their own test modules
(``test_schema.py``, ``test_loader.py``, ``test_scoring.py``, ``test_runner.py``,
``test_sandbox*.py``, ``test_failures.py``, ``test_conformance.py``).
"""
