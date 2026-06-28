# Design: Community AI Benchmark Platform

## 1. Purpose

Build a public platform and runner system for community-authored AI benchmarks. The platform should let non-lab people define, publish, run, score, compare, and preserve benchmarks across strange, niche, practical, multimodal, and agentic domains.

The product goal is not to create one benchmark. The product goal is to make it easy to create many reproducible benchmarks, including benchmarks that demonstrate current model and agent failure modes.

Working project name in this document: `community-bench`. Rename before release.

## 2. Source context

Primary brief supplied by the requester:

- Community-driven AI benchmarks, not just lab-authored benchmarks.
- Quirky cross-domain benchmarks such as SkateBench: name a skateboarding trick from a technical description.
- Agent tool-proficiency benchmarks such as GitBench.
- Failure-case preservation: store reproducible failed AI attempts so they can be retried later.
- Benchmarks for obscure domains, real work, and strange hypotheses.
- Benchmarks that expose areas where all agents are bad.

Related public examples to use as design references, not as copied implementation:

- SkateBench: https://skatebench.t3.gg/
- SkateBench repository: https://github.com/T3-Content/skatebench
- SWE-bench: https://www.swebench.com/
- Theo links from brief:
  - https://x.com/theo/status/2069621429189161350
  - https://www.youtube.com/watch?v=wEAb0x3wTRc

Important branding/legal constraint:

- Do not imply Theo endorsement.
- Do not use Theo's name, likeness, branding, or social handles in the product name, logo, metadata, marketing claims, or Open Graph text unless explicit permission is obtained.
- It is acceptable to include a neutral acknowledgement in internal docs: "Idea inspired by public commentary; no endorsement."

## 3. Product summary

`community-bench` has five core capabilities:

1. **Benchmark registry**
   - Public catalog of benchmarks.
   - Each benchmark has immutable releases, metadata, task definitions, scorers, licenses, and governance status.

2. **Benchmark authoring**
   - A file-based benchmark package format that contributors can submit through Git or the web UI.
   - Validation tools for schema correctness, data integrity, reproducibility, scoring, and safety.

3. **Evaluation runner**
   - Isolated execution workers that run models and agents against benchmark tasks.
   - Supports text-only, multimodal, repository-based, shell/tool-use, and custom domain benchmarks.
   - Stores traces, tool calls, prompts, outputs, logs, costs, latency, and artifacts.

4. **Scoring and leaderboards**
   - Objective metrics first: exact match, unit tests, repository tests, structured validators, image labels, programmatic scorers.
   - Optional human or model-judge scoring with disclosure and audit trails.
   - Public leaderboards with verified and unverified result states.

5. **Failure-case archive**
   - Every failed attempt can be promoted into a persistent, reproducible failure case.
   - Failure cases include input, expected behavior, actual output, environment, model/agent metadata, logs, and reproduction bundle.

## 4. Design principles

### 4.1 Reproducibility over vibes

Every public score must be tied to immutable versions of:

- Benchmark package.
- Task split.
- Scorer code.
- Runner image.
- Agent scaffold.
- Model identifier and provider.
- Prompt template.
- Tool permissions.
- Hyperparameters and sampling parameters.
- Random seed where applicable.
- Environment variables, excluding secrets.
- Cost and token accounting method.
- Start/end timestamps.
- Hardware/compute class where relevant.

### 4.2 Benchmarks should be easy to author but hard to fake

The author experience should be lightweight:

- A folder with `benchmark.yaml`, `tasks.jsonl`, optional assets, and optional scorer code.
- A local CLI command to validate and run a sample.
- A web UI that explains errors clearly.

The verification bar should remain strict:

- Immutable release artifacts.
- Content hashes.
- Sandboxed scorer execution.
- Required licenses.
- Required source disclosures.
- Moderation for unsafe, copyrighted, private, or medically sensitive data.
- Public distinction between verified and unverified leaderboard entries.

### 4.3 Quirky domains are first-class

The schema must not assume benchmarks are only academic QA. It must support:

- Niche terminology tests.
- Spatial reasoning from text.
- Domain-specific classification.
- Medical image triage benchmarks, with explicit safety constraints.
- Aerial/satellite image recognition.
- Programming language niche tasks such as Crystal, Zig, Nix, Elixir, Raku, or domain-specific languages.
- End-to-end agent tasks using shell, Git, browsers, filesystems, APIs, and custom tools.
- "Agents are bad at this" failure collections.

### 4.4 Scores must expose tradeoffs

Leaderboards should not only display one score. They should also show:

- Accuracy/pass rate.
- Cost.
- Latency.
- Token usage.
- Number of tool calls.
- Failure-mode distribution.
- Confidence interval where repeated runs are available.
- Environment constraints.
- Whether the result is verified, self-reported, or imported.
- Whether the run used a full split, public split, private holdout, or sample split.

### 4.5 Failure data is a product surface, not a log afterthought

Failed attempts are the most useful asset. Preserve them in a queryable form:

- "Show me all GitBench failures caused by incorrect branch state."
- "Show me all MRI benchmark cases where the answer was correct but the explanation hallucinated."
- "Show me models that pass easy tasks but fail tasks tagged `spatial-reasoning`."
- "Rerun all failures from model X against model Y."

## 5. Scope

## 5.1 MVP scope

The MVP should implement:

- User authentication.
- Public benchmark catalog.
- Benchmark package upload/import.
- Benchmark validation.
- Immutable benchmark versions.
- Task storage and asset storage.
- Text benchmark runner.
- Agent benchmark runner with a restricted shell and Git support.
- Programmatic scorers.
- Run creation and status tracking.
- Run logs and artifacts.
- Leaderboards.
- Failure-case archive.
- Admin review tools.
- Two seed benchmarks:
  - `skate-trick-name-lite`: text-to-label benchmark inspired by SkateBench, using fresh non-copyrighted toy data.
  - `git-tool-use-lite`: agent benchmark that tests Git operations in small synthetic repositories.

## 5.2 Explicit non-goals for MVP

- No clinical medical decision support.
- No paid benchmark marketplace.
- No arbitrary internet-browsing agents by default.
- No hidden proprietary lab results unless voluntarily submitted.
- No training-data contamination detection beyond source disclosures, private splits, and hash-based duplicate detection.
- No guarantee that community benchmark scores represent broad intelligence.
- No endorsement claims from Theo, labs, or model providers.

## 5.3 Later scope

- Human annotation marketplace or reviewer pools.
- Benchmark bounties.
- Private organization workspaces.
- Browser-use benchmarks.
- MCP/tool registry integration.
- Model-provider billing integration.
- Scheduled reruns.
- Differential regression alerts.
- Public dataset mirrors.
- Dataset cards and automated data provenance reports.
- Pairwise battle arenas for subjective outputs.
- Advanced contamination analysis using embedding similarity and web-scale search.

## 6. Users and permissions

## 6.1 Personas

### Benchmark author

Creates and maintains benchmark definitions.

Needs:

- Easy package format.
- Local validation.
- Clear docs and examples.
- Versioning and release workflow.
- Public credit and citations.

### Model or agent evaluator

Runs a model or agent against benchmarks.

Needs:

- Repeatable run configuration.
- Ability to bring API keys securely.
- Clear run status.
- Raw traces and scoring details.
- Public/private result controls.

### Reviewer/moderator

Reviews benchmark submissions and suspicious results.

Needs:

- Diff view between benchmark versions.
- Schema validation output.
- License and data-source flags.
- Scorer inspection.
- Sandbox risk flags.
- Ability to approve, reject, or request changes.

### Researcher/lab/user

Reads leaderboards and failure cases.

Needs:

- Clear methodology.
- Filters by domain, model, tool setup, cost, and benchmark split.
- Downloadable run artifacts.
- Stable citations.

## 6.2 Role matrix

| Capability | Anonymous | User | Author | Org Admin | Reviewer | System Admin |
|---|---:|---:|---:|---:|---:|---:|
| View public benchmarks | Yes | Yes | Yes | Yes | Yes | Yes |
| View public leaderboards | Yes | Yes | Yes | Yes | Yes | Yes |
| View public failure cases | Yes | Yes | Yes | Yes | Yes | Yes |
| Create benchmark draft | No | Yes | Yes | Yes | Yes | Yes |
| Publish benchmark release | No | No | Own benchmarks | Org benchmarks | With approval | Yes |
| Submit run | No | Yes | Yes | Yes | Yes | Yes |
| Publish verified run | No | No | No | No | Yes | Yes |
| Moderate benchmark | No | No | No | No | Yes | Yes |
| Delete illegal/private data | No | No | No | No | Yes | Yes |
| Manage system config | No | No | No | No | No | Yes |

## 7. Core domain model

## 7.1 Entities

### User

Represents a person who signs in.

Key fields:

- `id`
- `email`
- `display_name`
- `handle`
- `avatar_url`
- `role`
- `created_at`
- `updated_at`

### Organization

Group for shared benchmark ownership.

Key fields:

- `id`
- `slug`
- `name`
- `description`
- `created_at`
- `updated_at`

### Benchmark

Mutable top-level concept. Metadata can change, but scoring data points to immutable versions.

Key fields:

- `id`
- `slug`
- `owner_user_id`
- `owner_org_id`
- `title`
- `summary`
- `domain`
- `tags`
- `visibility`
- `status`: `draft | pending_review | public | archived | rejected`
- `risk_class`: `low | medium | high | restricted`
- `created_at`
- `updated_at`

### BenchmarkVersion

Immutable release of a benchmark package.

Key fields:

- `id`
- `benchmark_id`
- `version`
- `package_hash`
- `manifest_hash`
- `task_count`
- `public_task_count`
- `private_task_count`
- `scorer_hash`
- `runner_requirements_hash`
- `release_notes`
- `status`: `draft | validating | pending_review | released | deprecated | rejected`
- `created_by_user_id`
- `released_at`
- `created_at`

### Task

An individual benchmark instance within a version.

Key fields:

- `id`
- `benchmark_version_id`
- `task_key`
- `split`: `sample | dev | public_test | private_test | hidden_holdout`
- `input_json`
- `expected_json`
- `metadata_json`
- `asset_refs`
- `content_hash`
- `created_at`

### Asset

File referenced by a task or run.

Key fields:

- `id`
- `storage_key`
- `sha256`
- `mime_type`
- `size_bytes`
- `visibility`
- `created_at`

### Scorer

Program or built-in method that grades task outputs.

Key fields:

- `id`
- `benchmark_version_id`
- `scorer_type`: `exact_match | regex | json_schema | unit_tests | python | typescript | llm_judge | human`
- `entrypoint`
- `config_json`
- `code_hash`
- `created_at`

### Model

Logical model being evaluated.

Key fields:

- `id`
- `provider`
- `model_id`
- `display_name`
- `release_date`
- `model_family`
- `open_weights`
- `notes`

### AgentScaffold

Wrapper/tooling around a model.

Examples:

- Basic chat completion wrapper.
- Shell agent.
- Git agent.
- Browser agent.
- Custom tool agent.

Key fields:

- `id`
- `name`
- `version`
- `repo_url`
- `commit_sha`
- `container_image`
- `tool_permissions_json`
- `created_at`

### Run

One evaluation run against one benchmark version and split.

Key fields:

- `id`
- `benchmark_version_id`
- `split`
- `model_id`
- `agent_scaffold_id`
- `submitted_by_user_id`
- `status`: `queued | running | scoring | completed | failed | cancelled`
- `verification_status`: `unverified | self_reported | verified | rejected`
- `run_config_json`
- `environment_hash`
- `prompt_hash`
- `started_at`
- `completed_at`
- `primary_score`
- `cost_usd`
- `latency_ms_p50`
- `latency_ms_p95`
- `total_tokens_in`
- `total_tokens_out`
- `total_tool_calls`
- `error_message`
- `created_at`

### RunTaskResult

Result for one task inside a run.

Key fields:

- `id`
- `run_id`
- `task_id`
- `status`: `queued | running | passed | failed | errored | timed_out | skipped`
- `raw_output_json`
- `normalized_output_json`
- `score_json`
- `score`
- `cost_usd`
- `latency_ms`
- `tokens_in`
- `tokens_out`
- `tool_calls_count`
- `trace_asset_id`
- `stdout_asset_id`
- `stderr_asset_id`
- `artifact_refs`
- `failure_mode`
- `created_at`

### FailureCase

Promoted or automatically captured failure.

Key fields:

- `id`
- `run_task_result_id`
- `benchmark_version_id`
- `task_id`
- `model_id`
- `agent_scaffold_id`
- `title`
- `summary`
- `failure_mode`
- `reproduction_bundle_asset_id`
- `is_public`
- `tags`
- `created_by_user_id`
- `created_at`

### LeaderboardEntry

Denormalized view for quick leaderboard rendering.

Key fields:

- `id`
- `benchmark_version_id`
- `split`
- `run_id`
- `model_id`
- `agent_scaffold_id`
- `primary_score`
- `rank`
- `cost_usd`
- `latency_ms_p50`
- `verification_status`
- `published_at`

### Review

Review record for benchmark releases or runs.

Key fields:

- `id`
- `subject_type`: `benchmark_version | run | failure_case`
- `subject_id`
- `reviewer_user_id`
- `decision`: `approved | rejected | needs_changes`
- `comments`
- `created_at`

### AuditLog

Security and moderation audit trail.

Key fields:

- `id`
- `actor_user_id`
- `action`
- `target_type`
- `target_id`
- `metadata_json`
- `created_at`

## 8. Benchmark package specification

## 8.1 Package layout

A benchmark package is a directory or zip file.

```txt
my-benchmark/
  benchmark.yaml
  README.md
  LICENSE
  tasks/
    sample.jsonl
    public_test.jsonl
    private_test.jsonl            # optional; not public by default
  assets/
    images/
    repos/
    audio/
    misc/
  scorers/
    score.py                      # optional custom scorer
    package.json                  # optional TypeScript scorer
    pyproject.toml                # optional Python dependencies
  runners/
    adapter.ts                    # optional custom adapter
  docs/
    data-card.md
    scoring.md
```

## 8.2 `benchmark.yaml`

Example:

```yaml
schema_version: "1.0"
id: "git-tool-use-lite"
title: "Git Tool Use Lite"
summary: "Synthetic agent benchmark for basic Git operations."
description: >
  Tests whether an agent can inspect repository state, create branches,
  stage correct files, commit with required metadata, resolve conflicts,
  and avoid destructive Git commands.
domain: "developer-tools"
tags:
  - agent
  - git
  - shell
  - tool-use
  - reproducibility
license: "MIT"
authors:
  - name: "Community Bench Team"
    url: "https://example.com"
source_disclosure:
  generated: true
  human_written: true
  external_sources: []
risk_class: "low"
task_type: "agent_tool_use"
input_modalities:
  - text
  - repository
output_type: "repository_state"
output_schema:
  type: object
  required:
    - final_message
scoring:
  primary_metric: "pass_rate"
  metrics:
    - id: "pass_rate"
      type: "unit_tests"
      weight: 1.0
    - id: "git_hygiene"
      type: "custom"
      weight: 0.2
  scorer:
    type: "python"
    entrypoint: "scorers/score.py"
sandbox:
  network: "disabled"
  max_runtime_seconds_per_task: 180
  max_memory_mb: 1024
  max_disk_mb: 2048
  allowed_tools:
    - shell
    - git
splits:
  sample:
    path: "tasks/sample.jsonl"
    public: true
  public_test:
    path: "tasks/public_test.jsonl"
    public: true
  private_test:
    path: "tasks/private_test.jsonl"
    public: false
versioning:
  release_strategy: "immutable"
  suggested_initial_version: "0.1.0"
```

## 8.3 Task JSONL format

Each line is one task.

Text/classification example:

```json
{
  "id": "skate_0001",
  "input": {
    "prompt": "A rider pops the board, flips it one full kickflip rotation, and spins the body 180 degrees frontside before landing."
  },
  "expected": {
    "answer": "frontside flip",
    "aliases": ["frontside kickflip"]
  },
  "metadata": {
    "difficulty": "medium",
    "tags": ["skateboarding", "niche-terminology", "spatial-reasoning"]
  }
}
```

Agent/Git example:

```json
{
  "id": "git_0001",
  "input": {
    "instruction": "Create a branch named fix/readme-title, update README.md so the H1 is 'Widget CLI', commit the change with message 'docs: fix readme title', and leave the repository clean.",
    "repo_asset": "assets/repos/git_0001.tar.zst"
  },
  "expected": {
    "branch": "fix/readme-title",
    "commit_message": "docs: fix readme title",
    "clean_worktree": true,
    "file_assertions": [
      {
        "path": "README.md",
        "contains": "# Widget CLI"
      }
    ]
  },
  "metadata": {
    "difficulty": "easy",
    "tags": ["git", "branch", "commit", "worktree"]
  }
}
```

Multimodal/image example:

```json
{
  "id": "aerial_0001",
  "input": {
    "prompt": "Identify the primary visible land-use pattern.",
    "assets": ["assets/images/aerial_0001.png"]
  },
  "expected": {
    "label": "solar_farm",
    "aliases": ["solar array", "photovoltaic farm"]
  },
  "metadata": {
    "difficulty": "medium",
    "tags": ["aerial-imagery", "classification"]
  }
}
```

## 8.4 Required metadata rules

Every benchmark version must include:

- License.
- Data provenance statement.
- Whether examples are generated, scraped, donated, synthetic, expert-authored, or imported.
- Whether any private or sensitive data is present.
- Risk class.
- Scoring method.
- Output schema.
- Time/memory/disk/network requirements.
- Author contact or maintainer handle.
- Changelog/release notes.

## 8.5 Risk classes

| Risk class | Meaning | Allowed in MVP |
|---|---|---:|
| `low` | Toy, synthetic, non-sensitive data | Yes |
| `medium` | Real-world but non-sensitive public data | Yes |
| `high` | Domain-sensitive data, possible copyrighted content, medical/legal/financial content | Review only |
| `restricted` | Private, personal, regulated, unsafe, or legally ambiguous data | No public release in MVP |

Medical imaging benchmarks must be `high` at minimum and must include:

- De-identification statement.
- Source license.
- Expert review statement.
- Clear disclaimer that results are not clinical advice.
- No patient identifiers.
- Manual reviewer approval before publication.

## 9. Scoring design

## 9.1 Scorer types

### Built-in scorers

- `exact_match`
- `case_insensitive_match`
- `alias_match`
- `regex`
- `json_schema`
- `numeric_tolerance`
- `multiple_choice`
- `unit_tests`
- `repository_state`
- `image_label`
- `tool_trace_assertions`

### Custom scorers

Custom scorers can be Python or TypeScript.

Required contract:

Input:

```json
{
  "task": {},
  "model_output": {},
  "artifacts": [],
  "run_config": {},
  "environment": {}
}
```

Output:

```json
{
  "score": 1.0,
  "passed": true,
  "metrics": {
    "exact_match": 1.0,
    "format_valid": 1.0
  },
  "failure_mode": null,
  "explanation": "Matched canonical answer."
}
```

Rules:

- Scorer must be deterministic for the same inputs.
- Scorer must not use network access.
- Scorer must not read secrets.
- Scorer must run in a separate sandbox.
- Scorer must return machine-readable JSON.
- Scorer failures should not silently become task failures. They should be marked `errored`.

### LLM-as-judge scoring

Allowed but not preferred. Must disclose:

- Judge model.
- Judge prompt.
- Temperature and decoding parameters.
- Number of judge samples.
- Rubric.
- Calibration set if any.
- Whether human audit was performed.

Leaderboard entries using LLM judges should show a visible "judge-scored" badge.

## 9.2 Aggregation

Default aggregation:

```txt
primary_score = sum(task_score * task_weight) / sum(task_weight)
```

For pass/fail tasks:

```txt
pass_rate = passed_tasks / total_tasks
```

Cost:

```txt
total_cost_usd = sum(task_cost_usd)
cost_per_success = total_cost_usd / max(passed_tasks, 1)
```

Latency:

- Store per-task latency.
- Display p50, p95, max.
- Do not compare latency across incompatible hardware/tooling without disclosure.

Repeated runs:

- Allow `n` repeated attempts per task.
- Store each attempt separately.
- Report pass@1, pass@k, and mean score where applicable.
- Leaderboard must label stochastic or multi-attempt results clearly.

## 10. Runner design

## 10.1 Runner responsibilities

The runner:

1. Loads benchmark version and selected split.
2. Creates isolated task environments.
3. Invokes model or agent according to run config.
4. Captures outputs, traces, tool calls, logs, and artifacts.
5. Normalizes output.
6. Sends result to scorer.
7. Stores per-task results.
8. Updates run status.
9. Emits progress events.

The runner should not:

- Trust benchmark package code.
- Run untrusted scorer code in the API server process.
- Expose platform secrets to benchmark code.
- Depend on local mutable state.
- Publish leaderboard results directly without validation.

## 10.2 Runner modes

### Text/model mode

For classic prompt-response tasks.

Process:

1. Build prompt from task input and benchmark prompt template.
2. Call model provider or local model adapter.
3. Capture raw output.
4. Parse/normalize output if output schema requires it.
5. Score.

### Multimodal mode

For tasks with images/audio/video/PDFs.

Process:

1. Resolve asset references.
2. Pass assets to model adapter if provider supports them.
3. Store provider payload metadata and content hashes.
4. Score with built-in or custom scorer.

### Agent mode

For tool-use tasks.

Process:

1. Unpack task environment into sandbox.
2. Provide instruction and allowed tools.
3. Run agent loop until done, timeout, or budget exhaustion.
4. Capture every message, tool call, stdout, stderr, file diff, and final answer.
5. Score final state.

### Repository/Git mode

Specialized agent mode for GitBench-like tasks.

Process:

1. Unpack repository tarball.
2. Initialize isolated Git repository.
3. Optionally set remote to a local fake remote.
4. Execute agent with shell/Git tools.
5. Record final branch, commits, worktree status, diffs, and logs.
6. Run scorer assertions.

## 10.3 Tool permissions

Tool permissions are explicit and versioned.

Example:

```yaml
tools:
  shell:
    enabled: true
    allowed_commands:
      - git
      - ls
      - cat
      - sed
      - awk
      - python
      - node
    denied_commands:
      - rm -rf /
      - curl
      - wget
      - ssh
  filesystem:
    enabled: true
    root: "/workspace"
    write: true
  network:
    enabled: false
  browser:
    enabled: false
```

## 10.4 Sandbox constraints

Minimum sandbox constraints:

- Non-root user.
- Read-only mounted benchmark package.
- Writable task workspace only.
- No Docker socket.
- No host filesystem mounts.
- CPU limit.
- Memory limit.
- Disk quota.
- Wall-clock timeout.
- Network disabled by default.
- Egress allowlist only when benchmark requires it.
- Per-run secret injection only into model adapter, not task/scorer code.
- Logs scrubbed for secrets before persistence.

Recommended implementation path:

- MVP local/dev: Docker containers with strict flags.
- Production: Firecracker, gVisor, Kata Containers, Modal sandbox, or equivalent isolated compute.
- Do not run arbitrary community code directly in the web/API container.

## 11. Run configuration

A run config should be serializable and hashable.

Example:

```yaml
schema_version: "1.0"
benchmark:
  slug: "git-tool-use-lite"
  version: "0.1.0"
  split: "public_test"
model:
  provider: "openai-compatible"
  model_id: "example-model"
  display_name: "Example Model"
agent:
  scaffold: "basic-git-agent"
  scaffold_version: "0.1.0"
prompt:
  template_id: "default"
  template_version: "0.1.0"
sampling:
  temperature: 0
  top_p: 1
  max_output_tokens: 4096
limits:
  max_tasks: null
  max_cost_usd: 25
  max_runtime_seconds_per_task: 180
  max_total_runtime_seconds: 7200
tools:
  shell: true
  git: true
  network: false
publication:
  publish_artifacts: true
  request_verified_leaderboard_entry: true
```

## 12. API design

Use REST for public APIs and either REST or tRPC internally. Keep public API stable and versioned under `/api/v1`.

## 12.1 Auth

- `POST /api/v1/auth/session`
- `DELETE /api/v1/auth/session`
- OAuth sign-in can be implemented via Auth.js/NextAuth.
- API tokens for CLI and CI use.

## 12.2 Benchmarks

- `GET /api/v1/benchmarks`
  - Query params: `domain`, `tag`, `status`, `q`, `owner`, `riskClass`.
- `POST /api/v1/benchmarks`
  - Create draft benchmark metadata.
- `GET /api/v1/benchmarks/:slug`
  - Read benchmark metadata and latest released version.
- `PATCH /api/v1/benchmarks/:slug`
  - Update mutable metadata.
- `POST /api/v1/benchmarks/:slug/package`
  - Upload package zip.
- `POST /api/v1/benchmarks/:slug/validate`
  - Start validation job.
- `POST /api/v1/benchmarks/:slug/releases`
  - Create immutable release after validation.
- `GET /api/v1/benchmarks/:slug/versions`
  - List versions.
- `GET /api/v1/benchmarks/:slug/versions/:version`
  - Read version metadata.

## 12.3 Runs

- `POST /api/v1/runs`
  - Create evaluation run.
- `GET /api/v1/runs/:runId`
  - Read run summary.
- `GET /api/v1/runs/:runId/events`
  - Server-sent event stream.
- `GET /api/v1/runs/:runId/tasks`
  - List task results.
- `GET /api/v1/runs/:runId/tasks/:taskResultId`
  - Read one task result.
- `POST /api/v1/runs/:runId/cancel`
  - Cancel queued/running run.
- `POST /api/v1/runs/:runId/publish`
  - Request publication or verification.

## 12.4 Leaderboards

- `GET /api/v1/leaderboards/:benchmarkSlug`
- `GET /api/v1/leaderboards/:benchmarkSlug/:version`
- Query params:
  - `split`
  - `verifiedOnly`
  - `openWeightsOnly`
  - `agentScaffold`
  - `metric`
  - `costMax`
  - `dateFrom`
  - `dateTo`

## 12.5 Failure cases

- `GET /api/v1/failures`
- `POST /api/v1/failures`
  - Promote a failed `RunTaskResult`.
- `GET /api/v1/failures/:failureId`
- `POST /api/v1/failures/:failureId/rerun`
- `PATCH /api/v1/failures/:failureId`
- `DELETE /api/v1/failures/:failureId`
  - Soft-delete or unpublish. Hard delete for illegal/private data only.

## 12.6 Reviews/admin

- `GET /api/v1/reviews/queue`
- `POST /api/v1/reviews/:subjectType/:subjectId/decision`
- `GET /api/v1/audit-log`
- `POST /api/v1/admin/takedown`

## 13. Web UI design

## 13.1 Routes

```txt
/
  Landing page.
  Explain purpose, featured benchmarks, recent failures, top leaderboards.

/benchmarks
  Searchable benchmark catalog.

/benchmarks/new
  Create draft benchmark or upload package.

/benchmarks/[slug]
  Benchmark overview, latest version, description, metadata, leaderboards,
  versions, tasks summary, failure cases.

/benchmarks/[slug]/versions/[version]
  Immutable version view: manifest, task counts, scorer, splits, changelog.

/benchmarks/[slug]/runs/new
  Create run wizard.

/runs/[runId]
  Run status, config, progress, score, logs, per-task results, artifacts.

/runs/[runId]/tasks/[taskResultId]
  Detailed task trace and score explanation.

/leaderboards
  Global leaderboard browser.

/leaderboards/[benchmarkSlug]
  Benchmark leaderboard.

/failures
  Searchable failure archive.

/failures/[failureId]
  Failure case detail with reproduction bundle and rerun action.

/reviews
  Reviewer queue.

/admin
  Admin console.
```

## 13.2 Benchmark detail page

Must show:

- Title, summary, tags, domain.
- Risk class.
- Latest version.
- Maintainers.
- License.
- Data provenance summary.
- Primary metric.
- Public/private split availability.
- Runner requirements.
- Link to source/package.
- Leaderboard table.
- Failure-mode chart.
- Run button.
- Version history.
- "No Theo endorsement" disclaimer if the benchmark title/description references the idea origin.

## 13.3 Run detail page

Must show:

- Status.
- Benchmark/version/split.
- Model/provider.
- Agent scaffold.
- Tool permissions.
- Run config hash.
- Environment hash.
- Progress: `completed_tasks / total_tasks`.
- Primary score and secondary metrics.
- Cost, tokens, latency.
- Task table with pass/fail/error.
- Logs.
- Artifacts.
- Failure promotion controls.
- Verification/publication state.

## 13.4 Failure case page

Must show:

- Benchmark, version, task.
- Model and agent.
- Expected behavior.
- Actual output.
- Score explanation.
- Failure mode.
- Trace timeline.
- Tool calls.
- Logs.
- Reproduction bundle hash.
- Rerun button.
- Similar failures.
- Public/private visibility.

## 14. CLI design

Provide a CLI named `benchctl`.

Commands:

```txt
benchctl init
benchctl validate ./my-benchmark
benchctl run-local ./my-benchmark --split sample --model mock
benchctl package ./my-benchmark --out my-benchmark.zip
benchctl upload ./my-benchmark.zip
benchctl release BENCHMARK_SLUG --version 0.1.0
benchctl runs create --config run.yaml
benchctl runs watch RUN_ID
benchctl runs download RUN_ID --out artifacts/
benchctl failures rerun FAILURE_ID --model MODEL_ID
```

CLI responsibilities:

- Validate package locally.
- Run sample tasks locally with mock adapters.
- Package deterministic zip files.
- Compute content hashes.
- Upload packages.
- Start runs.
- Stream run status.
- Download artifacts.

## 15. Repository architecture

Recommended stack:

- Language: TypeScript for web/API/CLI/shared packages.
- Optional Python for scorer examples and sandboxed scorers.
- Package manager: `pnpm`.
- Web: Next.js App Router.
- API: Next.js route handlers or a separate Fastify service.
- DB: PostgreSQL.
- ORM: Prisma or Drizzle.
- Queue: Redis + BullMQ.
- Storage: S3-compatible object storage such as Cloudflare R2, AWS S3, MinIO.
- Runner: worker process that launches sandboxed containers.
- Local dev: Docker Compose.
- Testing: Vitest, Playwright, pytest for Python scorer examples.

Suggested monorepo:

```txt
community-bench/
  apps/
    web/
      app/
      components/
      lib/
      public/
    api/
      src/
  packages/
    benchmark-spec/
      src/
      schemas/
      examples/
    db/
      prisma/
      src/
    runner-core/
      src/
    model-adapters/
      src/
    scoring/
      src/
    ui/
      src/
    config/
      eslint/
      tsconfig/
  workers/
    runner/
      src/
      Dockerfile
    scorer/
      src/
      Dockerfile
  cli/
    benchctl/
      src/
  examples/
    skate-trick-name-lite/
    git-tool-use-lite/
  docs/
    architecture.md
    benchmark-spec.md
    scorer-api.md
    runner-security.md
  docker-compose.yml
  package.json
  pnpm-workspace.yaml
  README.md
```

## 16. Storage design

## 16.1 Object storage prefixes

```txt
packages/{benchmarkVersionId}/{packageHash}.zip
assets/{assetId}/{sha256}
runs/{runId}/config.yaml
runs/{runId}/tasks/{taskResultId}/trace.jsonl
runs/{runId}/tasks/{taskResultId}/stdout.log
runs/{runId}/tasks/{taskResultId}/stderr.log
runs/{runId}/tasks/{taskResultId}/artifacts/{filename}
failures/{failureId}/reproduction-bundle.tar.zst
```

## 16.2 Hashing

Use SHA-256 for:

- Benchmark package zip.
- Manifest.
- Task files.
- Assets.
- Scorer code.
- Runner image digest.
- Agent scaffold commit.
- Run config canonical JSON.
- Reproduction bundles.

Canonicalization rules:

- Sort object keys before hashing JSON.
- Normalize line endings to LF.
- Use UTF-8.
- Do not include timestamps in content hashes unless they are part of the source data.

## 17. Queue and job design

Queues:

- `benchmark-validation`
- `benchmark-release`
- `run-execution`
- `task-execution`
- `scoring`
- `artifact-processing`
- `leaderboard-refresh`
- `failure-bundle-build`
- `notifications`

Job idempotency:

- Every job must have an idempotency key.
- Re-running a job should not duplicate task results.
- Failed jobs should preserve logs.
- Jobs should be retryable unless marked non-retryable due to validation failure.

Run state machine:

```txt
queued
  -> running
  -> scoring
  -> completed

queued/running/scoring
  -> cancelled

queued/running/scoring
  -> failed
```

Task state machine:

```txt
queued
  -> running
  -> passed | failed | errored | timed_out | skipped
```

## 18. Validation pipeline

Benchmark validation steps:

1. Unpack package in temporary directory.
2. Reject path traversal or symlink escape.
3. Parse `benchmark.yaml`.
4. Validate manifest schema.
5. Validate license file.
6. Validate README.
7. Validate data-card requirements.
8. Validate split files exist.
9. Validate every JSONL line.
10. Validate unique task IDs.
11. Validate referenced assets exist.
12. Validate asset size and MIME type.
13. Validate scorer entrypoint exists.
14. Run scorer on sample fixture.
15. Run a smoke evaluation with mock model on sample split.
16. Compute hashes.
17. Produce validation report.
18. Set benchmark version status to `pending_review` or `rejected`.

Validation report shape:

```json
{
  "ok": true,
  "errors": [],
  "warnings": [
    {
      "code": "PRIVATE_SPLIT_PRESENT",
      "message": "private_test split will not be publicly downloadable."
    }
  ],
  "hashes": {
    "package": "sha256:...",
    "manifest": "sha256:..."
  },
  "taskCounts": {
    "sample": 5,
    "public_test": 100,
    "private_test": 100
  }
}
```

## 19. Verification and leaderboard rules

A run may appear on a public leaderboard when:

- Benchmark version is released.
- Run completed without infrastructure errors.
- Required split was evaluated.
- Task count matches expected count.
- Scorer hash matches benchmark version.
- Run config is public enough to reproduce.
- Artifacts required by benchmark are available.
- Model and agent metadata are locked.
- Reviewer or automated policy marks it verified.

Leaderboard categories:

- **Verified**: run executed by platform or reproduced by reviewer.
- **Self-reported**: uploaded by user with artifacts but not verified.
- **Imported**: external result with citation and limited artifacts.
- **Experimental**: partial split, sample split, or non-standard settings.

Default leaderboard should show verified entries first, then self-reported entries.

## 20. Failure-case preservation

## 20.1 Capture policy

For every failed or errored task, store:

- Task input.
- Expected output or scoring rubric if public.
- Raw model output.
- Normalized output.
- Score result.
- Failure mode.
- Model/provider metadata.
- Agent scaffold metadata.
- Prompt template and hash.
- Tool-call trace.
- Filesystem diff if repository task.
- stdout/stderr.
- Cost, tokens, latency.
- Sandbox environment hash.
- Reproduction command.
- Reproduction bundle hash.

## 20.2 Failure modes

Initial enum:

```txt
wrong_answer
invalid_format
missing_required_field
tool_misuse
git_state_wrong
repository_tests_failed
timeout
budget_exhausted
unsafe_action_blocked
hallucinated_capability
refused
overfit_to_example
partial_completion
scorer_error
infrastructure_error
other
```

## 20.3 Reproduction bundle

A reproduction bundle should contain:

```txt
reproduce/
  README.md
  run-config.canonical.json
  task.json
  expected.json
  model-output.json
  score-result.json
  trace.jsonl
  stdout.log
  stderr.log
  artifacts/
  workspace-before.tar.zst
  workspace-after.tar.zst
  scorer/
  manifest/
  reproduce.sh
```

The reproduction command should support:

```bash
benchctl reproduce ./reproduce --model mock
benchctl reproduce ./reproduce --model provider/model-id
```

## 21. Security and abuse controls

## 21.1 Threat model

Threats:

- Malicious benchmark package with path traversal.
- Malicious scorer code.
- Malicious uploaded assets.
- Model output prompt injection into UI.
- Secret leakage into traces.
- Benchmark author uploads copyrighted or private data.
- Agent executes destructive shell commands.
- Run floods system with expensive provider calls.
- Users fake leaderboard results.
- Hidden test leakage.
- Medical/legal content misuse.

## 21.2 Controls

- Validate zip extraction paths.
- Scan file types and enforce size limits.
- Store assets outside web root.
- Render model outputs as escaped text by default.
- Sanitize Markdown.
- Run scorers in isolated sandbox.
- Run agents in isolated sandbox.
- Disable network by default.
- Use per-run cost/time/tool budgets.
- Redact secrets from logs.
- Keep provider API keys in a secrets vault or encrypted store.
- Require review for high-risk benchmarks.
- Keep hidden/private splits inaccessible to authors after release if they are intended for official leaderboard use.
- Rate-limit uploads and runs.
- Require signed declaration of data rights.
- Maintain audit logs.
- Provide takedown workflow.
- Clearly label non-clinical medical benchmarks.

## 22. Observability

Metrics:

- Runs queued/running/completed/failed.
- Task throughput.
- Mean task runtime.
- Queue latency.
- Scorer error rate.
- Sandbox startup latency.
- Cost by provider/model/user.
- Storage used by runs/artifacts.
- Leaderboard refresh latency.
- Failure-mode counts.

Logs:

- API request logs.
- Job logs.
- Runner lifecycle logs.
- Scorer logs.
- Security/audit logs.

Tracing:

- One trace ID per run.
- One span per task.
- Child spans for model calls, tool calls, scoring, artifact upload.

Alerts:

- Runner failure spike.
- Queue backlog.
- Cost threshold exceeded.
- Sandbox escape signal.
- Object storage errors.
- DB connection exhaustion.
- Repeated scorer crashes for released benchmark.

## 23. Testing strategy

## 23.1 Unit tests

- Manifest schema validation.
- JSONL parser.
- Hash canonicalization.
- Scorer output validation.
- Aggregation math.
- Failure-mode classification.
- API authorization checks.
- Queue state transitions.

## 23.2 Integration tests

- Upload valid benchmark package.
- Reject invalid package.
- Create benchmark release.
- Run sample split with mock model.
- Run Git benchmark with mock agent.
- Store artifacts.
- Publish leaderboard entry.
- Promote failure case.
- Build reproduction bundle.

## 23.3 End-to-end tests

- User signs in.
- User uploads benchmark.
- Reviewer approves.
- User creates run.
- Run completes.
- Leaderboard updates.
- User opens failed task.
- User promotes failure case.
- User downloads reproduction bundle.

## 23.4 Security tests

- Zip-slip package.
- Symlink escape.
- Oversized asset.
- Malicious Markdown.
- Scorer tries network access.
- Scorer tries host filesystem access.
- Agent tries denied shell command.
- Model output contains script tag.
- Logs contain fake secret-like strings for redaction test.

## 24. Seed benchmarks

## 24.1 `skate-trick-name-lite`

Purpose:

- Demonstrate quirky niche terminology benchmark.
- Mimic the pattern "technical trick description -> trick name" without copying protected data.

Tasks:

- 25 sample tasks.
- 100 public test tasks.
- Exact/alias match scorer.
- Tags for spatial reasoning, terminology, difficulty.

Scoring:

- Primary: alias-normalized accuracy.
- Secondary: invalid format rate.

Expected output schema:

```json
{
  "answer": "string"
}
```

Important:

- Use original descriptions written for this project.
- Include aliases and accepted spellings.
- Avoid claiming to be official SkateBench.

## 24.2 `git-tool-use-lite`

Purpose:

- Demonstrate agent tool-use benchmark.

Task families:

- Branch creation.
- Commit correct file.
- Clean worktree.
- Resolve merge conflict.
- Revert bad commit.
- Inspect history.
- Cherry-pick simple commit.
- Avoid modifying unrelated files.

Scoring:

- Repository state assertions.
- Git log assertions.
- Unit tests where applicable.
- Forbidden command detection.

Failure modes:

- `git_state_wrong`
- `tool_misuse`
- `repository_tests_failed`
- `timeout`
- `partial_completion`

## 25. Deployment

## 25.1 Local development

Use Docker Compose for:

- PostgreSQL.
- Redis.
- MinIO.
- Web/API.
- Runner worker.
- Scorer worker.

Developer command set:

```bash
pnpm install
docker compose up -d postgres redis minio
pnpm db:migrate
pnpm dev
pnpm worker:runner
pnpm worker:scorer
```

## 25.2 Production

Minimum production components:

- Web/API service.
- PostgreSQL.
- Redis.
- S3-compatible storage.
- Runner worker pool.
- Scorer worker pool.
- Container registry for runner images.
- Secrets manager.
- Observability stack.

Deployment constraints:

- Web/API can run on standard app hosting.
- Runner/scorer workers must run on isolated compute.
- Object storage should have lifecycle policies for large transient artifacts.
- Keep public artifacts separate from private/hidden split assets.
- Use signed URLs for artifact download.

## 26. Acceptance criteria for MVP

MVP is complete when:

1. A user can create an account.
2. A user can upload a benchmark package.
3. The system validates the package and shows clear errors.
4. A reviewer can approve a benchmark version.
5. A benchmark version becomes immutable after release.
6. A user can create a run against a released benchmark.
7. The runner executes a sample text benchmark end to end.
8. The runner executes a sample Git agent benchmark end to end.
9. Scoring produces per-task and aggregate metrics.
10. Logs and artifacts are stored.
11. A leaderboard entry appears after a verified run.
12. Failed task results can be promoted to failure cases.
13. Failure cases include downloadable reproduction bundles.
14. Public pages show benchmark methodology, score, cost, latency, and verification state.
15. Security tests for package extraction, sandboxing, and XSS pass.
16. Documentation is sufficient for a contributor to author a new benchmark.

## 27. Open questions for product owner

These are not blockers for MVP; use the defaults in this design unless answered differently.

1. Should official leaderboards run only on platform-owned API keys, or can users bring keys for verified runs?
   - Default: users bring keys for unverified/self-reported; platform keys or reviewer rerun for verified.

2. Should hidden holdout tasks exist from day one?
   - Default: support schema and storage, but MVP public leaderboards use public test splits until governance is ready.

3. Should benchmark packages be edited in the web UI or only uploaded as files?
   - Default: upload/import first; web editor later.

4. Should model outputs be public by default?
   - Default: public for verified runs unless benchmark risk class or user setting prevents it.

5. Should high-risk medical benchmarks be allowed in MVP?
   - Default: allow drafts and private review only; do not release public medical leaderboards until policy is complete.

6. Should community voting affect benchmark visibility?
   - Default: not in MVP. Use reviewer curation first.

## 28. Implementation risks

| Risk | Impact | Mitigation |
|---|---|---|
| Arbitrary code execution in scorer/agent packages | Critical | Strict sandboxing; no untrusted code in API process |
| Low-quality benchmark spam | High | Review queue, rate limits, required metadata, status labels |
| Copyright/private data uploads | High | Declarations, moderation, takedown, restricted risk class |
| Hidden test leakage | High | Strict split storage, access control, audit logs |
| Fake leaderboard submissions | Medium | Verification states, platform reruns, artifact requirements |
| Cost blowups from model APIs | Medium | Budgets, rate limits, cancellation, dry-run mode |
| Overfitting to public benchmarks | Medium | Versioning, private splits, rotating tasks later |
| LLM judge instability | Medium | Prefer objective scorers, disclose judge details, calibration |
| Medical misuse | High | Disclaimers, de-identification, high-risk review gate |
| Runner complexity | High | Start with text + Git seed benchmarks; expand later |

## 29. Suggested first release roadmap

### Alpha

- Local package validation.
- Two seed benchmarks.
- Mock model runner.
- Local run artifacts.
- No public site required.

### Private beta

- Auth.
- Web catalog.
- Package uploads.
- Runner workers.
- Public pages.
- Manual reviewer approval.

### Public beta

- Leaderboards.
- Failure archive.
- Reproduction bundles.
- CLI.
- Verified/self-reported result labels.
- Community submissions.

### Stable v1

- Hardened sandbox.
- Hidden/private split support.
- More agent tools.
- Formal governance.
- Public API.
- Scheduled reruns.
