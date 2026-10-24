# ILSpy skill availability rerun: 2026-10-21

Completed **54 recorded trials and 27 matched pairs**: three dependency cases,
three repetitions, three models, and baseline/treatment conditions. Each model
contributed nine pairs. All pairs have two valid observations after recovery;
none are excluded from the final rates.

This rerun retained the existing `custom-tool-index-v1` harness, shared prompt,
skill snapshot, pinned fixture, research alternatives, budgets and scheduling seed.
The change was diagnostic recording and reporting. The question remains whether
making the skill available increases successful use of ILSpy on the target
dependency. Loading the skill body is a separate diagnostic.

## Results

| Model | Without skill: target decompilation | With skill: target decompilation | Uplift (pp) | Treatment body loads |
| --- | ---: | ---: | ---: | ---: |
| Opus 5.5 | 0/9 (0.0%) | 1/9 (11.1%) | +11.1 | 1/9 |
| Sonnet 5.5 | 1/9 (11.1%) | 0/9 (0.0%) | -11.1 | 2/9 |
| Haiku 5.5 | 1/9 (11.1%) | 0/9 (0.0%) | -11.1 | 0/9 |

There is **no consistent observed uplift across the three models in this batch**.
These small counts do not establish that the skill generally increases or reduces
usage. The three cases cover one project/dependency, repeated cases are not
independent projects, and answer correctness is not measured.

### Loading and execution

- Opus's successful treatment trial was `pair-0007`, `seq-retry-timing`, repetition
  3. It read `ilspy-decompile/SKILL.md`, received those instructions in a subsequent
  model request, and then successfully decompiled the target assembly. This is
  observed ordering, not proof the instructions caused the execution.
- Sonnet read the body in two treatment trials and did not invoke ILSpy in either.
  Its successful baseline execution occurred in `pair-0005`, `seq-first-event`,
  repetition 3.
- Haiku's successful baseline execution occurred in `pair-0004`,
  `seq-retry-timing`, repetition 2. It loaded no skill body.
- No target reference files were read. The two baseline executions occurred
  without the ILSpy entry or body; the single treatment execution followed a body
  load. There were no treatment executions without a body load in this batch.

The index entry remains part of the treatment, whether or not the body is loaded.
This design measures the effect of making the skill available; it does not isolate
the causal contribution of the description from that of the instructions.

## Budget and infrastructure

The assigned budget remained 100,000 cumulative prompt-plus-completion tokens per
trial, with 30 model requests, 8,192 completion tokens per request, and a 900-second
trial limit. Models were not given a remaining-budget counter.

Of the 54 final observations, **39 stopped at the cumulative token limit**, four
at an output limit, and 11 completed normally. Rates therefore describe execution
within the assigned budget, not unrestricted investigations.

The host disk filled during the initial run. We preserved 23 usable trial results,
kept copies of the pre-recovery reports and two damaged transcript files, and
completed only the remaining 31 scheduled observations. One recorded infrastructure
error and two interrupted transcript-write attempts were retried. These failed
attempts are retained as recovery evidence and are not counted as negative outcomes.
The recovery scheduler checked that harness files, dataset, skill snapshot and
research configuration matched before resuming the original schedule.

Cleanup removed nine older ILSpy console logs and reclaimed approximately 2.1 GB
of unused Docker build cache last accessed more than a week earlier. Current
reports and transcripts were retained. All evaluation processes and trial
containers exited after completion.

## Evidence and reproducibility

Batch prefix: `results/ilspy/20261021T020031Z-diagnostics-3cases-3x-`.
The `-batch.json` manifest records the commands, reports, recovery and final audit;
the three model reports have `-verified.json` derivatives. Raw results remain
ignored by Git.

- Harness commit: `c4c0036`.
- Skill revision: `ac0deb2f531ff5090718cb0069c73ba3f9f95f69`.
- Dataset SHA-256: `7268afdb6bd90b4339d1353e57a9d9bfe84d757ee5756106503e6b9263b57af8`.
- Fixture image: `sha256:40196c49bde4a60e9e78e69a79d5aac174623adc5a35f005b54c966dc5224e99`.
- Seed: 42. Full model IDs: `openrouter/anthropic/claude-{opus,sonnet,haiku}-5.5`.

Offline reanalysis verified **436 captured requests** against the saved message
prefixes and tool-definition hashes, and recomputed all execution scores with
**zero changes**. All 27 treatment trials captured the ILSpy index entry; all 27
baseline trials omitted it. Each condition used the same 38 common skills, and
treatment added `ilspy-decompile`. Captures describe inputs to LiteLLM, not proof
of downstream rendering or model attention. The audit made no model API calls.

See [measurement details](ilspy-activation.md#measurement-and-interpretation) and
[the earlier batches](ilspy-results-2026-10-20.md), which are reported separately.
