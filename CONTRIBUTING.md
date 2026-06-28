# Contributing a benchmark to `ai-bench`

`ai-bench` is a community-driven benchmark suite. Anyone can contribute a
benchmark. This guide covers the contribution workflow, provenance and
licensing expectations, status semantics, and the review process.

## TL;DR

```sh
# 1. Copy the template to a new benchmark directory.
cp -r benchmarks/_template benchmarks/<your-benchmark-id>

# 2. Edit benchmark.yaml, cases/*.yaml, and README.md.

# 3. Validate your benchmark (no model or API key needed).
uv run ai-bench validate benchmarks/<your-benchmark-id>

# 4. Run a smoke subset with the stub adapter.
uv run ai-bench run benchmarks/<your-benchmark-id> --tag smoke --model stub

# 5. Validate the whole suite (excludes the template).
uv run ai-bench validate
```

A contribution is a directory under `benchmarks/<your-benchmark-id>/`
containing a `benchmark.yaml` manifest, a `cases/` directory of case files,
and a `README.md`. The `ai-bench validate <benchmark>` command is the one
validation gate — it loads the manifest and all cases and validates them
against the v1 JSON Schemas (`schemas/benchmark.schema.json` and
`schemas/case.schema.json`). No new validate command is added for
contributions; the existing C03 command is reused.

## The template

`benchmarks/_template/**` is the contribution template. It is **excluded from
discovery, the registry, and the release validate-all gate** — it is never
listed or validated as a real benchmark. It is validated separately by
`tests/test_template.py`. Copy it to `benchmarks/<your-benchmark-id>/` to
start.

The template ships:

- `benchmark.yaml` — a manifest stub populating `tags` and
  `status: experimental`, with comments explaining every field.
- `cases/sample-case.yaml` — one sample case including a `smoke`-tagged case.
- `README.md` — replace with a benchmark-specific README.

## Manifest fields

Every manifest is validated against `schemas/benchmark.schema.json`. The
required fields are:

- `schema_version` — must be `"1"` for v1.
- `id` — stable, unique benchmark slug (lowercase, digits, hyphens). Must be
  unique across the suite and should match your directory name.
- `name` — human-readable benchmark name.
- `description` — short description of what the benchmark measures.
- `domain` — domain label, e.g. `recreation`, `tool-use`, `spatial-reasoning`,
  `medical-imaging`.
- `task_type` — `text` (model replies with text) or `tool-task` (agent emits
  structured tool actions inside a hermetic sandbox).
- `metric` — verifier/scorer config. v1 supports `exact_match`,
  `contains_any`, `regex_match`, `set_f1`, `state_check`, `llm_judge`. If you
  use `llm_judge` you must also pin an `llm_judge` block.
- `version` — manifest/fixture version (semver-ish). Bump when cases or
  expected values change.
- `contributor` — authorship/provenance metadata (`name` required; `contact`
  and `url` optional).
- `license` — SPDX identifier or `proprietary`. Reference benchmarks use
  `CC0-1.0`.
- `case_glob` — glob (relative to the benchmark directory) selecting case
  files. Resolved safely by the loader; case files cannot escape the benchmark
  directory.

Optional fields: `tags` (benchmark-level tags), `status` (`experimental` or
`stable`), `prompt_template`, `sampling`, `llm_judge`. See
`schemas/benchmark.schema.json` for the authoritative definitions.

## Case files

Each case is a YAML file under `cases/` matching `case_glob`. Cases are
validated against `schemas/case.schema.json`. Required fields: `schema_version`
(`"1"`), `id` (unique within the benchmark), and `input`. Most cases also set
`expected` (the value the verifier checks against the model reply or final
repository state).

Every benchmark must ship at least one case tagged `smoke` so the smoke subset
(selected with `--tag smoke`) is non-empty. The `smoke` tag is reserved at the
case level for this purpose.

## Provenance and originality

- **Original fixtures only.** Every case, fixture, and expected value must be
  written from scratch for this suite. Do not import or reproduce another
  benchmark's cases, prompts, or expected values without explicit permission
  and a clear citation in `provenance.source`.
- **Cite inspirations, not imports.** If your benchmark is inspired by the
  *shape* of an existing benchmark (e.g. Theo's SkateBench or GitBench), say
  so in the README and manifest `description`, and make clear that your
  benchmark is original and not an import. Use `provenance.source: "original"`
  for fixtures you wrote from scratch.
- **No endorsement claims.** Do not claim endorsement from any person or
  project. Theo has no involvement with or endorsement of this project.

## Licensing

- Use a permissive SPDX identifier. Reference benchmarks use `CC0-1.0` so the
  fixtures are maximally reusable. `MIT` and `Apache-2.0` are also acceptable.
- `proprietary` is permitted but the benchmark will not be eligible for the
  release validate-all gate or the public registry index until it is
  re-licensed under an SPDX identifier.
- Set `license` at the benchmark level (manifest) and per-case
  (`provenance.license`). They should agree.

## Status: `experimental` vs `stable`

The `status` field (frozen by C02) signals maturity:

- `experimental` — the default for new contributions. The fixture set may
  still change; cases may be added, removed, or revised. The suite maintainers
  have not yet frozen the benchmark.
- `stable` — the fixture set has been reviewed and frozen by the suite
  maintainers. Case ids, expected values, and the prompt template are not
  expected to change except via a `version` bump and a documented migration.

New contributions should set `status: experimental`. The maintainers promote a
benchmark to `stable` after review (see Review expectations below).

## Review expectations

A contribution is reviewed by the suite maintainers before it is merged. The
review checks:

1. **Validation.** `ai-bench validate <benchmark>` exits 0 with actionable
   errors fixed. `ai-bench validate` (no-arg) still passes for the whole suite.
2. **Originality and provenance.** Cases are original fixtures or carry a
   clear, permission-backed citation. No endorsement claims.
3. **Licensing.** Benchmark and case licenses agree and use an SPDX identifier
   (or `proprietary` if intentional).
4. **Smoke subset.** At least one case is tagged `smoke` and the smoke subset
   is non-empty.
5. **Reproducibility.** The benchmark runs with the stub adapter
   (`--model stub`) and, where applicable, ships a non-stub offline path
   (`--predictions` or `--replay` samples) so the suite can be scored
   end-to-end without a live model or API key.
6. **README.** A benchmark-specific README describes what the benchmark
   measures, its verifier, its smoke subset, and its limitations.

The review does **not** promise legal review of your fixtures or licensing, and
it does **not** imply endorsement from Theo or any other party. The
maintainers may request changes to the manifest, cases, or README before merge.

## The registry

Registered benchmarks are auto-discovered by `ai-bench registry`, which lists
each benchmark's `id`, `domain`, `tags`, `contributor`, `license`, `status`,
and `version` sourced directly from the manifest (never inferred). Discovery
excludes `benchmarks/_template/**`. The registry is derived on demand from
manifests so it can never drift from the source of truth; there is no
checked-in index file to keep in sync.

```sh
uv run ai-bench registry            # human-readable table
uv run ai-bench registry --json     # JSON-serializable index array
```

Duplicate benchmark ids are rejected at discovery time. If two benchmark
directories declare the same `id`, `ai-bench validate` and
`ai-bench registry` both fail with a clear, actionable error naming both
directories.

## Verification commands

```sh
# Validate your benchmark alone.
uv run ai-bench validate benchmarks/<your-benchmark-id>

# Validate every registered benchmark (excludes the template).
uv run ai-bench validate

# List the registry (excludes the template).
uv run ai-bench registry

# Run a smoke subset with the stub adapter.
uv run ai-bench run benchmarks/<your-benchmark-id> --tag smoke --model stub

# Run the template/registry tests.
uv run pytest tests/test_template.py tests/test_registry.py -q
```

No command in this guide requires live model credentials or network access.
The stub adapter and the offline `--predictions`/`--replay` paths exist so the
suite can be developed and verified without a provider API key.
