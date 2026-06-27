# AI benchmarks that Theo wants

Idea from Theo (https://x.com/theo/status/2069621429189161350 / https://www.youtube.com/watch?v=wEAb0x3wTRc). Note that Theo has no endorsement on this project (yet).

## Rationale - **More AI Benchmarks**

### Pain Points
There are too few benchmarks, and they aren’t diverse enough. Most of them come from inside research labs.

### What Theo Wants
-  Benchmarks written by non-lab people: community-driven, quirky, cross-domain
-  Theo’s SkateBench, which asks the model to guess a skate trick name from a description of the trick, turned out to be unexpectedly useful—somewhere between a syntax test, a niche English test, and 3D spatial reasoning. Many labs proactively reached out about it.
-  Agent tool-proficiency benchmarks: for example, GitBench, which measures an agent’s ability to use Git
-  Failure-case preservation: save AI attempts at tasks that fail in a reproducible way so they can be retried later
-  Benchmarks for everything from strange hypotheses to real work
-  Benchmarks for obscure domains: niche programming languages like Crystal, medical imaging (MRI cancer diagnosis), aerial image recognition, and more
-  Especially things agents are bad at—creating a benchmark that proves all agents are bad at something is the best way to motivate labs to fix it

### Core Logic
Once there is a metric, labs will go all out to improve the score. Proving that “all agents are bad at something” is the best way to motivate labs to improve.

