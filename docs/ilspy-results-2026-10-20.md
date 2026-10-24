# Saved ILSpy runs: availability and instruction loading

Re-summarized locally on 2026-10-21 using saved transcripts and wrapper events.
This processed six reports containing **73 saved trials**, made **zero API calls**,
and changed **zero execution scores**. Original reports and artifacts were preserved.

The two batches below used different shared system prompts and are reported
separately. Each covered the three dependency cases, with three planned
repetitions per case and model, and two conditions. Neither batch included the
repository-only controls. Model IDs were
`openrouter/anthropic/claude-{opus,sonnet,haiku}-5.5`.

## Completed pilot: optional skill-loading instruction

Source prefix: `results/ilspy/20261020T033958Z-research-3cases-3x-`.
54 saved trials, 27 valid matched pairs, no excluded pairs.

| Model | Valid pairs | ILSpy without skill | ILSpy with skill | Uplift (pp) | Treatment body reads | Treatment target uses without body |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Opus 5.5 | 9 | 0/9 | 0/9 | +0.0 | 0 | 0 |
| Sonnet 5.5 | 9 | 0/9 | 0/9 | +0.0 | 0 | 0 |
| Haiku 5.5 | 9 | 0/9 | 3/9 | +33.3 | 0 | 3 |

51/54 trials stopped at the cumulative token limit; three Sonnet baseline trials
completed normally. The shared prompt used the earlier optional wording:
"You may load available skills with invoke_skill when useful."

## User-stopped rerun: explicit index-consideration instruction

Source prefix: `results/ilspy/20261020T040555Z-skill-index-3cases-3x-`.
**Interrupted, not a completed comparison:** 19 of 54 planned trials were saved.
These provide nine valid matched pairs. One Haiku pair has only one saved partner
and is excluded from rates and paired diagnostics.

| Model | Saved trials | Valid pairs | Excluded pairs | ILSpy without skill | ILSpy with skill | Uplift (pp) | Treatment body reads | Treatment target uses without body |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Opus 5.5 | 4 | 2 | 0 | 0/2 | 0/2 | +0.0 | 0 | 0 |
| Sonnet 5.5 | 6 | 3 | 0 | 0/3 | 2/3 | +66.7 | 0 | 2 |
| Haiku 5.5 | 9 | 4 | 1 | 0/4 | 0/4 | +0.0 | 0 | 0 |

16/19 saved trials stopped at the cumulative token limit; three Sonnet baseline
trials completed normally. The shared system prompt explicitly asked agents to
consider the index, identified the tool description containing it, and showed the
generic `invoke_skill` argument syntax. It did not name ILSpy. Both conditions
received this wording; all other assigned settings were unchanged.

## What the diagnostics establish

- All five successful target-decompilation trials were in the with-skill
  condition: three Haiku trials in the completed pilot, and two Sonnet trials in
  the stopped rerun. No saved trial in either batch successfully read the ILSpy
  skill body or a reference file.
- Within valid pairs, the treatment index included the ILSpy entry for all 27
  pilot trials and all nine rerun trials; the corresponding baseline index
  omitted it. This exposure is **reconstructed from condition and the recorded
  skill snapshot**, not from captured outbound request schemas. Those schemas
  were not retained by the historical runner.
- The successful decompilations remain positive primary outcomes despite the
  zero body-read count. The index entry could have cued ILSpy use; these artifacts
  do not establish the model's motivation or isolate the index's causal effect.
- These small, heavily budget-limited runs describe the custom harness within
  its assigned investigation budget. The partial rerun is especially unsuitable
  for a general uplift claim. Repetitions of the same three cases are not
  independent projects, and execution success does not measure answer correctness.

## Reproduction and evidence

Run the offline command separately for each original model report:

```bash
uv run --frozen dotnet-evals summarize-ilspy \
  results/ilspy/20261020T040555Z-skill-index-3cases-3x-sonnet.json \
  --output results/ilspy/review-sonnet-diagnostics.json
```

Use a new output name each time. Derived reports contain source/report hashes,
diagnostic-code hashes, original run status and provenance, recomputed scores,
paired diagnostics, and all-saved-trial stopping reasons. Raw and derived results
remain ignored by Git; this document is the reviewable summary.

Paid evals were stopped at the time of this reanalysis. A subsequent authorized
[2026-10-21 rerun](ilspy-results-2026-10-21.md) used the same custom harness with
updated diagnostics. Native-harness alignment is a separate question; see
[harness fidelity and measurement details](ilspy-activation.md#harness-fidelity).
