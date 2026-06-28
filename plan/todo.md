# Implementation Checklist: Community AI Benchmark Platform

This checklist is written for a coding agent implementing the project step by step. It assumes the design in `design.md` is the source of truth.

Use the default stack from `design.md` unless the repository already has a different stack:

- TypeScript monorepo.
- `pnpm` workspace.
- Next.js web app.
- PostgreSQL.
- Prisma or Drizzle.
- Redis + BullMQ.
- S3-compatible storage.
- Docker-based runner for local/dev.
- Sandboxed runner/scorer workers.
- Optional Python for example scorers.

## 0. Ground rules

- [ ] Do not use Theo's name or social handles in product branding.
- [ ] Do not imply endorsement from Theo, labs, model providers, or benchmark authors.
- [ ] Treat benchmark packages, scorers, uploaded assets, model outputs, and agent outputs as untrusted input.
- [ ] Keep benchmark versions immutable once released.
- [ ] Ensure every score is tied to a benchmark version, scorer hash, run config hash, model metadata, and agent metadata.
- [ ] Prefer objective scoring over LLM-as-judge scoring.
- [ ] Disable network in runner/scorer sandboxes by default.
- [ ] Never expose provider API keys to benchmark code or scorer code.
- [ ] Escape or sanitize all model outputs before rendering in the UI.
- [ ] Maintain audit logs for release, review, publication, deletion, and admin actions.

Completion gate:

- [ ] The repository has a visible `README.md` stating these rules.

## 1. Repository bootstrap

### 1.1 Initialize monorepo

- [ ] Create repository root.
- [ ] Add `package.json`.
- [ ] Add `pnpm-workspace.yaml`.
- [ ] Add `.gitignore`.
- [ ] Add `.editorconfig`.
- [ ] Add `.npmrc` with strict peer dependency and package-manager settings if desired.
- [ ] Add shared TypeScript config under `packages/config/tsconfig`.
- [ ] Add ESLint config under `packages/config/eslint`.
- [ ] Add Prettier config.
- [ ] Add root scripts:
  - [ ] `dev`
  - [ ] `build`
  - [ ] `test`
  - [ ] `lint`
  - [ ] `typecheck`
  - [ ] `db:migrate`
  - [ ] `db:seed`
  - [ ] `worker:runner`
  - [ ] `worker:scorer`

Suggested layout:

```txt
apps/web
apps/api
packages/benchmark-spec
packages/db
packages/runner-core
packages/model-adapters
packages/scoring
packages/ui
workers/runner
workers/scorer
cli/benchctl
examples/skate-trick-name-lite
examples/git-tool-use-lite
docs
```

Completion gate:

- [ ] `pnpm install` succeeds.
- [ ] `pnpm typecheck` runs, even if no code exists yet.
- [ ] `pnpm lint` runs, even if no code exists yet.

### 1.2 Add local infrastructure

- [ ] Add `docker-compose.yml` with:
  - [ ] PostgreSQL.
  - [ ] Redis.
  - [ ] MinIO or another S3-compatible local object store.
- [ ] Add `.env.example` with:
  - [ ] `DATABASE_URL`
  - [ ] `REDIS_URL`
  - [ ] `S3_ENDPOINT`
  - [ ] `S3_REGION`
  - [ ] `S3_BUCKET`
  - [ ] `S3_ACCESS_KEY_ID`
  - [ ] `S3_SECRET_ACCESS_KEY`
  - [ ] `AUTH_SECRET`
  - [ ] `APP_BASE_URL`
  - [ ] `RUNNER_SANDBOX_MODE`
- [ ] Add `scripts/check-env.ts` or equivalent.
- [ ] Add setup docs to `README.md`.

Completion gate:

- [ ] `docker compose up -d` starts all infrastructure services.
- [ ] The app can connect to DB, Redis, and object storage in a smoke test.

## 2. Database schema

### 2.1 Create DB package

- [ ] Create `packages/db`.
- [ ] Configure Prisma or Drizzle.
- [ ] Add DB client export.
- [ ] Add migration commands.
- [ ] Add seed script.

### 2.2 Implement initial tables

Create tables/entities for:

- [ ] `users`
- [ ] `organizations`
- [ ] `organization_members`
- [ ] `benchmarks`
- [ ] `benchmark_versions`
- [ ] `tasks`
- [ ] `assets`
- [ ] `scorers`
- [ ] `models`
- [ ] `agent_scaffolds`
- [ ] `runs`
- [ ] `run_task_results`
- [ ] `failure_cases`
- [ ] `leaderboard_entries`
- [ ] `reviews`
- [ ] `audit_logs`
- [ ] `api_tokens`

For every table:

- [ ] Add `id`.
- [ ] Add `created_at`.
- [ ] Add `updated_at` where mutable.
- [ ] Add relevant foreign keys.
- [ ] Add indexes for common queries.
- [ ] Add unique constraints for slugs, versions, task keys, and package hashes where appropriate.

Completion gate:

- [ ] Migration applies cleanly to an empty DB.
- [ ] Migration rolls back or can be reset cleanly in local dev.
- [ ] Seed script creates at least one admin/reviewer user, one mock model, and one mock agent scaffold.

### 2.3 Add enums

- [ ] Add benchmark status enum:
  - [ ] `draft`
  - [ ] `pending_review`
  - [ ] `public`
  - [ ] `archived`
  - [ ] `rejected`
- [ ] Add benchmark version status enum:
  - [ ] `draft`
  - [ ] `validating`
  - [ ] `pending_review`
  - [ ] `released`
  - [ ] `deprecated`
  - [ ] `rejected`
- [ ] Add risk class enum:
  - [ ] `low`
  - [ ] `medium`
  - [ ] `high`
  - [ ] `restricted`
- [ ] Add run status enum:
  - [ ] `queued`
  - [ ] `running`
  - [ ] `scoring`
  - [ ] `completed`
  - [ ] `failed`
  - [ ] `cancelled`
- [ ] Add verification status enum:
  - [ ] `unverified`
  - [ ] `self_reported`
  - [ ] `verified`
  - [ ] `rejected`
- [ ] Add task result status enum:
  - [ ] `queued`
  - [ ] `running`
  - [ ] `passed`
  - [ ] `failed`
  - [ ] `errored`
  - [ ] `timed_out`
  - [ ] `skipped`
- [ ] Add failure mode enum:
  - [ ] `wrong_answer`
  - [ ] `invalid_format`
  - [ ] `missing_required_field`
  - [ ] `tool_misuse`
  - [ ] `git_state_wrong`
  - [ ] `repository_tests_failed`
  - [ ] `timeout`
  - [ ] `budget_exhausted`
  - [ ] `unsafe_action_blocked`
  - [ ] `hallucinated_capability`
  - [ ] `refused`
  - [ ] `overfit_to_example`
  - [ ] `partial_completion`
  - [ ] `scorer_error`
  - [ ] `infrastructure_error`
  - [ ] `other`

Completion gate:

- [ ] Type-safe enum values are available in application code.

## 3. Benchmark package specification

### 3.1 Create `packages/benchmark-spec`

- [ ] Add Zod schemas or equivalent runtime validation schemas.
- [ ] Add TypeScript types generated from schemas.
- [ ] Add JSON Schema export for external tools.
- [ ] Add fixtures for valid and invalid benchmark packages.

### 3.2 Implement manifest schema

Validate `benchmark.yaml` fields:

- [ ] `schema_version`
- [ ] `id`
- [ ] `title`
- [ ] `summary`
- [ ] `description`
- [ ] `domain`
- [ ] `tags`
- [ ] `license`
- [ ] `authors`
- [ ] `source_disclosure`
- [ ] `risk_class`
- [ ] `task_type`
- [ ] `input_modalities`
- [ ] `output_type`
- [ ] `output_schema`
- [ ] `scoring`
- [ ] `sandbox`
- [ ] `splits`
- [ ] `versioning`

Validation details:

- [ ] Reject missing required fields.
- [ ] Reject invalid semantic versions.
- [ ] Reject unsafe benchmark IDs or slugs.
- [ ] Reject restricted risk class for public release in MVP.
- [ ] Warn on high-risk class requiring manual review.
- [ ] Validate allowed tool names.
- [ ] Validate sandbox limits are below system maximums.
- [ ] Validate split paths are relative and safe.

Completion gate:

- [ ] Valid manifest fixture passes.
- [ ] Invalid manifest fixtures fail with clear error codes.

### 3.3 Implement task JSONL schema

- [ ] Parse JSONL with line numbers.
- [ ] Validate each task has:
  - [ ] `id`
  - [ ] `input`
  - [ ] `expected` unless benchmark explicitly permits hidden/manual scoring.
  - [ ] `metadata`
- [ ] Validate unique task IDs across all splits.
- [ ] Validate task IDs use safe characters.
- [ ] Validate asset references.
- [ ] Validate output schema compatibility where possible.
- [ ] Validate task weights if present.
- [ ] Produce actionable errors with split name and line number.

Completion gate:

- [ ] Parser handles valid JSONL.
- [ ] Parser reports exact line for malformed JSON.
- [ ] Duplicate task IDs are rejected.

### 3.4 Implement deterministic hashing

- [ ] Implement canonical JSON stringify.
- [ ] Normalize line endings to LF.
- [ ] Hash manifest.
- [ ] Hash each task file.
- [ ] Hash each asset.
- [ ] Hash scorer code.
- [ ] Hash full package.
- [ ] Add tests proving stable hashes across OS line endings and file traversal order.

Completion gate:

- [ ] Same package contents produce same hashes across two temp directories.

## 4. Package validation pipeline

### 4.1 Safe unpacking

- [ ] Add zip/tar extraction utility.
- [ ] Reject absolute paths.
- [ ] Reject `..` path traversal.
- [ ] Reject symlink escapes.
- [ ] Reject files above max size.
- [ ] Reject package above max total size.
- [ ] Reject unsupported file types where applicable.
- [ ] Store unpacked package in temp directory.
- [ ] Ensure temp directory is deleted after validation.

Completion gate:

- [ ] Zip-slip test package is rejected.
- [ ] Symlink escape test package is rejected.

### 4.2 Package validation command

Create function:

```ts
validateBenchmarkPackage(path: string): Promise<ValidationReport>
```

- [ ] Parse manifest.
- [ ] Validate split files.
- [ ] Validate tasks.
- [ ] Validate assets.
- [ ] Validate README exists.
- [ ] Validate LICENSE exists.
- [ ] Validate `docs/data-card.md` exists or warn for MVP.
- [ ] Validate scorer exists if configured.
- [ ] Run scorer smoke test if possible.
- [ ] Compute hashes.
- [ ] Return `ok`, `errors`, `warnings`, `hashes`, and task counts.

Completion gate:

- [ ] Valid seed benchmark package produces `ok: true`.
- [ ] Invalid fixtures produce expected errors.

### 4.3 API/job integration

- [ ] Add `benchmark-validation` queue.
- [ ] Add validation job processor.
- [ ] Persist validation report.
- [ ] Update `benchmark_versions.status`.
- [ ] Store package zip in object storage after basic safe unpack succeeds.
- [ ] Record package hash and manifest hash.
- [ ] Add audit log entry.

Completion gate:

- [ ] Uploading a valid package creates a version in `pending_review`.
- [ ] Uploading an invalid package creates a validation report with errors and does not release it.

## 5. Authentication and authorization

### 5.1 Auth implementation

- [ ] Add authentication provider.
- [ ] Support local dev auth.
- [ ] Support OAuth provider if configured.
- [ ] Store users in DB.
- [ ] Add session helpers.
- [ ] Add API token model for CLI.
- [ ] Add API token creation UI or endpoint.
- [ ] Hash API tokens before storage.

Completion gate:

- [ ] User can sign in locally.
- [ ] API token can authenticate a CLI request.

### 5.2 Authorization middleware

- [ ] Implement role checks.
- [ ] Implement ownership checks.
- [ ] Implement reviewer/admin checks.
- [ ] Protect benchmark mutation endpoints.
- [ ] Protect run creation endpoint.
- [ ] Protect review endpoints.
- [ ] Protect admin endpoints.
- [ ] Add tests for denied access.

Completion gate:

- [ ] Anonymous user cannot create benchmark.
- [ ] Non-owner cannot edit benchmark.
- [ ] Non-reviewer cannot approve release.

## 6. Object storage

### 6.1 Storage abstraction

Create package or module with:

- [ ] `putObject`
- [ ] `getObject`
- [ ] `headObject`
- [ ] `deleteObject`
- [ ] `createSignedDownloadUrl`
- [ ] `createSignedUploadUrl` if needed.
- [ ] `copyObject`
- [ ] `listObjects` for admin/debug only.

Completion gate:

- [ ] Local MinIO integration test passes.
- [ ] Object SHA-256 is verified after upload.

### 6.2 Storage prefixes

Implement prefixes:

- [ ] `packages/{benchmarkVersionId}/{packageHash}.zip`
- [ ] `assets/{assetId}/{sha256}`
- [ ] `runs/{runId}/config.yaml`
- [ ] `runs/{runId}/tasks/{taskResultId}/trace.jsonl`
- [ ] `runs/{runId}/tasks/{taskResultId}/stdout.log`
- [ ] `runs/{runId}/tasks/{taskResultId}/stderr.log`
- [ ] `runs/{runId}/tasks/{taskResultId}/artifacts/{filename}`
- [ ] `failures/{failureId}/reproduction-bundle.tar.zst`

Completion gate:

- [ ] Run artifacts can be uploaded and downloaded via signed URL.
- [ ] Private artifacts are not publicly accessible without signed URL.

## 7. Core API

### 7.1 Benchmark endpoints

Implement:

- [ ] `GET /api/v1/benchmarks`
- [ ] `POST /api/v1/benchmarks`
- [ ] `GET /api/v1/benchmarks/:slug`
- [ ] `PATCH /api/v1/benchmarks/:slug`
- [ ] `POST /api/v1/benchmarks/:slug/package`
- [ ] `POST /api/v1/benchmarks/:slug/validate`
- [ ] `POST /api/v1/benchmarks/:slug/releases`
- [ ] `GET /api/v1/benchmarks/:slug/versions`
- [ ] `GET /api/v1/benchmarks/:slug/versions/:version`

For each endpoint:

- [ ] Validate request body.
- [ ] Enforce authorization.
- [ ] Return typed error responses.
- [ ] Write audit log for mutations.
- [ ] Add API tests.

Completion gate:

- [ ] A user can create a draft benchmark and upload a package via API.
- [ ] A reviewer can approve/release a validated version via API.

### 7.2 Run endpoints

Implement:

- [ ] `POST /api/v1/runs`
- [ ] `GET /api/v1/runs/:runId`
- [ ] `GET /api/v1/runs/:runId/events`
- [ ] `GET /api/v1/runs/:runId/tasks`
- [ ] `GET /api/v1/runs/:runId/tasks/:taskResultId`
- [ ] `POST /api/v1/runs/:runId/cancel`
- [ ] `POST /api/v1/runs/:runId/publish`

Run creation must:

- [ ] Validate benchmark version exists and is released.
- [ ] Validate split exists.
- [ ] Validate model metadata.
- [ ] Validate agent scaffold.
- [ ] Validate budget and timeout.
- [ ] Persist canonical run config.
- [ ] Compute run config hash.
- [ ] Enqueue `run-execution` job.

Completion gate:

- [ ] Creating a run enqueues a job and returns `runId`.
- [ ] Run status can be read.
- [ ] Run events stream status updates.

### 7.3 Leaderboard endpoints

Implement:

- [ ] `GET /api/v1/leaderboards/:benchmarkSlug`
- [ ] `GET /api/v1/leaderboards/:benchmarkSlug/:version`

Support filters:

- [ ] `split`
- [ ] `verifiedOnly`
- [ ] `openWeightsOnly`
- [ ] `agentScaffold`
- [ ] `metric`
- [ ] `costMax`
- [ ] `dateFrom`
- [ ] `dateTo`

Completion gate:

- [ ] Leaderboard returns sorted entries by primary score.
- [ ] Verified entries are visually and structurally distinct from self-reported entries.

### 7.4 Failure-case endpoints

Implement:

- [ ] `GET /api/v1/failures`
- [ ] `POST /api/v1/failures`
- [ ] `GET /api/v1/failures/:failureId`
- [ ] `POST /api/v1/failures/:failureId/rerun`
- [ ] `PATCH /api/v1/failures/:failureId`
- [ ] `DELETE /api/v1/failures/:failureId`

Failure promotion must:

- [ ] Require failed/errored/timed-out task result.
- [ ] Copy relevant metadata.
- [ ] Build reproduction bundle job.
- [ ] Enforce visibility rules.
- [ ] Add audit log entry.

Completion gate:

- [ ] Failed task can be promoted to failure case.
- [ ] Failure detail endpoint includes reproduction bundle status.

### 7.5 Review/admin endpoints

Implement:

- [ ] `GET /api/v1/reviews/queue`
- [ ] `POST /api/v1/reviews/:subjectType/:subjectId/decision`
- [ ] `GET /api/v1/audit-log`
- [ ] `POST /api/v1/admin/takedown`

Completion gate:

- [ ] Reviewer can approve or reject a benchmark version.
- [ ] Admin can unpublish a benchmark or failure case.
- [ ] Audit log records the action.

## 8. Runner core

### 8.1 Create `packages/runner-core`

- [ ] Define runner interfaces.
- [ ] Define model adapter interface.
- [ ] Define agent scaffold interface.
- [ ] Define tool-call trace format.
- [ ] Define task workspace interface.
- [ ] Define normalized output format.
- [ ] Add mock model adapter.
- [ ] Add mock agent adapter.

Interfaces to implement:

```ts
interface ModelAdapter {
  invoke(input: ModelInvocation): Promise<ModelInvocationResult>;
}

interface AgentAdapter {
  run(input: AgentInvocation): Promise<AgentInvocationResult>;
}

interface BenchmarkRunner {
  runTask(input: RunTaskInput): Promise<RunTaskOutput>;
}
```

Completion gate:

- [ ] Mock text task can be invoked without external API.
- [ ] Mock agent task can return deterministic output.

### 8.2 Text runner

- [ ] Load task input.
- [ ] Build prompt.
- [ ] Invoke model adapter.
- [ ] Capture raw output.
- [ ] Normalize output.
- [ ] Capture token/cost metadata if available.
- [ ] Return task result payload.

Completion gate:

- [ ] Text runner passes a simple exact-match benchmark with mock model.

### 8.3 Multimodal runner

- [ ] Resolve asset references from object storage.
- [ ] Pass asset handles to model adapter.
- [ ] Capture asset hashes in trace.
- [ ] Fail gracefully if model adapter does not support modality.
- [ ] Add tests using a dummy image asset.

Completion gate:

- [ ] Multimodal task can be skipped or errored with a clear reason when unsupported.

### 8.4 Agent runner

- [ ] Create temporary workspace.
- [ ] Unpack task assets.
- [ ] Apply sandbox config.
- [ ] Invoke agent scaffold.
- [ ] Capture messages.
- [ ] Capture tool calls.
- [ ] Capture stdout/stderr.
- [ ] Capture workspace diff.
- [ ] Enforce timeout.
- [ ] Enforce budget.
- [ ] Enforce denied commands.
- [ ] Clean up workspace.

Completion gate:

- [ ] Agent runner executes a simple Git task in local sandbox.
- [ ] Denied command is blocked and logged.
- [ ] Timeout produces `timed_out` result.

## 9. Scoring

### 9.1 Create `packages/scoring`

- [ ] Define scorer input/output schemas.
- [ ] Implement scorer output validator.
- [ ] Implement built-in scorers:
  - [ ] `exact_match`
  - [ ] `case_insensitive_match`
  - [ ] `alias_match`
  - [ ] `regex`
  - [ ] `json_schema`
  - [ ] `numeric_tolerance`
  - [ ] `multiple_choice`
  - [ ] `unit_tests`
  - [ ] `repository_state`
  - [ ] `tool_trace_assertions`
- [ ] Implement aggregation helpers.
- [ ] Implement failure-mode mapping helpers.

Completion gate:

- [ ] Built-in scorer unit tests pass.
- [ ] Aggregation tests pass.

### 9.2 Custom scorer sandbox

- [ ] Create scorer worker.
- [ ] Run custom Python scorer in isolated container.
- [ ] Run custom TypeScript scorer in isolated container if supported.
- [ ] Disable network.
- [ ] Mount inputs read-only.
- [ ] Provide output path for `score-result.json`.
- [ ] Enforce runtime limit.
- [ ] Enforce memory limit.
- [ ] Capture stdout/stderr.
- [ ] Validate JSON output.
- [ ] Mark scorer failures as `scorer_error`, not as ordinary wrong answers.

Completion gate:

- [ ] Custom scorer can grade a fixture.
- [ ] Scorer trying to access network fails.
- [ ] Malformed scorer output is rejected.

### 9.3 Repository-state scorer

For GitBench-like tasks:

- [ ] Inspect current branch.
- [ ] Inspect commit messages.
- [ ] Inspect worktree status.
- [ ] Inspect file contents.
- [ ] Run configured tests.
- [ ] Check forbidden file modifications.
- [ ] Check forbidden commands from trace.
- [ ] Return score and detailed metrics.

Completion gate:

- [ ] Correct Git task scores 1.0.
- [ ] Wrong branch scores failure with `git_state_wrong`.
- [ ] Dirty worktree scores failure.

## 10. Runner worker

### 10.1 Job processor

- [ ] Create `workers/runner`.
- [ ] Connect to Redis queue.
- [ ] Process `run-execution` jobs.
- [ ] Load run and benchmark version.
- [ ] Create task result rows in queued state.
- [ ] Execute tasks sequentially for MVP.
- [ ] Update task result status.
- [ ] Upload traces/logs/artifacts.
- [ ] Enqueue scoring jobs or call scoring package.
- [ ] Update aggregate run status.
- [ ] Emit progress events.
- [ ] Handle cancellation.
- [ ] Handle retries safely.

Completion gate:

- [ ] End-to-end mock run completes from queued to completed.
- [ ] Task results are persisted.
- [ ] Logs are uploaded.

### 10.2 Task concurrency

For MVP:

- [ ] Add config for max concurrent tasks per run.
- [ ] Default to sequential execution.
- [ ] Make concurrency opt-in.
- [ ] Ensure output ordering remains deterministic.
- [ ] Ensure budgets are checked across concurrent tasks.

Completion gate:

- [ ] Sequential mode works.
- [ ] Concurrent mode can be disabled globally.

### 10.3 Cost/budget controls

- [ ] Store max cost per run.
- [ ] Track per-task cost.
- [ ] Stop run when budget is exhausted.
- [ ] Mark remaining tasks as skipped or budget-exhausted.
- [ ] Show budget exhaustion in UI and API.

Completion gate:

- [ ] Artificial low budget stops a run and records clear status.

## 11. Leaderboards

### 11.1 Leaderboard refresh job

- [ ] Create `leaderboard-refresh` queue/job.
- [ ] On run completion, compute candidate leaderboard entry.
- [ ] Verify benchmark version and split.
- [ ] Verify scorer hash.
- [ ] Verify task count.
- [ ] Verify run config public fields.
- [ ] Insert/update leaderboard entry.
- [ ] Compute rank.
- [ ] Preserve historical rank data if desired.

Completion gate:

- [ ] Completed verified run appears on benchmark leaderboard.
- [ ] Incomplete run does not appear.

### 11.2 Leaderboard UI rules

- [ ] Show model display name.
- [ ] Show provider.
- [ ] Show agent scaffold.
- [ ] Show primary score.
- [ ] Show cost.
- [ ] Show p50 latency.
- [ ] Show verification badge.
- [ ] Show split.
- [ ] Show run date.
- [ ] Link to run detail.
- [ ] Allow sorting by score, cost, and latency.
- [ ] Default sort by verified first, score descending, cost ascending.

Completion gate:

- [ ] User can inspect the run behind every leaderboard row.

## 12. Failure-case archive

### 12.1 Automatic failure capture

- [ ] For every failed/errored/timed-out task, store enough data to build a failure case later.
- [ ] Save raw output.
- [ ] Save normalized output.
- [ ] Save scorer output.
- [ ] Save trace.
- [ ] Save logs.
- [ ] Save workspace before/after for agent tasks if feasible.
- [ ] Save failure mode.

Completion gate:

- [ ] Failed task result contains all metadata needed for detail view.

### 12.2 Manual promotion

- [ ] Add `Promote to failure case` API.
- [ ] Add UI action on failed task result.
- [ ] Require title and summary or auto-generate draft.
- [ ] Copy task/run/model/agent metadata.
- [ ] Add tags.
- [ ] Set visibility.
- [ ] Enqueue reproduction bundle build.

Completion gate:

- [ ] User can promote failed task to failure case from run detail page.

### 12.3 Reproduction bundle builder

- [ ] Create `failure-bundle-build` job.
- [ ] Collect run config.
- [ ] Collect task input.
- [ ] Collect expected output if public.
- [ ] Collect model output.
- [ ] Collect scorer result.
- [ ] Collect trace/logs/artifacts.
- [ ] Collect workspace before/after if applicable.
- [ ] Add `README.md`.
- [ ] Add `reproduce.sh`.
- [ ] Create `.tar.zst` bundle.
- [ ] Upload to object storage.
- [ ] Store asset ID/hash on failure case.

Completion gate:

- [ ] Reproduction bundle downloads and contains expected files.
- [ ] `reproduce.sh` works with mock model for deterministic fixture.

### 12.4 Failure search

- [ ] Implement filters:
  - [ ] benchmark
  - [ ] benchmark version
  - [ ] model
  - [ ] agent
  - [ ] failure mode
  - [ ] tags
  - [ ] date
  - [ ] verification status
- [ ] Add full-text search over title/summary.
- [ ] Add indexes.
- [ ] Add failure detail page.

Completion gate:

- [ ] User can find all failures for a benchmark and failure mode.

## 13. Web application

### 13.1 App shell

- [ ] Create Next.js app.
- [ ] Add layout.
- [ ] Add navigation.
- [ ] Add auth UI.
- [ ] Add error boundary.
- [ ] Add loading states.
- [ ] Add empty states.
- [ ] Add basic responsive styling.
- [ ] Add safe Markdown renderer.
- [ ] Add table component.

Completion gate:

- [ ] App loads locally.
- [ ] Authenticated and anonymous navigation states work.

### 13.2 Landing page

- [ ] Explain platform purpose.
- [ ] Show featured benchmarks.
- [ ] Show recent leaderboard updates.
- [ ] Show recent failure cases.
- [ ] Link to docs.
- [ ] Link to submit benchmark.
- [ ] Include no-endorsement wording if inspiration is mentioned.

Completion gate:

- [ ] Anonymous user understands what the platform does and can browse benchmarks.

### 13.3 Benchmark catalog

- [ ] Implement `/benchmarks`.
- [ ] Add search input.
- [ ] Add filters for domain, tag, risk class, status.
- [ ] Show benchmark cards.
- [ ] Show latest version.
- [ ] Show primary metric.
- [ ] Show task count.
- [ ] Show risk class.
- [ ] Show verification/review status.

Completion gate:

- [ ] User can find seed benchmarks.

### 13.4 Benchmark detail page

- [ ] Implement `/benchmarks/[slug]`.
- [ ] Show metadata.
- [ ] Show README/description.
- [ ] Show version list.
- [ ] Show splits and task counts.
- [ ] Show scorer summary.
- [ ] Show data provenance.
- [ ] Show risk class.
- [ ] Show leaderboard preview.
- [ ] Show failure cases preview.
- [ ] Add `Run benchmark` button for signed-in users.

Completion gate:

- [ ] Seed benchmark detail page is complete.

### 13.5 Benchmark upload flow

- [ ] Implement `/benchmarks/new`.
- [ ] Create benchmark draft form.
- [ ] Upload package zip.
- [ ] Show upload progress.
- [ ] Trigger validation.
- [ ] Show validation report.
- [ ] Show errors and warnings.
- [ ] Allow resubmission.
- [ ] Show review status.

Completion gate:

- [ ] User can upload valid seed package and see validation success.
- [ ] User can upload invalid package and see actionable errors.

### 13.6 Run creation flow

- [ ] Implement `/benchmarks/[slug]/runs/new`.
- [ ] Select benchmark version.
- [ ] Select split.
- [ ] Select model.
- [ ] Select or enter agent scaffold.
- [ ] Configure sampling.
- [ ] Configure budgets/timeouts.
- [ ] Configure tool permissions.
- [ ] Preview canonical run config.
- [ ] Submit run.

Completion gate:

- [ ] User can start a mock run from UI.

### 13.7 Run detail page

- [ ] Implement `/runs/[runId]`.
- [ ] Show status.
- [ ] Show config summary.
- [ ] Stream progress.
- [ ] Show score when available.
- [ ] Show task results table.
- [ ] Show cost/tokens/latency.
- [ ] Show logs/artifacts links.
- [ ] Show leaderboard publication state.
- [ ] Show cancel button while queued/running.
- [ ] Show publish/verification request action after completion.

Completion gate:

- [ ] User can watch run progress and inspect failed tasks.

### 13.8 Task result detail page

- [ ] Implement `/runs/[runId]/tasks/[taskResultId]`.
- [ ] Show task input.
- [ ] Show expected output if visible.
- [ ] Show raw output.
- [ ] Show normalized output.
- [ ] Show scorer explanation.
- [ ] Show trace timeline.
- [ ] Show logs.
- [ ] Show artifacts.
- [ ] Add promote-to-failure action.

Completion gate:

- [ ] Failed seed task is inspectable and promotable.

### 13.9 Failure archive pages

- [ ] Implement `/failures`.
- [ ] Implement `/failures/[failureId]`.
- [ ] Add filters.
- [ ] Add search.
- [ ] Show failure mode.
- [ ] Show model/agent.
- [ ] Show reproduction bundle download.
- [ ] Show rerun action if implemented.

Completion gate:

- [ ] Promoted failure appears in archive and detail page.

### 13.10 Review/admin UI

- [ ] Implement `/reviews`.
- [ ] Show pending benchmark versions.
- [ ] Show validation report.
- [ ] Show manifest diff if previous version exists.
- [ ] Show risk flags.
- [ ] Approve/reject/request changes.
- [ ] Implement `/admin` minimal takedown interface.
- [ ] Show audit log.

Completion gate:

- [ ] Reviewer can approve a submitted benchmark release from UI.

## 14. CLI: `benchctl`

### 14.1 Package setup

- [ ] Create `cli/benchctl`.
- [ ] Add command parser.
- [ ] Add config file support.
- [ ] Add API token auth.
- [ ] Add pretty error output.
- [ ] Add JSON output mode.

Completion gate:

- [ ] `benchctl --help` works.

### 14.2 Benchmark author commands

Implement:

- [ ] `benchctl init`
- [ ] `benchctl validate ./path`
- [ ] `benchctl run-local ./path --split sample --model mock`
- [ ] `benchctl package ./path --out benchmark.zip`
- [ ] `benchctl upload benchmark.zip`
- [ ] `benchctl release BENCHMARK_SLUG --version 0.1.0`

Completion gate:

- [ ] Author can validate and package seed benchmark locally.

### 14.3 Run commands

Implement:

- [ ] `benchctl runs create --config run.yaml`
- [ ] `benchctl runs watch RUN_ID`
- [ ] `benchctl runs download RUN_ID --out artifacts/`

Completion gate:

- [ ] CLI can start a mock run and watch it finish.

### 14.4 Failure commands

Implement:

- [ ] `benchctl failures list`
- [ ] `benchctl failures get FAILURE_ID`
- [ ] `benchctl failures rerun FAILURE_ID --model MODEL_ID`
- [ ] `benchctl reproduce ./reproduce --model mock`

Completion gate:

- [ ] Downloaded reproduction bundle can be exercised with CLI.

## 15. Seed benchmark: `skate-trick-name-lite`

### 15.1 Create package

- [ ] Create `examples/skate-trick-name-lite`.
- [ ] Add `benchmark.yaml`.
- [ ] Add `README.md`.
- [ ] Add `LICENSE`.
- [ ] Add `docs/data-card.md`.
- [ ] Add `tasks/sample.jsonl`.
- [ ] Add `tasks/public_test.jsonl`.

### 15.2 Create tasks

- [ ] Write 25 sample tasks.
- [ ] Write 100 public test tasks.
- [ ] Each task must include:
  - [ ] Original trick description.
  - [ ] Canonical answer.
  - [ ] Aliases.
  - [ ] Difficulty.
  - [ ] Tags.
- [ ] Ensure data is original and not copied from public SkateBench.

Task tags should include some of:

- [ ] `skateboarding`
- [ ] `niche-terminology`
- [ ] `spatial-reasoning`
- [ ] `rotation`
- [ ] `flip`
- [ ] `grind`
- [ ] `manual`
- [ ] `transition`

Completion gate:

- [ ] Package validates.
- [ ] Exact/alias scorer grades fixture outputs correctly.

### 15.3 Add scorer

- [ ] Use built-in alias-match scorer if sufficient.
- [ ] Normalize case.
- [ ] Normalize punctuation.
- [ ] Normalize repeated whitespace.
- [ ] Accept configured aliases.
- [ ] Reject unrelated answers.
- [ ] Return clear explanation.

Completion gate:

- [ ] Known alias passes.
- [ ] Wrong trick fails.
- [ ] Invalid format fails as `invalid_format`.

## 16. Seed benchmark: `git-tool-use-lite`

### 16.1 Create package

- [ ] Create `examples/git-tool-use-lite`.
- [ ] Add `benchmark.yaml`.
- [ ] Add `README.md`.
- [ ] Add `LICENSE`.
- [ ] Add `docs/data-card.md`.
- [ ] Add `tasks/sample.jsonl`.
- [ ] Add `tasks/public_test.jsonl`.
- [ ] Add `assets/repos`.

### 16.2 Create repository fixtures

Create synthetic repositories for task families:

- [ ] Branch creation.
- [ ] Commit correct file.
- [ ] Clean worktree.
- [ ] Resolve simple conflict.
- [ ] Revert bad commit.
- [ ] Inspect history.
- [ ] Cherry-pick simple commit.
- [ ] Avoid modifying unrelated files.

For each fixture:

- [ ] Generate repo from script to ensure reproducibility.
- [ ] Set deterministic author name/email.
- [ ] Set deterministic commit timestamps.
- [ ] Tar and compress fixture.
- [ ] Hash fixture.
- [ ] Reference fixture from task JSONL.

Completion gate:

- [ ] Fixture generation script produces same hashes on repeated runs.

### 16.3 Create task set

- [ ] Add at least 5 sample tasks.
- [ ] Add at least 40 public test tasks.
- [ ] Include difficulty tags.
- [ ] Include expected branch state.
- [ ] Include expected commit messages.
- [ ] Include expected file assertions.
- [ ] Include forbidden modifications where appropriate.
- [ ] Include expected clean worktree flag.

Completion gate:

- [ ] Package validates.

### 16.4 Add repository-state scorer

- [ ] Inspect final branch.
- [ ] Inspect worktree.
- [ ] Inspect staged changes.
- [ ] Inspect commit history.
- [ ] Inspect file content assertions.
- [ ] Run tests if configured.
- [ ] Check forbidden commands from trace.
- [ ] Return detailed metrics.

Completion gate:

- [ ] Correct fixture scores pass.
- [ ] Wrong branch fails.
- [ ] Dirty worktree fails.
- [ ] Missing commit fails.
- [ ] Unrelated file modification fails.

## 17. Model adapters

### 17.1 Mock adapter

- [ ] Implement deterministic mock text adapter.
- [ ] Implement deterministic mock agent adapter.
- [ ] Allow task ID based canned responses.
- [ ] Use mock adapter in tests and seed demos.

Completion gate:

- [ ] End-to-end system can run without external model API keys.

### 17.2 OpenAI-compatible adapter placeholder

- [ ] Implement generic HTTP adapter for OpenAI-compatible chat completions if configured.
- [ ] Read API key from secure runtime config.
- [ ] Do not persist API key.
- [ ] Capture request metadata, not secrets.
- [ ] Capture token usage if provider returns it.
- [ ] Implement retries with exponential backoff.
- [ ] Respect timeout and cancellation.
- [ ] Add provider error mapping.

Completion gate:

- [ ] Adapter is disabled unless environment is configured.
- [ ] Missing key produces clear error.

### 17.3 Local model adapter placeholder

- [ ] Add interface for local model endpoint.
- [ ] Support base URL.
- [ ] Support model ID.
- [ ] Support timeout.
- [ ] Add clear unsupported-modality errors.

Completion gate:

- [ ] Local adapter can be configured but is not required for MVP tests.

## 18. Security hardening

### 18.1 Upload security

- [ ] Enforce upload size limit.
- [ ] Enforce package size limit.
- [ ] Enforce asset size limit.
- [ ] Reject unsafe paths.
- [ ] Reject symlink escapes.
- [ ] Scan MIME types.
- [ ] Store original uploads outside public web root.
- [ ] Sanitize validation report rendering.

Completion gate:

- [ ] Malicious package fixtures are rejected.

### 18.2 Sandbox security

- [ ] Run container as non-root.
- [ ] Drop Linux capabilities.
- [ ] Disable privilege escalation.
- [ ] Do not mount Docker socket.
- [ ] Mount benchmark package read-only.
- [ ] Mount workspace read-write only.
- [ ] Disable network by default.
- [ ] Enforce CPU/memory/disk limits.
- [ ] Enforce wall-clock timeout.
- [ ] Scrub environment variables before scorer/agent execution.
- [ ] Inject provider keys only into model adapter process when required.
- [ ] Add denied command filter for shell tool.

Completion gate:

- [ ] Scorer cannot read host files.
- [ ] Agent cannot access network when disabled.
- [ ] Denied command test passes.

### 18.3 UI security

- [ ] Escape model outputs.
- [ ] Sanitize Markdown.
- [ ] Add Content Security Policy.
- [ ] Use signed URLs for private artifacts.
- [ ] Prevent reflected/stored XSS from task inputs, model outputs, and scorer explanations.
- [ ] Add tests for script injection strings.

Completion gate:

- [ ] XSS test payload renders as inert text.

### 18.4 Secrets and logs

- [ ] Add secret redaction utility.
- [ ] Redact API keys from logs.
- [ ] Redact common token patterns.
- [ ] Redact `.env` content if accidentally printed.
- [ ] Prevent raw request headers from being persisted.
- [ ] Add tests with fake secrets.

Completion gate:

- [ ] Fake secret strings do not appear in persisted logs.

## 19. Moderation and governance

### 19.1 Review workflow

- [ ] Benchmark version enters `pending_review` after validation.
- [ ] Reviewer can inspect manifest.
- [ ] Reviewer can inspect validation report.
- [ ] Reviewer can inspect source disclosure.
- [ ] Reviewer can inspect risk class.
- [ ] Reviewer can approve/reject/request changes.
- [ ] Decision is stored in `reviews`.
- [ ] Decision is written to `audit_logs`.

Completion gate:

- [ ] Public catalog only shows released benchmarks.

### 19.2 Risk review rules

- [ ] Low-risk benchmarks can be approved after automated validation.
- [ ] Medium-risk benchmarks require reviewer approval.
- [ ] High-risk benchmarks require reviewer approval and explicit risk notes.
- [ ] Restricted benchmarks cannot be publicly released in MVP.
- [ ] Medical imaging benchmarks require high-risk review.
- [ ] Benchmarks with unclear copyright/data rights require rejection or changes.

Completion gate:

- [ ] Restricted benchmark upload cannot become public.

### 19.3 Takedown workflow

- [ ] Add admin action to unpublish benchmark.
- [ ] Add admin action to unpublish failure case.
- [ ] Add hard delete path for illegal/private data.
- [ ] Preserve audit log for administrative actions.
- [ ] Add public "report issue" link.

Completion gate:

- [ ] Admin can remove public visibility without deleting all metadata.

## 20. Testing

### 20.1 Unit test checklist

- [ ] Manifest schema validation.
- [ ] Task JSONL parser.
- [ ] Asset reference validation.
- [ ] Hash canonicalization.
- [ ] Built-in scorers.
- [ ] Aggregation math.
- [ ] Failure-mode mapping.
- [ ] Authorization helpers.
- [ ] Storage key generation.
- [ ] Secret redaction.
- [ ] Run state transitions.

Completion gate:

- [ ] Unit tests run in CI.

### 20.2 Integration test checklist

- [ ] Create user.
- [ ] Create benchmark draft.
- [ ] Upload valid package.
- [ ] Upload invalid package.
- [ ] Validate package.
- [ ] Approve release.
- [ ] Create run.
- [ ] Execute mock text run.
- [ ] Execute mock Git run.
- [ ] Store artifacts.
- [ ] Score run.
- [ ] Refresh leaderboard.
- [ ] Promote failure.
- [ ] Build reproduction bundle.

Completion gate:

- [ ] Integration tests run against Docker Compose services.

### 20.3 End-to-end test checklist

Use Playwright or equivalent.

- [ ] Anonymous user browses catalog.
- [ ] User signs in.
- [ ] User uploads benchmark package.
- [ ] User sees validation report.
- [ ] Reviewer approves release.
- [ ] User starts run.
- [ ] User watches run complete.
- [ ] User opens leaderboard row.
- [ ] User opens failed task.
- [ ] User promotes failure case.
- [ ] User downloads reproduction bundle.

Completion gate:

- [ ] E2E test passes in CI or nightly workflow.

### 20.4 Security test checklist

- [ ] Zip-slip upload.
- [ ] Symlink escape upload.
- [ ] Oversized upload.
- [ ] Malicious Markdown.
- [ ] Model output with script tag.
- [ ] Scorer network access attempt.
- [ ] Scorer host filesystem access attempt.
- [ ] Agent denied command attempt.
- [ ] Fake secret leakage.
- [ ] Unauthorized API access.

Completion gate:

- [ ] Security tests are included in CI before public beta.

## 21. CI/CD

### 21.1 CI workflow

- [ ] Add GitHub Actions or equivalent CI.
- [ ] Install dependencies.
- [ ] Run lint.
- [ ] Run typecheck.
- [ ] Run unit tests.
- [ ] Build packages.
- [ ] Build web app.
- [ ] Run integration tests with services.
- [ ] Upload test artifacts on failure.

Completion gate:

- [ ] CI passes on main branch.

### 21.2 Docker images

- [ ] Add Dockerfile for web/API.
- [ ] Add Dockerfile for runner worker.
- [ ] Add Dockerfile for scorer worker.
- [ ] Add sandbox base image.
- [ ] Pin base image versions.
- [ ] Generate image digests.
- [ ] Add vulnerability scan if available.

Completion gate:

- [ ] Images build locally.
- [ ] Runner image digest is stored in run metadata.

### 21.3 Deployment config

- [ ] Add production environment variable documentation.
- [ ] Add migration deployment step.
- [ ] Add object storage bucket setup docs.
- [ ] Add Redis setup docs.
- [ ] Add worker scaling docs.
- [ ] Add backup/restore docs for DB.
- [ ] Add lifecycle policy docs for run artifacts.

Completion gate:

- [ ] A fresh environment can be deployed from docs.

## 22. Documentation

### 22.1 User docs

- [ ] Write `docs/getting-started.md`.
- [ ] Write `docs/create-a-benchmark.md`.
- [ ] Write `docs/run-a-benchmark.md`.
- [ ] Write `docs/read-leaderboards.md`.
- [ ] Write `docs/failure-cases.md`.
- [ ] Write `docs/verification.md`.

Completion gate:

- [ ] New user can run seed benchmark from docs.

### 22.2 Developer docs

- [ ] Write `docs/architecture.md`.
- [ ] Write `docs/benchmark-spec.md`.
- [ ] Write `docs/scorer-api.md`.
- [ ] Write `docs/runner-security.md`.
- [ ] Write `docs/local-development.md`.
- [ ] Write `docs/contributing.md`.

Completion gate:

- [ ] New developer can run app locally from docs.

### 22.3 Policy docs

- [ ] Write `docs/data-policy.md`.
- [ ] Write `docs/moderation-policy.md`.
- [ ] Write `docs/medical-content-policy.md`.
- [ ] Write `docs/leaderboard-policy.md`.
- [ ] Write `docs/no-endorsement-notice.md`.

Completion gate:

- [ ] Public release has clear rules for data, scoring, and endorsement.

## 23. Alpha release checklist

Alpha means local/demo quality, not public production.

- [ ] Repository bootstrapped.
- [ ] DB schema implemented.
- [ ] Benchmark spec implemented.
- [ ] Package validation works locally.
- [ ] Object storage works locally.
- [ ] Mock text runner works.
- [ ] Mock Git runner works.
- [ ] Built-in scorers work.
- [ ] Seed `skate-trick-name-lite` validates.
- [ ] Seed `git-tool-use-lite` validates.
- [ ] Runs can complete locally.
- [ ] Failures can be captured locally.
- [ ] Basic web catalog exists.
- [ ] Basic run detail page exists.
- [ ] README explains how to run demo.

Alpha completion gate:

- [ ] A developer can clone the repo, run local infrastructure, seed DB, run both seed benchmarks with mock adapters, and inspect results in the browser.

## 24. Private beta checklist

Private beta means authenticated users and reviewer-gated benchmark publishing.

- [ ] Auth works.
- [ ] API tokens work.
- [ ] Benchmark upload UI works.
- [ ] Validation jobs work.
- [ ] Review workflow works.
- [ ] Release immutability works.
- [ ] Runner worker processes queued jobs.
- [ ] Scorer worker processes custom scorer jobs.
- [ ] Leaderboards work.
- [ ] Failure archive works.
- [ ] Reproduction bundles work.
- [ ] Basic security tests pass.
- [ ] Basic observability exists.
- [ ] Docs cover authoring and running benchmarks.

Private beta completion gate:

- [ ] An invited user can upload a benchmark, get it approved, run it, publish a self-reported result, and preserve a failure case.

## 25. Public beta checklist

Public beta means the system can accept real community traffic with guardrails.

- [ ] Rate limits enabled.
- [ ] Upload limits enabled.
- [ ] Cost budgets enabled.
- [ ] Takedown workflow enabled.
- [ ] Admin console usable.
- [ ] Verification labels visible.
- [ ] Public no-endorsement notice visible where relevant.
- [ ] Security tests pass in CI.
- [ ] Backups configured.
- [ ] Object storage lifecycle rules configured.
- [ ] Error monitoring configured.
- [ ] Abuse reporting link present.
- [ ] Policy docs published.
- [ ] Public API documented.
- [ ] CLI install path documented.

Public beta completion gate:

- [ ] A public user can browse benchmarks, inspect methodology, start an allowed run, view leaderboard entries, and inspect public failure cases without accessing private data or secrets.

## 26. Suggested implementation order

Follow this order to minimize rework:

1. [ ] Repository bootstrap.
2. [ ] Local infrastructure.
3. [ ] DB schema.
4. [ ] Benchmark spec and validation.
5. [ ] Seed benchmarks.
6. [ ] Built-in scorers.
7. [ ] Mock runner.
8. [ ] Run API.
9. [ ] Runner worker.
10. [ ] Object storage artifacts.
11. [ ] Basic web catalog.
12. [ ] Run creation/detail UI.
13. [ ] Leaderboards.
14. [ ] Failure-case archive.
15. [ ] Reproduction bundles.
16. [ ] Auth and authorization.
17. [ ] Review/admin UI.
18. [ ] CLI.
19. [ ] Security hardening.
20. [ ] CI/CD.
21. [ ] Documentation.
22. [ ] Private beta polish.
23. [ ] Public beta guardrails.

## 27. Definition of done for the whole project

The implementation is done for MVP when all of the following are true:

- [ ] `pnpm install` works from a clean clone.
- [ ] `docker compose up -d` starts local dependencies.
- [ ] `pnpm db:migrate && pnpm db:seed` works.
- [ ] `pnpm test` passes.
- [ ] `pnpm lint` passes.
- [ ] `pnpm typecheck` passes.
- [ ] `pnpm build` passes.
- [ ] User can sign in.
- [ ] User can upload a benchmark package.
- [ ] Package validation is safe and informative.
- [ ] Reviewer can release a benchmark version.
- [ ] Released benchmark versions are immutable.
- [ ] User can run a benchmark with mock model/agent.
- [ ] Text seed benchmark completes.
- [ ] Git seed benchmark completes.
- [ ] Per-task results are stored.
- [ ] Aggregate score is computed.
- [ ] Cost/latency/token fields exist even if mock values are zero.
- [ ] Leaderboard entry appears for verified run.
- [ ] Failed task can be promoted to failure case.
- [ ] Reproduction bundle can be downloaded.
- [ ] Public UI distinguishes verified, self-reported, imported, and experimental results.
- [ ] No untrusted scorer or agent code runs in the web/API process.
- [ ] Network is disabled by default in runner/scorer sandboxes.
- [ ] Model outputs are sanitized in UI.
- [ ] Secrets are redacted from logs.
- [ ] Documentation explains how to author a new benchmark.
- [ ] Documentation explains how to run the two seed benchmarks.
