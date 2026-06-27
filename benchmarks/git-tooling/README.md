# Git tool-proficiency

This is the second reference benchmark in the `ai-bench` suite (chunk C08). It
is a **tool-task** benchmark: given a seeded git working tree and an
imperative instruction, an agent emits structured tool actions (`git` and
`file.write`) inside a hermetic sandbox, and the final repository state is
scored by the built-in `state_check` verifier.

## Shape and inspiration

The task is inspired by the *shape* of Theo's GitBench: a tool-proficiency
benchmark that scores whether an agent can drive git to a target repository
state from a seeded working tree. This benchmark generalizes that shape into a
checked-in, hermetically scoreable suite of original fixtures.

## Non-endorsement and originality

- **No endorsement.** Theo has no involvement with or endorsement of this
  project or this benchmark. The name "GitBench" is Theo's; this benchmark is
  **not** called GitBench and does not import or reproduce any of Theo's
  actual GitBench cases.
- **Original fixtures.** Every case, seeded working tree, and expected
  repository state in `cases/*.yaml` and `fixtures/seed/**` was written from
  scratch for this suite. They are original fixtures, not copied from any
  existing benchmark dataset.

## What it measures

This benchmark measures **tool proficiency, not trivia.** Cases exercise
whether an agent can correctly sequence git and filesystem tool actions to
reach a deterministic target repository state — init/commit, branch/switch,
stage/commit, amend, rm/mv, tag, restore, reset, clean, merge (ff and no-ff),
cherry-pick, revert, stash, orphan branches, and empty commits. It is not a
git-vocabulary quiz; the score reflects the produced repository state, not
whether the agent can recite git flags.

## Verifier

The benchmark uses the built-in `state_check` verifier (C04/C07) declared in
`src/ai_bench/scoring.py`. Each case carries a per-case `verifier:
{verifier: state_check}` override and a `state_check` block asserting
deterministic repository invariants: `git.status_clean`,
`git.head_commit_message` (matched by substring), `git.branches`,
`files.<path>.exists`, and `absent`. The verifier fails closed on
nondeterministic assertions like `sha256`, so cases rely on subject substrings
and branch lists instead of commit hashes. No LLM judge is used.

## Hermetic sandbox assumptions

Cases rely on the enforced C07 sandbox guarantees and cannot reach the
outbound network or host credentials:

- **Network denial.** No outbound network access is available; cases never
  require `fetch`, `push`, `pull`, `clone`, or any remote.
- **Credential stripping.** Host git credentials (credential helpers, SSH
  keys, signing keys) are stripped; cases never require or can reach them.
- **Path confinement.** Tool actions are confined to the seeded working tree;
  `git config` is constrained to the two safe local identity keys
  (`user.name`, `user.email`) and global `-c` config injection, alias
  expansion, hooks, and filters are rejected before host git is invoked.
- **Timeouts.** Each action is bounded by a per-action timeout; a timed-out
  action is recorded as a sandbox boundary violation, not a silent success.

## Smoke subset

Cases tagged `smoke` form the smoke subset selectable with
`ai-bench run benchmarks/git-tooling --tag smoke --model stub`. There are 4
`smoke`-tagged cases:

- `init-repo` (trivial, PASS)
- `create-branch` (easy, PASS)
- `stage-and-commit` (easy, PASS)
- `dirty-no-commit` (easy, **intentional FAIL**)

`dirty-no-commit` is the deliberate failure path: its script writes `notes.md`
but never stages or commits it, so its `state_check` (which expects
`status_clean: true` and `notes.md` to exist as a committed result) fails.
This proves failed case verdicts are scored evaluation data, not command
failures — the run still exits 0 and writes a schema-valid run-record.

## Reproducibility and the non-stub path

This benchmark ships a checked-in non-stub transcript-replay sample in
`sample_transcripts/` (one `<id>.json` per case id) so the benchmark can be
scored end-to-end without a live model, API key, or sandbox re-exec:

```sh
uv run ai-bench run benchmarks/git-tooling \
  --replay benchmarks/git-tooling/sample_transcripts
```

This exercises the C05 transcript-replay path: real submitted agent/tool-action
transcripts with final repo-state snapshots are replayed through the real
`state_check` verifier (not a stub), and a schema-valid run-record is written.
The `dirty-no-commit` replay intentionally violates its `state_check`, so a
failed verdict appears in the run-record while the command still exits 0.

## Limitations

- **Small and git-only.** v1 ships 24 cases over a single small seeded
  repository. This is enough to demonstrate the `state_check` verifier path
  and the hermetic tool-task contribution shape, not to support statistically
  strong model rankings.
- **Deterministic state.** Expected states are deterministic repository
  snapshots; `sha256` is deliberately avoided in favor of subject substrings
  and branch lists, so the suite cannot distinguish commits that happen to
  share a subject but differ in content.
- **No networked git.** All cases are local; remote/credential-dependent git
  workflows are out of v1 scope by design (and unreachable under the C07
  sandbox).
- **Coverage is illustrative.** The case set is not an exhaustive taxonomy of
  git operations.

## Verification commands

```sh
uv run ai-bench validate benchmarks/git-tooling
uv run ai-bench run benchmarks/git-tooling --model stub
uv run ai-bench run benchmarks/git-tooling --tag smoke --model stub
uv run ai-bench run benchmarks/git-tooling --replay benchmarks/git-tooling/sample_transcripts
uv run pytest tests/test_git_tooling_benchmark.py -q
```

All five exit 0 on a healthy benchmark. Per the C05 exit contract, exit 0 means
the selected cases were evaluated, scored through the `state_check` verifier,
and a schema-valid run-record was written — it does **not** mean every case
verdict passed (the `dirty-no-commit` smoke case and any failed replay verdicts
are scored evaluation data, not command failures).

## License

Benchmark cases, fixtures, and this README are licensed `CC0-1.0` (see
`benchmark.yaml`).
