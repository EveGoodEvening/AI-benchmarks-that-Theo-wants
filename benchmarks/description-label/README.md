# Board-sport trick description-to-label

This is the first reference benchmark in the `ai-bench` suite (chunk C06). It
is a text-in/text-out **description-to-label** task: given a plain-English
description of a board-sport trick, the model must reply with the trick's
common name.

## Shape and inspiration

The task is inspired by the *shape* of [Theo's
SkateBench](https://x.com/theo/status/2069621429189161350), which asks a model
to guess a skate trick name from a description and turned out to sit between a
syntax test, a niche-English vocabulary test, and 3D spatial reasoning. This
benchmark generalizes that shape across three board sports — skateboarding,
snowboarding, and surfing — so the same kind of "niche language + spatial
motion" reasoning is exercised over a broader vocabulary.

## Non-endorsement and originality

- **No endorsement.** Theo has no involvement with or endorsement of this
  project or this benchmark. The name "SkateBench" is Theo's; this benchmark is
  **not** called SkateBench and does not import or reproduce any of Theo's
  actual SkateBench cases.
- **Original fixtures.** Every case description and expected label in
  `cases/*.yaml` was written from scratch for this suite. They are original
  prose, not copied from any existing benchmark dataset.
- **Shared labels are intentional.** Some trick names (e.g. `ollie`, `nollie`)
  appear in more than one sport; the expected label is the canonical name
  regardless of sport, which is part of what makes the task non-trivial.

## What it measures

- **Niche vocabulary**: recognition of specialized board-sport trick names.
- **Spatial reasoning**: mapping a verbal description of board rotation,
  flip axis, and body motion to a named maneuver.
- **Syntax-like parsing**: extracting the single canonical label from a
  description that may admit several phrasings.

## Verifier

The benchmark uses the built-in `exact_match` verifier (case-insensitive,
whitespace-normalized) defined in `src/ai_bench/scoring.py` (C04). Expected
labels are short canonical names, so deterministic exact matching is
unambiguous; no LLM judge is used.

## Smoke subset

Cases tagged `smoke` form the smoke subset selectable with
`ai-bench run benchmarks/description-label --tag smoke --model stub`. There are
4 `smoke`-tagged cases covering one trivial, one easy, and two medium
examples across all three sports.

## Limitations

- **Small and English-only.** v1 ships 25 cases in English. This is enough to
  demonstrate the verifier path and contribution shape, not to support
  statistically strong model rankings.
- **Label ambiguity is minimized but not zero.** A few tricks have common
  aliases (e.g. "360 flip" for "tre flip", "barrel" for "tube ride"). The
  expected value is the single canonical short name; aliases count as failures
  under `exact_match`. A fuzzy/alias-aware verifier is a post-v1 option (C13),
  not a v1 change.
- **No multimodal input.** Descriptions are text only; video or image-based
  trick recognition is out of v1 scope.
- **Sports coverage is illustrative.** The set is not an exhaustive taxonomy of
  any sport.

## Reproducibility and the non-stub path

This benchmark ships a checked-in non-stub prediction sample in
`sample_predictions/` (one `.txt` file per case id) so the benchmark can be
scored end-to-end without a live model or API key:

```sh
uv run ai-bench run benchmarks/description-label \
  --predictions benchmarks/description-label/sample_predictions
```

This exercises the C05 file-prediction path: real submitted text outputs are
scored by the real C04 `exact_match` verifier, and the run-record's `model id`
records the prediction source (`file:...`) rather than a live provider. The
sample intentionally contains one wrong prediction (`surf-airs`) to show that
failed case verdicts are scored evaluation data, not command failures — the
command still exits 0 and writes a schema-valid run-record.

## Verification commands

```sh
uv run ai-bench validate benchmarks/description-label
uv run ai-bench run benchmarks/description-label --model stub
uv run ai-bench run benchmarks/description-label --tag smoke --model stub
uv run ai-bench run benchmarks/description-label --predictions benchmarks/description-label/sample_predictions
```

All four exit 0 on a healthy benchmark. Per the C05 exit contract, exit 0 means
the selected cases were evaluated, scored, and a schema-valid run-record was
written — it does **not** mean every case verdict passed.

## License

Benchmark cases and this README are licensed `CC0-1.0` (see `benchmark.yaml`).
