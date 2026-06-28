# Benchmark template

This directory is the contribution template for a new `ai-bench` benchmark.
It is **excluded from discovery, the registry, and the release validate-all
gate** — `benchmarks/_template/**` is never listed or validated as a real
benchmark. It is validated separately by `tests/test_template.py`.

## Copy it to start a benchmark

```sh
# From the repository root:
cp -r benchmarks/_template benchmarks/<your-benchmark-id>
```

Then edit:

- `benchmark.yaml` — set `id`, `name`, `description`, `domain`, `task_type`,
  `metric`, `version`, `contributor`, `license`, `tags`, and `status`. The
  `id` must be unique across the suite and must match your directory name.
- `cases/*.yaml` — add one case file per case. Each case needs a unique `id`,
  an `input`, an `expected` value, and at least one case tagged `smoke`.
- `README.md` — replace this file with a benchmark-specific README describing
  what the benchmark measures, its verifier, and its limitations.

## Validate your benchmark

```sh
# Validate just your benchmark:
uv run ai-bench validate benchmarks/<your-benchmark-id>

# Validate every registered benchmark (excludes this template):
uv run ai-bench validate
```

`ai-bench validate <benchmark>` loads the manifest and all cases and validates
them against the v1 JSON Schemas (`schemas/benchmark.schema.json` and
`schemas/case.schema.json`). It reports actionable per-file/per-field errors.
No model, API key, or smoke run is required to validate.

## Run a smoke subset

Once your benchmark validates, run its smoke subset with the stub adapter:

```sh
uv run ai-bench run benchmarks/<your-benchmark-id> --tag smoke --model stub
```

Exit 0 means the selected cases were evaluated, scored, and a schema-valid
run-record was written — it does **not** mean every case verdict passed.

## Verifier guidance

The `metric.verifier` field selects the scorer. v1 supports:

- `exact_match` — the model reply must equal `expected` (with optional
  `case_sensitive`, `trim`, `normalize_whitespace` params).
- `contains_any` — the reply must contain any of the expected substrings.
- `regex_match` — the reply must match a regex in `params.regex`.
- `set_f1` — set-F1 over token/line sets in `params`.
- `state_check` — for `tool-task` benchmarks; asserts deterministic repository
  state invariants (`git.status_clean`, `git.branches`, `files.<path>.exists`,
  etc.). See `benchmarks/git-tooling` for a complete example.
- `llm_judge` — requires a pinned `llm_judge` block in the manifest
  (`judge_model`, `judge_prompt`, `judge_params`, `judge_seed`).

See `schemas/benchmark.schema.json` and `schemas/case.schema.json` for the
authoritative field definitions, and `CONTRIBUTING.md` for the full
contribution workflow, provenance, licensing, and review expectations.
