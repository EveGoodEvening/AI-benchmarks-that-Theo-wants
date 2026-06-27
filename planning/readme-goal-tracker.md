# README.md Goal Progress Tracker

Implementation state: C01, C02, C03, C04, and C05 implemented and verified; C06-C13 not started.

Use with: `planning/readme-goal-plan.md`

Recommended planning-artifact commit: `docs(plan): add durable README goal implementation plan`

## Tracker rules

### Checkbox states

- `[ ]` Unchecked means not complete. It may be not started, in progress, blocked, or deferred; read the chunk notes before claiming status.
- A checked checkbox means the chunk is implemented, reviewed against its criteria, and verified with the listed command(s) or explicit method. Do not check a chunk because code was merely written.
- `BLOCKED:` may be added under an unchecked item only with blocker, owner, date, and the exact missing prerequisite. `owner: TBD` and `date: TBD` are NOT acceptable for any blocker; a blocker with a TBD owner/date does not satisfy the item and must not be used to justify checking a dependent item or the final gate. The only substitute for resolved evidence is an explicit approved deferral (see `DEFERRED:`).
- `DEFERRED:` may be added under an unchecked item only with owner, date, rationale, and explicit scope approval. Deferred items must stay visible in this tracker.

### Final-gate behavior

- The README goal must not be declared complete while any active C01-C12 chunk is unchecked.
- A blocked active chunk fails the final gate unless the blocker is resolved and the chunk is checked.
- A deferred active chunk fails the final gate unless there is explicit scope approval recorded in the tracker.
- C13 is post-v1 expansion scope. It may be deferred for a v1 release only if owner/date/rationale are recorded; it must not be silently omitted from the full README roadmap.
- Before the final gate is checked, record the exact final verification commands and outcomes under `Final verification log`, including the non-stub offline scoring commands (`--predictions` and `--replay`).
- C11/final-gate CI rule (authoritative): C11 and the final gate cannot be checked until C11's remote CI evidence records a workflow run URL, the exact commit SHA, and a passing/successful outcome for that SHA, unless an explicit approved deferral with owner/date/rationale is recorded. Failed, cancelled, skipped, timed-out, or neutral outcomes do not satisfy this rule and keep C11/final gate unchecked. A `BLOCKED` note with `owner: TBD` or `date: TBD` is NOT acceptable and does not satisfy this rule. This rule applies to C11, C12's final-gate confirmation, and the `Final verification log` remote-CI entry.

### Parallel-work rules

A future session may run chunks in parallel only when they do not touch the same files, interfaces, generated artifacts, or checklist items.

- Safe only after C02: C03 and C04 may run in parallel if C02 has frozen schemas and `src/ai_bench/types.py`. C03 owns both the `ai-bench validate <benchmark>` and the no-argument `ai-bench validate` (validate-all) CLI additions in `cli.py`.
- Serial after C05: C07 must run after C05 because it plugs the sandboxed dispatcher into the agent-adapter/run-record interfaces frozen by C05/C02. C07 must not edit `src/ai_bench/models.py` or `src/ai_bench/run_records.py`. C05's `--replay` mode is plumbing only (tested against a fake/stub state-check verifier) and does NOT depend on C07; the real state-check verifier implementation lands in C07.2, which owns real-verifier transcript-replay acceptance (C05 `--replay` plumbing scored by the real verifier), exercised end-to-end with checked-in `--replay` samples in C08/C11/C12. C07 is split into ordered sub-phases C07.1 (sandbox backend + dispatcher confinement) → C07.2 (repo-state verifier integration, depends on C07.1) and C07.3 (network/env/credential/resource hardening, depends on C07.1 and may run in parallel with C07.2); C07 is not checked until C07.1, C07.2, and C07.3 are all checked. C07 may run alongside C06 only if C06 stays inside `benchmarks/description-label/**`.
- Safe only after C05+C07: C06 and C08 may run in parallel if they stay inside separate benchmark directories and benchmark-specific tests. Both depend on C03 (validate + validate-all), C05 (run + adapters + `--tag smoke` + process-exit contract), and C08 also depends on C07 (enforced sandboxed dispatch + state verifier). Their run verification treats exit 0 as successful evaluation/scoring/run-record creation, not as all case verdicts passing.
- Usually serial: C09 and C10, because both may touch CLI and registry/docs. C10 no longer delivers `ai-bench validate` (moved to C03); it adds template/registry/contribution workflow and reuses C03's validate commands.
- Serial: C01, C02, C11, C12, and C13.

### Commit hygiene

- Prefer one reviewable commit per chunk using the Conventional Commit candidate shown below.
- Do not mix unrelated chunks in one commit unless a shared-interface change makes separation impossible; if combined, explain the coupling in the commit body.
- Do not check a chunk until its verification evidence is recorded.

## Chunk checklist

### [x] C01 — Project skeleton + toolchain

- Conventional Commit candidate: `chore: add Python project skeleton and CLI entry point`
- Owned files/scope: `pyproject.toml`, `uv.lock`, `.gitignore`, `src/ai_bench/__init__.py`, `src/ai_bench/cli.py`, initial `tests/` package if needed.
- Dependencies: none.
- Parallel: none; establishes shared toolchain.
- Verification: `uv sync`; `uv run ai-bench --help`; `uv run pytest -q`.
- Review criteria: minimal Python 3.11+ uv project; no heavy ML dependency stack; stable CLI entry point; no committed caches/build output.
- Tasks:
  - [x] Create the Python/uv project files.
  - [x] Add the package and CLI entry point.
  - [x] Add minimal test layout if needed.
  - [x] Run and record verification commands.
- Verification evidence (C01): `uv sync` -> Checked 13 packages; `uv run ai-bench --help` -> usage printed, `ai-bench` entry point resolves (`validate`/`run`/`failures` subcommands present, planned); `uv run pytest -q` -> 5 passed. Python 3.11+ uv project; runtime deps limited to pyyaml + jsonschema (no heavy ML stack); `ai-bench` console script stable; `.gitignore` excludes caches/build output.

### [x] C02 — Schemas + typed contracts

- Conventional Commit candidate: `feat(schema): define benchmark, case, run-record, and failure-store contracts`
- Owned files/scope: `schemas/benchmark.schema.json`, `schemas/case.schema.json`, `schemas/run-record.schema.json`, `schemas/failure-store.schema.json`, `src/ai_bench/types.py`, `tests/test_schema.py`.
- Dependencies: C01.
- Parallel: none; freezes the full v1 shared contract surface. No C01-C12 chunk may add or extend a `schemas/*.schema.json` file. The C02 freeze is v1-scoped (C01-C12); post-v1 schema evolution is owned by C13 as a versioned migration plan with compatibility tests, not by in-flight edits to the C02 schemas.
- Verification: `uv run pytest tests/test_schema.py -q`.
- Review criteria: required identity/provenance/license fields; benchmark `tags`/`status` (experimental|stable) fields; reserved case `smoke` tag; verifier types express README scope; run-record schema includes tool-action transcript + final repo-state fields; failure-store schema includes the full reproducibility determinant set; schema and runtime types cannot drift silently; no real benchmark fixtures except test fixtures; schema freeze is explicitly v1-scoped (C01-C12) and C13 owns post-v1 schema evolution via a versioned migration plan with compatibility tests.
- Tasks:
  - [x] Define benchmark manifest schema, including benchmark-level `tags` and `status` (enum: `experimental` | `stable`, default `experimental`).
  - [x] Define case schema, including provenance, nullable expected only for failure cases, and the reserved `smoke` tag value.
  - [x] Define run-record schema with pinned reproducibility fields, plus v1 tool-action transcript fields (command, argv, cwd, env_overrides, stdin, exit_code, stdout, stderr, wall_clock_ms, timeout, sandbox_boundary_violation) and final repo-state snapshot block.
  - [x] Define failure-store schema (v1) with the full reproducibility determinant set and preserved failure-case fields.
  - [x] Add typed contracts or generated equivalents.
  - [x] Add schema acceptance/rejection tests (including `status` enum, `smoke` tag, transcript fields, failure-store determinant set).
  - [x] Run and record verification command.
- Verification evidence (C02): Verified after the latest red-test fix and orchestrator verification passed. Targeted re-run of the red tests confirmed the fix: text `RunRecord` dataclass test -> passed; `llm_judge` `RunRecord` dataclass test -> passed. `uv run pytest tests/test_schema.py -q` -> 73 passed. `uv run pytest -q` -> 78 passed (full suite, no regressions). Coverage spans acceptance/rejection across benchmark, case, run-record, and failure-store schemas + typed-contract drift guards + schema-freeze v1 pin; includes C02-review negative tests for normal-case expected/provenance/license, state_check/llm_judge conditional requirements, benchmark llm_judge pinned config, run-record raw-output/transcript/final_repo_state conditional requirements, and failure-store null-expected metadata; run-record `judge_config` acceptance/rejection, missing `task_type` rejection, and null/non-string text `observed` rejection. `schemas/benchmark.schema.json` pins `schema_version` const "1", requires identity/provenance/license fields, defines `tags` (unique string array) and `status` enum `experimental|stable` with default `experimental`, enumerates all six v1 verifier types, and conditionally requires a pinned `llm_judge` config when the metric verifier is `llm_judge`. `schemas/case.schema.json` requires `expected` (non-null) and `provenance.license` for normal cases, requires `expected_metadata.reason` when `expected` is null (preserved failure case), requires `state_check` when the per-case verifier is `state_check`, requires a pinned `llm_judge` config when the per-case verifier is `llm_judge`, and accepts the reserved `smoke` tag. `schemas/run-record.schema.json` requires `benchmark.task_type` (the raw-output preservation discriminator), requires per-case `observed` (non-null string) for text benchmark runs and per-case `transcript` + `final_repo_state` for tool-task/replay runs, conditionally requires a pinned `verifier.judge_config` (judge_model/judge_prompt/judge_params/judge_seed) when the run verifier is `llm_judge`, and requires the pinned reproducibility determinant set. `schemas/failure-store.schema.json` requires `expected_metadata.reason` whenever a failure record's `expected` is null, and requires the full reproducibility determinant set. Typed contracts in `src/ai_bench/types.py` stay aligned via drift guards (including `BenchmarkManifest.llm_judge`, the required `BenchmarkRef.task_type`, and `RunVerifier.judge_config`/`RunJudgeConfig`). All seven C02 tasks are satisfied and verified; C02 remains checked. C02 final-review fixes are in place: (1) run-record root `verifier` is required with a required `name` so llm_judge records cannot omit judge pins by omitting the verifier/name (judge_config still conditionally required for llm_judge); (2) text `observed` is required but `minLength: 0` so empty raw output validates while null/non-string observed is rejected; (3) `tool_action` requires `env_overrides`, `stdin`, `stdout`, `stderr` (defaults are not applied by JSON Schema, so the keys must be present); (4) `repo_state` requires `file_tree`, `git_status`, `branches`, `commits`, `diff` so an empty `{}` snapshot is rejected. Typed contracts mirror the schema (`RunVerifier.name` and `RunRecord.verifier` are required; `RepoState` fields are required non-optional). Tests include `test_repo_state_empty_rejected`, `test_tool_action_transcript_fields_validated` extended to the four required fields, `test_verifier_required_at_root`, `test_verifier_name_required`, `test_text_result_with_empty_observed_accepted`, `test_repo_state_missing_required_fields_rejected`; `_dataclass_to_dict` preserves explicit null for nullable (`X | None`) fields so required nullable fields like `ToolAction.stdin` serialize as JSON null.

### [x] C03 — Loader + validator + discovery + minimal validate CLI

- Conventional Commit candidate: `feat(loader): validate and discover benchmark definitions with minimal validate CLI`
- Owned files/scope: `src/ai_bench/loader.py`, CLI additions in `src/ai_bench/cli.py` for both `ai-bench validate <benchmark>` and no-argument `ai-bench validate`, `tests/fixtures/loader/**`, `tests/test_loader.py`, `tests/test_validate_cli.py`.
- Dependencies: C02.
- Parallel: may run with C04 after C02 only if it does not edit schemas, `types.py`, or scorer APIs. C03 owns the `cli.py` validate additions (both forms).
- Verification: `uv run pytest tests/test_loader.py tests/test_validate_cli.py -q`; `uv run ai-bench validate tests/fixtures/loader/valid_benchmark` succeeds; negative fixture test via `tests/test_validate_cli.py` (pytest) and/or explicit `uv run ai-bench validate tests/fixtures/loader/malformed_manifest` fails with an actionable error (NOT the repo-root no-arg command); release validate-all gate `uv run ai-bench validate` (no-arg, run at repo root) validates only real registered benchmarks excluding `benchmarks/_template/**` and is expected to PASS on a healthy repo.
- Review criteria: `yaml.safe_load` only; case globs cannot escape benchmark directory; actionable validation errors; deterministic canonical serialization; both `ai-bench validate <benchmark>` and no-arg `ai-bench validate` exist and are usable by C06/C08/C12 before C10; discovery excludes `benchmarks/_template/**`; loader validates benchmark `tags`/`status` and the reserved `smoke` tag; release behavior separated from negative fixture testing (repo-root no-arg `ai-bench validate` validates only real benchmarks and passes on a healthy repo; invalid-fixture failure tested via pytest or explicit fixture-root/cwd command, not via the release validate-all against a tree containing malformed fixtures).
- Tasks:
  - [x] Implement safe YAML/JSON loading.
  - [x] Validate manifests and cases against schemas, including benchmark `tags`/`status` and the reserved `smoke` tag.
  - [x] Implement benchmark discovery and unique-id checks, excluding `benchmarks/_template/**`.
  - [x] Implement safe case glob resolution with tag-based subset selection support.
  - [x] Add deterministic canonicalization helper.
  - [x] Add `ai-bench validate <benchmark>` CLI (schema + loader gate only; no smoke run, no template/registry).
  - [x] Add no-argument `ai-bench validate` CLI (validate all discovered benchmarks excluding `_template`, per-benchmark summary, overall exit code).
  - [x] Add validate CLI tests for both forms (valid fixture passes, malformed manifest/case fails, no-arg validates all fixtures).
  - [x] Run and record verification commands.
- Verification evidence (C03): Orchestrator verification passed. `uv run pytest tests/test_loader.py tests/test_validate_cli.py -q` -> passed. `uv run ai-bench validate tests/fixtures/loader/valid_benchmark` -> exited 0 with `OK` and `cases=2 smoke=1`. `uv run ai-bench validate tests/fixtures/loader/malformed_manifest` -> exited 1 with actionable schema errors (expected negative). `uv run ai-bench validate` (no-arg, repo root) -> exited 0 with zero registered benchmarks message. `uv run pytest -q` -> passed (full suite, no regressions). Coverage spans safe YAML/JSON loading, manifest/case schema validation including benchmark `tags`/`status` and the reserved `smoke` tag, benchmark discovery excluding `benchmarks/_template/**` with unique-id checks, safe case glob resolution with tag-based subset selection, deterministic canonicalization, both `ai-bench validate <benchmark>` and no-argument `ai-bench validate` CLI forms, and validate CLI tests for both forms (valid fixture passes, malformed manifest fails, no-arg validates all fixtures). Release behavior separated from negative fixture testing: repo-root no-arg `ai-bench validate` validates only real registered benchmarks and passes on a healthy repo (zero-registered message on a tree with no real benchmarks); invalid-fixture failure tested via explicit fixture-root command, not via the release validate-all against a tree containing malformed fixtures. All nine C03 tasks are satisfied and verified; C03 remains checked. C04 code exists but is left unchecked for a separate tracker update; C05+ remain unchecked.
- Review-fix evidence (C03): Targeted Python verification parsed the touched Python files and exercised the review regressions: discovery still finds real benchmarks when the repo path has an unrelated `_template` ancestor while excluding `benchmarks/_template/**`; validate-all discovery failure stderr includes nested `metric.verifier` schema detail; `canonical_json` preserves `"expected": null`. No gate/test/formatter/git command was run for this review-only fix.

### [x] C04 — Scoring/verifier engine

- Conventional Commit candidate: `feat(scoring): add built-in deterministic benchmark verifiers`
- Owned files/scope: `src/ai_bench/scoring.py`, `tests/fixtures/scoring/**`, `tests/test_scoring.py`.
- Dependencies: C02.
- Parallel: may run with C03 after C02 only if it consumes frozen types and avoids loader files.
- Verification: `uv run pytest tests/test_scoring.py -q`.
- Review criteria: deterministic verifier outputs; edge cases covered; LLM-judge requires pinned metadata; no arbitrary custom-code plugin in v1.
- Tasks:
  - [x] Add exact-match scorer.
  - [x] Add contains-any scorer.
  - [x] Add regex-match scorer.
  - [x] Add set-F1 scorer with edge-case handling.
  - [x] Add state-check verifier interface shape.
  - [x] Add LLM-judge contract with deterministic test double only.
  - [x] Run and record verification command.

- Verification evidence (C04): Orchestrator verification passed. `uv run pytest tests/test_scoring.py -q` -> passed. `uv run pytest -q` -> passed (full suite, no regressions). Coverage spans deterministic verifiers (exact-match, contains-any, regex-match, set-F1 with edge cases), state-check verifier interface shape, and LLM-judge contract with deterministic test double only; no arbitrary custom-code plugin in v1. All seven C04 tasks are satisfied and verified; C04 checked. C01-C03 remain checked; C05+ remain unchecked.

- Review-fix evidence (C04): Follow-up review findings addressed in `src/ai_bench/scoring.py` and `tests/test_scoring.py`: mapping `judge_config` now rejects missing/non-mapping `judge_params` while accepting `{}`; boolean verifier params reject string values instead of truthiness-coercing them; scalar string `contains_any` `needles` is treated as one needle instead of characters. Per assignment, no pytest/gates/formatters/git were run; verification used a targeted Python import/smoke snippet that compiled `tests/test_scoring.py` and exercised the corrected C04 behaviours.

### [x] C05 — Runner + model/agent adapters + run-records + tool-task execution contract

- Conventional Commit candidate: `feat(runner): execute benchmarks with reproducible run records and tool-task agent adapter`
- Owned files/scope: `src/ai_bench/runner.py`, `src/ai_bench/models.py` (text + agent/tool-task adapter; C05 is sole owner), `src/ai_bench/run_records.py` (tool-action transcript + final repo-state fields frozen by C02; C05 is sole owner), CLI additions in `src/ai_bench/cli.py`, `tests/test_runner.py`, `tests/test_run_records.py`, `tests/test_agent_adapter.py`.
- Dependencies: C03 and C04. C05 does NOT depend on C07: the `--replay` mode is plumbing only (loading, schema validation, snapshot materialization, hand-off to the state-check verifier interface) and is tested against a fake/stub state-check verifier; the real state-check verifier implementation lands in C07.2.
- Parallel: normally serial; C07 runs after C05 and must not edit `models.py` or `run_records.py`. C05's `--replay` plumbing does not block on C07; real-verifier transcript-replay acceptance is owned by C07.2 and exercised end-to-end in C08/C11/C12.
- Verification: `uv run pytest tests/test_runner.py tests/test_run_records.py tests/test_agent_adapter.py -q`; reproducibility assertion in tests; agent-adapter contract test with a deterministic stub agent and an in-process fake dispatcher capturing exit codes/stdout/stderr/durations and handing final state to the state-check verifier interface; smoke-selector test for `ai-bench run <benchmark> --tag smoke --model stub`; non-stub file-prediction test (`ai-bench run <benchmark> --predictions <fixture-pred-dir>` scores real text predictions with the real C04 verifiers, writes a schema-valid run-record, no API key/network); non-stub transcript-replay plumbing test (`ai-bench run <benchmark> --replay <fixture-transcript-dir>` replays submitted agent transcripts through the state-check verifier interface using a fake/stub state-check verifier — NOT the real verifier, which arrives in C07.2 — writes a schema-valid run-record, no sandbox re-exec/API key/host mutation). Real-verifier transcript-replay acceptance is NOT verified here; it is owned by C07.2 and exercised end-to-end in C08/C11/C12.
- Run/CLI contract (C05-owned): `ai-bench run` exits 0 when selected cases load, evaluate, score, and write a schema-valid run-record, regardless of pass rate or failed verdicts; it exits non-zero for validation/load/runtime/infrastructure/verifier/run-record failures, including missing inputs, verifier exceptions/config errors, unevaluated/unscored selected cases, and run-record write/schema-validation failures. Failed case verdicts are evaluation data, not process failures.
- Review criteria: no live API keys; run-records validate against schema including tool-action transcript + final repo-state fields frozen by C02; environment hash deterministic; no silent case skipping; agent-adapter contract defined solely here before C07/C08 so sandbox and fixtures have a stable interface; `--tag smoke` selector works; a CI-safe non-stub evaluation path exists and is tested (file-based `--predictions` scores real text outputs with the real C04 text verifiers complete in C04; `--replay` transcript-replay plumbing loads real submitted transcripts, materializes snapshots, and hands them to the state-check verifier interface, tested against a fake/stub verifier in C05) so the v1 checklist cannot pass on deterministic stubs alone. Real-verifier transcript-replay acceptance (real submitted agent transcripts scored by the real state-check verifier) is NOT a C05 acceptance criterion; it is owned by C07.2 and exercised end-to-end with checked-in `--replay` samples in C08/C11/C12.
- Review addendum: downstream C06/C08/C11 gates rely on the C05 exit-code distinction between scored failed verdicts and broken commands.
- Tasks:
  - [x] Implement thin text model-adapter interface (prompt + params in, text out).
  - [x] Implement deterministic stub text adapter.
  - [x] Define agent/tool-task adapter interface (sole owner): per-case sandbox handle, structured tool-action stream (command, argv, cwd, env overrides, stdin), deterministic stub agent emitting scripted git/file actions.
  - [x] Implement run-record tool-action transcript + final repo-state fields per the C02 schema (sole owner).
  - [x] Define how final repo state is passed to the state-check verifier.
  - [x] Add `ai-bench run <benchmark>` wiring selecting text vs agent adapter by `task_type`, with `--tag <tag>` selector (e.g. `--tag smoke`).
  - [x] Define `ai-bench run` process exit semantics: exit 0 when selected cases load/evaluate/score and a schema-valid run-record is written regardless of pass rate; non-zero for validation/load/runtime/infrastructure/verifier/run-record failures.
  - [x] Add exit-code contract tests: failed verdicts/low aggregate score exit 0 with a schema-valid run-record; malformed load, missing predictions/transcripts, verifier exception/config error, runtime/infrastructure failure, unevaluated or unscored selected case, and run-record write/schema-validation failure exit non-zero.
  - [x] Write pinned run-record artifacts.
  - [x] Ensure run-records expose per-case verdict/provenance/raw output/tool transcript, params, seed, environment hash, and run-record identity needed by C09's `ai-bench failures save <run-record> --store <failure-store>`.
  - [x] Add reproducibility tests for same/different seeds.
  - [x] Add agent-adapter contract test with stub agent + fake dispatcher.
  - [x] Add smoke-selector test (`--tag smoke` runs only `smoke`-tagged cases).
  - [x] Implement CI-safe non-stub file-prediction mode (`ai-bench run <benchmark> --predictions <dir>`): load per-case text predictions from disk, score with real C04 verifiers, write schema-valid run-record with `model id` recording the prediction source; no API key/network.
  - [x] Implement CI-safe non-stub transcript-replay plumbing (`ai-bench run <benchmark> --replay <dir>`): load submitted agent/tool-action transcripts + optional final repo-state snapshots, hand them to the state-check verifier interface (shape from C04), write schema-valid run-record; test against a fake/stub state-check verifier only (the real state-check verifier arrives in C07.2); no API key/network/host mutation. Real-verifier transcript-replay acceptance is owned by C07.2, not here.
  - [x] Add non-stub file-prediction test (real C04 verifiers) and non-stub transcript-replay plumbing test (fake/stub state-check verifier) asserting schema-valid run-records and no live API keys/network.
  - [x] Run and record verification commands.
- Verification evidence (C05): Orchestrator verification passed after all C05 review fixes. `python3 -m py_compile src/ai_bench/runner.py tests/test_runner.py` -> passed. `uv run pytest tests/test_runner.py::test_materialize_replay_state_ignores_unknown_exit_code_without_timeout_or_violation -q` -> 1 passed. `uv run pytest tests/test_runner.py::test_materialize_replay_state_normalizes_cwd_and_ignores_failed_writes -q` -> 1 passed. `uv run pytest tests/test_runner.py tests/test_run_records.py tests/test_agent_adapter.py -q` -> 30 passed. `uv run pytest -q` -> 253 passed (full suite, no regressions). Coverage spans: thin text model-adapter interface + deterministic stub text adapter (`test_stub_text_run_writes_schema_valid_record_and_failed_verdict_is_data`); agent/tool-task adapter interface as sole owner with structured tool-action stream (command/argv/cwd/env overrides/stdin) and scripted stub agent (`test_stub_agent_emits_structured_git_and_file_actions`, `test_stub_dispatcher_records_c02_transcript_fields`); run-record tool-action transcript + final repo-state fields per C02 schema (`test_tool_run_record_preserves_transcript_and_final_state`, `test_replay_materializers_require_c02_transcript_fields`, `test_repo_state_materializer_rejects_incomplete_snapshot`); final repo state handed to the state-check verifier interface (`test_runner_hands_stub_agent_state_to_fake_state_check`, `test_replay_plumbing_scores_transcripts_with_c05_fake_state_check`); `ai-bench run` wiring selecting text vs agent adapter by `task_type` with `--tag` selector (`test_smoke_tag_selector_runs_only_smoke_cases`); exit semantics — exit 0 for scored failed verdicts with a schema-valid run-record, non-zero for missing predictions/transcripts, invalid verifier config, empty selection, and run-record write/schema-validation failures (`test_cli_failed_verdicts_exit_zero_but_missing_prediction_exits_nonzero`, `test_cli_replay_failed_verdict_exits_zero_missing_transcript_exits_nonzero`, `test_invalid_verifier_config_and_empty_selection_are_command_failures`, `test_run_record_write_failure_is_command_failure`); pinned run-record artifacts written via `write_run_record` and schema-validated (`test_text_run_record_validates_and_writes`, `test_tool_run_record_preserves_transcript_and_final_state`); run-records expose per-case verdict/provenance/raw output/tool transcript, params, seed, deterministic path-independent environment hash, and run-record identity (`test_environment_hash_is_deterministic_and_path_independent`, `test_validation_rejects_missing_text_observed`); reproducibility for same/different seeds (`test_stub_seed_reproducibility_and_seed_variance`); agent-adapter contract test with stub agent + fake dispatcher (`test_stub_dispatcher_records_c02_transcript_fields`, `test_runner_hands_stub_agent_state_to_fake_state_check`); smoke-selector test (`test_smoke_tag_selector_runs_only_smoke_cases`); CI-safe non-stub file-prediction mode scoring real text outputs with real C04 verifiers, recording prediction source as `model id`, no API key/network (`test_predictions_dir_scores_real_text_outputs_with_c04_verifier`, `test_predictions_file_jsonl_supported`); CI-safe non-stub transcript-replay plumbing loading submitted transcripts + final repo-state snapshots, handing them to the state-check verifier interface, schema-valid run-record, tested against a fake/stub state-check verifier only with no API key/network/host mutation (`test_replay_plumbing_scores_transcripts_with_c05_fake_state_check`, `test_cli_replay_failed_verdict_exits_zero_missing_transcript_exits_nonzero`). Run exit semantics verified by tests: exit 0 means selected cases evaluated/scored and a schema-valid run-record written regardless of pass rate; non-zero means validation/load/runtime/infrastructure/verifier/run-record failure. Real-verifier transcript-replay acceptance remains owned by C07.2 (C05 `--replay` plumbing tested against a fake/stub verifier only). All seventeen C05 tasks are satisfied and verified; C05 checked. C01-C04 remain checked; C06+ remain unchecked.
- Review-fix evidence (C05): C05 review findings addressed in `src/ai_bench/runner.py` and `tests/test_runner.py`: (1) `prompt_template.path` now loaded relative to the benchmark directory before rendering, with absolute/escaping/missing path-only templates rejected as `RunnerError`; (2) `_materialize_replay_state` normalizes successful `file.write` paths against the action's relative `cwd` and ignores writes with a non-zero exit code (including an unknown/`None` exit code), a timeout, or a sandbox boundary violation, and skips absolute/escaping paths; (3) `_copy_fixture_if_present` walks the fixture tree before `shutil.copytree` and rejects symlinks or resolved paths escaping the benchmark directory; (4) `_metric_params` now records per-case verifier override provenance (verifier name + params, including empty params) under `_case_overrides`; (5) added exit-code contract tests for malformed load, text-adapter runtime failure, agent/dispatcher runtime failure, internal mismatch (unevaluated case), and run-record schema-validation failure, backing the previously over-marked exit-code task. Clean-review fix: `_materialize_replay_state` now materializes only `action.exit_code == 0` (an unknown/`None` exit code is no longer treated as a successful write), with timeout/boundary checks unchanged; regression test `test_materialize_replay_state_ignores_unknown_exit_code_without_timeout_or_violation` added. Orchestrator verification after all C05 review fixes: `python3 -m py_compile src/ai_bench/runner.py tests/test_runner.py` -> passed; `uv run pytest tests/test_runner.py::test_materialize_replay_state_ignores_unknown_exit_code_without_timeout_or_violation -q` -> 1 passed; `uv run pytest tests/test_runner.py::test_materialize_replay_state_normalizes_cwd_and_ignores_failed_writes -q` -> 1 passed; `uv run pytest tests/test_runner.py tests/test_run_records.py tests/test_agent_adapter.py -q` -> 30 passed; `uv run pytest -q` -> 253 passed.

### [ ] C06 — Reference benchmark A: description-to-label benchmark

- Conventional Commit candidate: `feat(benchmarks): add description-to-label reference benchmark`
- Owned files/scope: `benchmarks/description-label/benchmark.yaml`, `benchmarks/description-label/cases/*.yaml`, `benchmarks/description-label/README.md`, optional `tests/test_description_label_benchmark.py`.
- Dependencies: C03 and C05. (C03 provides `ai-bench validate`; C05 provides `ai-bench run`, the text model adapter, and the `--tag smoke` selector.)
- Parallel: may run with C08 after C05+C07 if it stays within `benchmarks/description-label/**` and benchmark-specific tests.
- Verification: `uv run ai-bench validate benchmarks/description-label`; `uv run ai-bench run benchmarks/description-label --model stub`; `uv run ai-bench run benchmarks/description-label --tag smoke --model stub`; non-stub offline scoring sample `uv run ai-bench run benchmarks/description-label --predictions benchmarks/description-label/sample_predictions` (checked-in real text predictions scored by real C04 verifiers, schema-valid run-record, no stub/live model); optional benchmark-specific pytest.
- C05 exit-contract dependency: C06 run commands are expected to exit 0 when selected cases are evaluated/scored and schema-valid run-records are written, even if some case verdicts fail. A non-zero exit is treated as validation/load/runtime/infrastructure/verifier/run-record failure and blocks C06.
- Review criteria: 20-50 original cases; no implied Theo endorsement; unambiguous expected answers; manifest populates `tags` and `status` per C02 schema; contributor/license/provenance metadata; valid non-empty run-record; `--tag smoke` covers only `smoke`-tagged cases; a checked-in non-stub prediction sample is scored by the real verifiers (not a stub) and produces a valid run-record, exercising the CI-safe non-stub path from C05.
- Review addendum: C06 acceptance relies on valid run-record generation and benchmark wiring, not on every stub/sample prediction verdict passing.
- Tasks:
  - [ ] Create benchmark manifest populating `tags` and `status` (e.g. `status: experimental`).
  - [ ] Add original description-to-label cases.
  - [ ] Add smoke subset via the reserved `smoke` case tag (at least one `smoke`-tagged case).
  - [ ] Add benchmark README with limitations and non-endorsement language.
  - [ ] Add a checked-in non-stub prediction sample (`benchmarks/description-label/sample_predictions`) and run the `--predictions` non-stub scoring path; record a schema-valid run-record.
  - [ ] Record run-command exit status separately from case pass rate, relying on C05 semantics: schema-valid run-records with failed verdicts are acceptable evaluation evidence; non-zero run exits are not.
  - [ ] Run and record verification commands.

### [ ] C07 — Hermetic sandbox + sandboxed dispatch + repo-state verifier

- Conventional Commit candidate: `feat(sandbox): add hermetic sandboxed task execution and repo-state verifier`
- Owned files/scope: `src/ai_bench/sandbox.py` (sandbox, sandboxed command dispatcher, security policy, repo-state snapshot), state-check verifier implementation in `src/ai_bench/scoring.py` (interface shape from C04), runner integration in `src/ai_bench/runner.py` only to plug the dispatcher into the C05 agent-adapter contract, `tests/fixtures/sandbox/**`, `tests/test_sandbox.py` (C07.1), `tests/test_sandbox_integration.py` (C07.2), `tests/test_sandbox_hardening.py` (C07.3). C07 must not edit `src/ai_bench/models.py` or `src/ai_bench/run_records.py`.
- Dependencies: C04 and C05. C07 runs after C05 to plug the sandboxed dispatcher into the agent-adapter and run-record interfaces frozen by C05/C02.
- Parallel: none with C05; after C05 may run alongside C06 only if C06 stays inside `benchmarks/description-label/**`.
- Verification (C07 overall — all sub-phase commands must pass): `uv run pytest tests/test_sandbox.py tests/test_sandbox_integration.py tests/test_sandbox_hardening.py -q`; integration scenario where `ai-bench run` with the stub agent creates a commit inside the sandbox, the state-check verifier passes, and the host repository is byte-identical before and after; boundary-violation scenario where every required C07.3 acceptance test fails closed and is recorded in the run-record transcript. C07 is split into ordered sub-phases C07.1 → C07.2 (depends on C07.1) and C07.3 (depends on C07.1, may run parallel with C07.2); C07 is not checked until C07.1, C07.2, and C07.3 are all checked.
- Review criteria: host repo cannot be mutated (verified by host-tree hash before/after); reliable cleanup; useful mismatch diagnostics; sandbox backend is concrete and enforced (bubblewrap/namespace backend on Linux, or in-process allowlisted dispatcher fallback), not a plain temp working tree; backend selection explicit and recorded; security posture enforced not just documented (no broad host mounts, no unchecked path joins, no execution outside sandbox, no outbound network, no inherited credentials, timeouts/resource limits applied, every violation recorded); sandboxed dispatcher satisfies the C05 agent-adapter contract; C07 did not edit `models.py` or `run_records.py`; C07 is not checked until all three ordered sub-phases (C07.1, C07.2, C07.3) are individually checked.
- Tasks (ordered sub-phases; C07 is not checked until all three are checked):

  #### [ ] C07.1 — Sandbox backend + sandboxed dispatcher confinement

  - [ ] Implement concrete enforced sandbox backend: primary bubblewrap (`bwrap`) on Linux with user + mount + network namespaces + seccomp, empty network namespace, private mount table; fallback in-process allowlisted operation dispatcher (no shell, no arbitrary subprocess) when `bwrap` is unavailable or host is non-Linux. Plain temp working tree is NOT sufficient; temp dirs are storage inside the boundary only.
  - [ ] Document host prerequisites and fallbacks; record active backend in run-record environment hash.
  - [ ] Implement read-only fixture mounting/copying strategy.
  - [ ] Implement sandboxed command dispatcher (C05 contract): working-directory/path/host-boundary confinement, record exit code/stdout/stderr/duration/timeout/boundary-violation per C02/C05 transcript fields; absolute paths and symlink escapes outside the sandbox root are rejected and recorded.
  - [ ] Add no-host-mutation assertions (host-tree hash before/after) and cleanup-on-failure coverage.
  - [ ] Run and record C07.1 verification (`uv run pytest tests/test_sandbox.py -q`).

  #### [ ] C07.2 — Repo-state verifier integration

  - [ ] Implement repo-state verifier primitives receiving final sandbox state from runner (interface shape from C04). This is the real state-check verifier implementation that the C05 `--replay` plumbing hands transcripts/snapshots to; until C07.2 lands, C05's `--replay` is tested only against a fake/stub state-check verifier.
  - [ ] Plug sandboxed dispatcher into the C05 agent-adapter contract in `src/ai_bench/runner.py` only; hand final repo-state snapshot to the state-check verifier. Do not edit `models.py` or `run_records.py`.
  - [ ] Add integration test: stub agent performs a git task inside the sandbox, state-check verifier observes pass and fail paths; host repository byte-identical before and after.
  - [ ] Add real-verifier transcript-replay acceptance test: `ai-bench run <benchmark> --replay <fixture-transcript-dir>` replays a small fixture of submitted agent/tool-action transcripts (with final repo-state snapshots) through the now-implemented real state-check verifier (C05 `--replay` plumbing wired to the C07.2 verifier), writes a validated run-record, no API key/network/host mutation. This is the real-verifier transcript-replay acceptance deferred from C05; it is owned here and exercised end-to-end with checked-in `--replay` samples in C08/C11/C12.
  - [ ] Run and record C07.2 verification (`uv run pytest tests/test_sandbox_integration.py -q`), including the real-verifier transcript-replay acceptance test passing.

  #### [ ] C07.3 — Network/env/credential/resource-limit hardening

  - [ ] Deny outbound network by default; record attempted network access as boundary violations.
  - [ ] Clear/allowlist environment variables; strip credentials, tokens, SSH keys, cloud-provider env; prevent host `~/.gitconfig`, `~/.ssh`, `~/.aws`, credential helpers visibility.
  - [ ] Enforce per-command timeouts and resource limits (CPU/wall-clock, process count, disk write where feasible).
  - [ ] Add boundary-violation acceptance tests: absolute-path and symlink-escape read/write outside sandbox fail and are recorded.
  - [ ] Add boundary-violation acceptance tests: git remote/network access (fetch/clone/push) fails and is recorded.
  - [ ] Add boundary-violation acceptance tests: credential helpers / host gitconfig / SSH / cloud env access unavailable and attempts recorded.
  - [ ] Add boundary-violation acceptance tests: subprocess/process-count/CPU/wall-clock limits enforced; spawning/long-running actions killed and recorded.
  - [ ] Run and record C07.3 verification (`uv run pytest tests/test_sandbox_hardening.py -q`).

- [ ] C07 overall: run and record the combined verification commands once C07.1, C07.2, and C07.3 are all checked.

### [ ] C08 — Reference benchmark B: git tool-proficiency benchmark

- Conventional Commit candidate: `feat(benchmarks): add git tool-proficiency reference benchmark`
- Owned files/scope: `benchmarks/git-tooling/benchmark.yaml`, `benchmarks/git-tooling/cases/*.yaml`, `benchmarks/git-tooling/fixtures/**`, `benchmarks/git-tooling/README.md`, optional `tests/test_git_tooling_benchmark.py`.
- Dependencies: C03, C05, and C07. (C03 provides `ai-bench validate`; C05 provides the agent-adapter and run-record contract and `--tag smoke` selector; C07 provides the enforced sandboxed dispatcher and state-check verifier that C08 fixtures target.)
- Parallel: may run with C06 after C05+C07 if it stays within `benchmarks/git-tooling/**` and benchmark-specific tests.
- Verification: `uv run ai-bench validate benchmarks/git-tooling`; `uv run ai-bench run benchmarks/git-tooling --model stub`; `uv run ai-bench run benchmarks/git-tooling --tag smoke --model stub`; non-stub offline transcript-replay sample `uv run ai-bench run benchmarks/git-tooling --replay benchmarks/git-tooling/sample_transcripts` (checked-in submitted agent/tool-action transcripts with final repo-state snapshots, replayed through the state-check verifier, schema-valid run-record, no sandbox re-exec/stub/live model); optional benchmark-specific pytest.
- C05 exit-contract dependency: C08 run commands are expected to exit 0 when selected cases are evaluated/scored through the state-check verifier and schema-valid run-records are written, even if some replayed verdicts fail. A non-zero exit is treated as validation/load/runtime/infrastructure/verifier/run-record failure and blocks C08.
- Review criteria: 20-50 original hermetic git tasks; deterministic expected states; manifest populates `tags` and `status` per C02 schema; fixtures rely on the enforced C07 sandbox guarantees (network denial, credential stripping, path confinement, timeouts) and cannot reach outbound network or host credentials; benchmark measures tool proficiency rather than trivia; a checked-in non-stub transcript-replay sample is scored by the real state-check verifier (not a stub; plumbing from C05, real verifier from C07.2) and produces a valid run-record, exercising the real-verifier transcript-replay acceptance owned by C07.2.
- Review addendum: C08 acceptance relies on valid run-record generation and deterministic state-check scoring, not on every replayed transcript verdict passing.
- Tasks:
  - [ ] Create benchmark manifest populating `tags` and `status` (e.g. `status: experimental`).
  - [ ] Add fixture repositories.
  - [ ] Add original git/tool-use cases.
  - [ ] Add smoke subset via the reserved `smoke` case tag, covering pass and fail paths.
  - [ ] Add benchmark README with sandbox assumptions.
  - [ ] Add a checked-in non-stub transcript-replay sample (`benchmarks/git-tooling/sample_transcripts`) and run the `--replay` non-stub scoring path; record a schema-valid run-record.
  - [ ] Record run-command exit status separately from case pass rate, relying on C05 semantics: schema-valid run-records with failed verdicts are acceptable evaluation evidence; non-zero run exits are not.
  - [ ] Run and record verification commands.

### [ ] C09 — Failure-case preservation + retry + hard-set

- Conventional Commit candidate: `feat(failures): preserve and retry benchmark failure cases`
- Owned files/scope: `src/ai_bench/failures.py`, CLI additions in `src/ai_bench/cli.py`, `tests/test_failures.py`, optional `failures/README.md`. C09 consumes `schemas/failure-store.schema.json` (frozen by C02) and adds no schema files.
- Dependencies: C06 and C08, with C05 run-record support complete.
- Parallel: serialize with C10 unless CLI/docs ownership is explicitly split.
- Preservation entry point/ownership: C09 owns `ai-bench failures save <run-record> --store <failure-store>`, which consumes schema-valid C05 run-records produced by actual `ai-bench run` invocations and preserves cases with failed verifier verdicts. C05 only guarantees record compatibility and exit semantics; it does not mutate the failure store.
- Verification: `uv run pytest tests/test_failures.py -q`; induced-failure scenario saves, retries improved/unchanged, exports hard set, and runs exported set; plus cases proving same task/model/params under a different seed or a different environment hash are NOT deduplicated (both records retained with own provenance).
- Additional end-to-end verification: create a schema-valid run-record with at least one failed verdict via the public `ai-bench run`, invoke `ai-bench failures save <run-record> --store <tmp-store>`, validate the failure store, then retry/export/run the saved failures. Hand-built internal failure objects do not satisfy this check.
- Review criteria: artifacts validate against `schemas/failure-store.schema.json` (frozen by C02); C09 adds no schema files; storage/dedup behavior explicit; verdict comparisons use verifiers; exported hard sets preserve provenance.
- Review addendum: failure preservation must be exercised through the public save entry point against real C05 run-records, preserving run-record references and the full reproducibility determinant set.
- Tasks:
  - [ ] Implement versioned failure-case store conforming to the C02 failure-store schema.
  - [ ] Capture failed task metadata and run-record references per the schema.
  - [ ] Implement public preservation entry point `ai-bench failures save <run-record> --store <failure-store>` that reads schema-valid C05 run-records, extracts failed per-case verdicts, and writes/updates the failure store.
  - [ ] Add end-to-end preservation test from actual `ai-bench run` record through `ai-bench failures save`, failure-store schema validation, retry, hard-set export, and exported-set run.
  - [ ] Implement retry improved/regressed/unchanged reporting.
  - [ ] Implement hard-set export.
  - [ ] Add deduplication keyed by the full reproducibility determinant set from the failure-store schema (task/model/params/fixture-version alone is insufficient).
  - [ ] Add dedup tests: same task/model/params with different seed or different environment hash are both retained.
  - [ ] Run and record verification command and scenario.

### [ ] C10 — Community contribution scaffold + registry + template

- Conventional Commit candidate: `feat(contrib): add benchmark template and validation workflow`
- Owned files/scope: `benchmarks/_template/**`, `CONTRIBUTING.md`, registry/index support, CLI additions in `src/ai_bench/cli.py`, `tests/test_registry.py`, `tests/test_template.py` (the `ai-bench validate` and `ai-bench validate <benchmark>` commands are delivered in C03 and tested there; C10 only adds template/registry tests and any contributor-facing wrapper).
- Dependencies: C03, C05, C06, and C08.
- Parallel: serialize with C09 unless C09 avoids CLI and docs.
- Verification: `uv run pytest tests/test_registry.py tests/test_template.py -q`; copy template to temp dir, add one case, run `ai-bench validate` (from C03), mutate manifest, confirm clear failure; registry exclusion check that `ai-bench validate` (no-arg) and the registry do not list or validate `benchmarks/_template/**`.
- Review criteria: one-command contributor path; no live credentials; duplicate ids caught; registry excludes `benchmarks/_template/**` and reads `tags`/`status` from manifests (frozen by C02) rather than inferring them; licensing/provenance expectations documented; clear validation errors; no new validate command added (reuses C03).
- Tasks:
  - [ ] Add benchmark template directory under `benchmarks/_template/**` with manifest stub populating `tags` and `status: experimental`, one sample case (including a `smoke`-tagged case), and verifier guidance.
  - [ ] Add contributor-facing validation workflow built on the existing `ai-bench validate <benchmark>` and `ai-bench validate` (from C03); no new validate command.
  - [ ] Add auto-discovered registry/index excluding `benchmarks/_template/**`, sourcing `tags`/`status` from manifest fields frozen by C02.
  - [ ] Add CONTRIBUTING guide covering provenance, licensing, `experimental` vs `stable` status, and review expectations.
  - [ ] Add registry and template tests, including the `_template` exclusion check.
  - [ ] Run and record verification command and scenario.

### [ ] C11 — Conformance, smoke, and CI hardening

- Conventional Commit candidate: `ci: verify benchmark conformance and smoke runs`
- Owned files/scope: `tests/test_conformance.py`, `tests/test_smoke.py`, `tests/conftest.py`, `.github/workflows/ci.yml`, small fixture adjustments for suite reliability.
- Dependencies: C09 and C10.
- Parallel: none; integration gate.
- Verification: `uv run pytest -q`; `uv run ai-bench run benchmarks/description-label --tag smoke --model stub`; `uv run ai-bench run benchmarks/git-tooling --tag smoke --model stub`; non-stub offline scoring `uv run ai-bench run benchmarks/description-label --predictions benchmarks/description-label/sample_predictions`; non-stub offline transcript replay `uv run ai-bench run benchmarks/git-tooling --replay benchmarks/git-tooling/sample_transcripts`; inspect CI workflow for local reproducibility; remote CI run required once pushed and its evidence (workflow run URL, exact commit SHA, passing/successful outcome for that SHA) recorded in the tracker — failed/cancelled/skipped/timed-out/neutral outcomes do not satisfy this evidence, and no `TBD` owner/date is accepted for a deferral.
- C05 exit-contract dependency: C11/CI treats any non-zero `ai-bench run` exit as validation/load/runtime/infrastructure/verifier/run-record failure, while failed case verdicts or low scores remain scored records and do not by themselves fail the process.
- Review criteria: behavior-focused tests; no live provider secrets; failure diagnostics clear; corrupt fixtures fail the suite; conformance and smoke exclude `benchmarks/_template/**`; remote CI evidence records a workflow run URL, exact commit SHA, and passing/successful outcome for that SHA, or an explicit approved deferral with owner/date/rationale is recorded (a `BLOCKED` note with `owner: TBD` or `date: TBD` is NOT acceptable); failed, cancelled, skipped, timed-out, or neutral CI outcomes keep C11/final gate unchecked; CI exercises the non-stub offline scoring path (`--predictions` and `--replay` samples), not only stub smoke runs.
- Tasks:
  - [ ] Add repository-wide benchmark conformance tests excluding `benchmarks/_template/**`.
  - [ ] Add stub smoke tests for every benchmark using the durable `--tag smoke` selector (`ai-bench run <benchmark> --tag smoke --model stub`), proving each benchmark has a non-empty `smoke`-tagged subset.
  - [ ] Add CI workflow.
  - [ ] Add mutation-style validation failure coverage where practical.
  - [ ] Add CI steps running the non-stub offline scoring path (`--predictions` for description-label, `--replay` for git-tooling) so CI proves real outputs/transcripts are scored, not only stubs; run-records must validate against `schemas/run-record.schema.json` with no secrets/network.
  - [ ] Add CI/test assertions relying on C05 exit semantics: a scored failed-verdict sample exits 0 with a schema-valid run-record, and a deliberately invalid run input exits non-zero.
  - [ ] Record remote CI evidence (workflow run URL, exact commit SHA, passing/successful outcome for that SHA) in the tracker. Authoritative rule: C11 is not checked until this successful evidence is recorded, OR an explicit approved deferral with owner/date/rationale is recorded; failed, cancelled, skipped, timed-out, or neutral outcomes do not satisfy this task, and a `BLOCKED` note with `owner: TBD` or `date: TBD` is NOT acceptable.
  - [ ] Run and record verification commands.

### [ ] C12 — README, governance, and release finalization

- Conventional Commit candidate: `docs: document benchmark suite usage and governance`
- Owned files/scope: `README.md`, `CONTRIBUTING.md`, benchmark READMEs if needed, tracker final state updates only after actual implementation.
- Dependencies: C11.
- Parallel: none; final v1 narrative and release gate.
- Verification: follow README commands in a clean checkout after C11; `uv run ai-bench validate` (no-arg, validate-all, delivered in C03); `uv run ai-bench validate benchmarks/description-label`; `uv run ai-bench validate benchmarks/git-tooling`; `uv run ai-bench run benchmarks/description-label --model stub`; `uv run ai-bench run benchmarks/git-tooling --model stub`; non-stub offline scoring `uv run ai-bench run benchmarks/description-label --predictions benchmarks/description-label/sample_predictions`; non-stub offline transcript replay `uv run ai-bench run benchmarks/git-tooling --replay benchmarks/git-tooling/sample_transcripts`.
- Review criteria: README claims match implemented commands; non-endorsement language clear; docs explain score limits; all active C01-C12 items checked with evidence; C11 remote CI evidence records a workflow run URL, exact commit SHA, and passing/successful outcome for that SHA, or an explicit approved deferral with owner/date/rationale is recorded (a `BLOCKED` note with `owner: TBD` or `date: TBD` is NOT acceptable; failed/cancelled/skipped/timed-out/neutral CI outcomes do not satisfy the gate); non-stub offline scoring path (`--predictions` and `--replay`) exercised in final verification.
- Tasks:
  - [ ] Expand README from idea stub into project overview.
  - [ ] Document install, validate (both forms), run, add-benchmark, and failure-case workflows.
  - [ ] Add governance/review criteria for community benchmarks.
  - [ ] Add post-v1 roadmap for obscure/multimodal domains.
  - [ ] Confirm C11 remote CI evidence records a workflow run URL, exact commit SHA, and passing/successful outcome for that SHA, or an explicit approved deferral with owner/date/rationale is recorded, before checking C11; failed, cancelled, skipped, timed-out, or neutral outcomes do not satisfy this task, and a `BLOCKED` note with `owner: TBD` or `date: TBD` is NOT acceptable.
  - [ ] Follow README commands and record final verification evidence.

### [ ] C13 — Post-v1 obscure-domain and multimodal expansion

- Conventional Commit candidate: `feat(benchmarks): add post-v1 obscure-domain benchmark support`
- Owned files/scope: new `benchmarks/<domain-id>/**`, a versioned schema-evolution/migration plan for any asset/modality schema changes (owned here, not by in-flight edits to the C02 v1 schemas: schema `version` bump, migration/coercion path from v1 records, compatibility tests), runner/adapter extensions only if required, README and benchmark README updates.
- Dependencies: C12.
- Parallel: after C12, separate domain benchmarks may run in parallel only if they do not edit shared schemas, adapters, runner behavior, docs, or checklist items.
- Verification: at minimum `uv run ai-bench validate benchmarks/<domain-id>` plus stub smoke run, or explicit manual protocol if external domain assets cannot run hermetically.
- Review criteria: additive compatibility with v1; any schema change is a versioned migration with compatibility tests proving existing v1 benchmarks/run-records still validate or are migrated deterministically (no silent breaking change to the C02 v1 schemas); explicit licensing/provenance; real model/agent weakness; non-hermetic requirements documented as blockers before merge.
- Tasks:
  - [ ] Choose one post-v1 domain with clear README alignment.
  - [ ] Define any required modality/asset schema changes as a versioned schema-evolution/migration plan: bumped schema `version`, deterministic migration/coercion from v1 records, and compatibility tests proving existing v1 benchmarks/run-records still validate or migrate.
  - [ ] Add domain benchmark fixtures and metadata.
  - [ ] Add domain-specific verification method.
  - [ ] Update README roadmap/status.
  - [ ] Run and record verification method.

## Final verification log

Record final commands only after implementation chunks are complete.

- [ ] `uv run pytest -q` — outcome: not run; implementation not started.
- [ ] `uv run ai-bench validate` (no-arg, validate-all excluding `benchmarks/_template/**`) — outcome: not run; implementation not started.
- [ ] `uv run ai-bench validate benchmarks/description-label` — outcome: not run; implementation not started.
- [ ] `uv run ai-bench validate benchmarks/git-tooling` — outcome: not run; implementation not started.
- [ ] `uv run ai-bench run benchmarks/description-label --model stub` — outcome: not run; implementation not started.
- [ ] `uv run ai-bench run benchmarks/git-tooling --model stub` — outcome: not run; implementation not started.
- [ ] `uv run ai-bench run benchmarks/description-label --tag smoke --model stub` — outcome: not run; implementation not started.
- [ ] `uv run ai-bench run benchmarks/git-tooling --tag smoke --model stub` — outcome: not run; implementation not started.
- [ ] `uv run ai-bench run benchmarks/description-label --predictions benchmarks/description-label/sample_predictions` (non-stub offline scoring) — outcome: not run; implementation not started.
- [ ] `uv run ai-bench run benchmarks/git-tooling --replay benchmarks/git-tooling/sample_transcripts` (non-stub offline transcript replay) — outcome: not run; implementation not started.
- [ ] Run-command process outcomes above recorded using C05 semantics — outcome: not run; implementation not started. Exit 0 means selected cases evaluated/scored and schema-valid run-record written, not that every verdict passed; non-zero means validation/load/runtime/infrastructure/verifier/run-record failure.
- [ ] Passing remote CI evidence (workflow run URL, exact commit SHA, successful outcome) — outcome: not run; implementation not started. Authoritative rule: this item is not checked until the URL/SHA and passing/successful outcome for that exact SHA are recorded, or an explicit approved deferral with owner/date/rationale is recorded; failed, cancelled, skipped, timed-out, or neutral outcomes do not satisfy this item, and a `BLOCKED` note with `owner: TBD` or `date: TBD` is NOT acceptable.
- [ ] README clean-checkout walkthrough — outcome: not run; implementation not started.
