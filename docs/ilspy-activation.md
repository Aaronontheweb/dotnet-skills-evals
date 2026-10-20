# ILSpy activation uplift

This experiment asks: **how much does making `ilspy-decompile` available increase
successful use of ILSpy to inspect a relevant NuGet dependency?**

Each model/case/repetition gets a matched pair of fresh containers and separate
conversations. Baseline has the registered skill catalog minus `ilspy-decompile`;
treatment has the full catalog. Both have the same installed ILSpy, shell tool,
source, packages, prompt, resource limits, and model settings. The treatment
advertises the skill through `invoke_skill`; its instructions are loaded only if
the model requests them. Skill loading is recorded separately from ILSpy use.

This uses a controlled LiteLLM/OpenRouter tool loop, rather than a native coding
assistant's system prompt, permission model, or built-in tools. Conclusions apply
to this agent environment. There are no API calls to a judge.

## Setup and credentials

Requires Linux or macOS with Docker running, Git, and uv. Docker runs Linux
containers. Python 3.11+ is managed by uv; .NET and ILSpy live inside the fixture.
The fixture build needs public GitHub, NuGet, Debian and Microsoft registry access.
Individual model trials run offline, with no host mounts or credentials passed in.

From the evaluation worktree:

```bash
uv sync --frozen --extra dev
uv run --frozen dotnet-evals prepare-ilspy
```

`prepare-ilspy` builds the image, runs the real ILSpy tool, and checks that help
and type listings do not count as decompilation. It needs **no API credentials**.
It can be rerun without invoking a model.

The only paid-service credential is an **OpenRouter API key with available
credits and access to the subject models**. Set it in this worktree's ignored
`.env`, or export it in the invoking shell:

```dotenv
OPENROUTER_API_KEY=your-openrouter-key
```

No separate Anthropic, OpenAI, or GitHub token is required. The existing harness
routes all subject models through OpenRouter. A model must support function tools.
Use explicit versioned IDs where available; moving aliases weaken reproducibility.

The skill repository defaults to `~/repositories/dotnet-skills`. Set
`DOTNET_SKILLS_REPO` or pass `--skills-repo /path/to/dotnet-skills` to override it.
If absent, the existing loader clones the public repository. To reproduce a run,
use the same skill revision and file hashes recorded in its result. The harness
snapshots all registered skill markdown before the experiment starts, so source
changes during a run cannot change the treatment.

## Preflight and first run

Set a real model ID below. The placeholder deliberately does not pick a moving
"latest" model:

```bash
export SUBJECT_MODEL='openrouter/<provider>/<versioned-model-id>'

uv run --frozen dotnet-evals eval-ilspy \
  --model "$SUBJECT_MODEL" \
  --case seq-queue-retry --repetitions 1 --preflight-only
```

Preflight validates the dataset, skill snapshot, pinned source commit, target
assembly identities, installed tool, and scoring controls. It reports trial
counts and makes **zero model API calls**, even if a key is already configured.
It does not validate model access or provider compatibility.

After configuring the key, start with one pair:

```bash
uv run --frozen dotnet-evals eval-ilspy \
  --model "$SUBJECT_MODEL" \
  --case seq-queue-retry --repetitions 1 \
  --output results/ilspy/first-pair.json
```

This is two trials and at most 60 model requests under the default 30-step limit.
Check the saved transcripts for tool protocol compatibility and the actual
investigation behavior before expanding. A one-pair run is a plumbing check;
it cannot establish a stable activation rate.

Run the five-case dataset with repetitions:

```bash
uv run --frozen dotnet-evals eval-ilspy \
  --model "$SUBJECT_MODEL" \
  --repetitions 5 \
  --output results/ilspy/comparison.json
```

That schedules **50 trials per model**: five cases × five repetitions × two
conditions. Repeat `--model` to compare multiple models in one report. Each model
gets its own rates and uplift; controls are reported separately. Pair order and
condition order are randomized using the recorded `--seed` (default 42).

Budget flags include `--max-steps`, `--max-completion-tokens`, `--max-total-tokens`,
`--trial-seconds`, `--request-seconds`, and `--command-seconds`. Defaults are 30 model decisions, 8,192
completion tokens per request, a 100,000 total-token stopping threshold, 900
seconds per trial, 180 seconds per model request, and 60 seconds per shell command.
Increase `--request-seconds` for models that need longer reasoning requests, within
the trial's remaining time. Prompt tokens count toward
the total. The total-token limit is a **soft stop after a response**; a request's
prompt usage can take it past that threshold. These are execution limits, not a
dollar spending cap. Skill loading consumes the same step and token budget as
other actions. Responses are not cached; repeated temperature-zero requests may
still give identical answers.

Provider or infrastructure errors stop the experiment after checkpointing the
partial report. Diagnose the error and use a new output filename for a new run;
there is no automatic retry or resume. Existing outputs are never overwritten.

## Fixture and cases

- Repository: `datalust/serilog-sinks-seq`, tag `v7.0.0`, commit
  `bf6c2f8d26803a30b9963e01ea0d5f63152a7006`.
- Production project: `src/Serilog.Sinks.Seq/Serilog.Sinks.Seq.csproj`.
- Dependency of interest: `Serilog.Sinks.PeriodicBatching` **4.0.0**.
- Restore: checked-in `fixtures/ilspy/packages.lock.json`, using locked mode.
- SDK: **10.0.100**, with the base image pinned by digest.
- ILSpyCmd: **9.1.0.7988**, installed before either condition starts. The SDK runs
  this older tool using `DOTNET_ROLL_FORWARD=Major`.

Package archive hashes, assembly hashes, SDK/tool versions, and the actual image
identity are saved in the report. Every trial uses that same image identity,
even if someone retags the image while the experiment runs. Rebuilding can change
OS package layers; compare recorded image identities when reproducing results.

The three dependency cases investigate queue/batch memory bounds and failed
batches, retry scheduling, and first-event scheduling. Their questions require
crossing from the checkout into the batching dependency. Prompts name neither
ILSpy nor decompilation. The queue/retry prompt asks only the operational question,
without instructing the model to trace dependency implementations. The two
repository-only controls ask about configuration
branching and argument validation that are visible directly in the checkout.

The model receives the project source and restored packages, but no dependency
source checkout or web access. This holds alternative retrieval paths constant
and makes this specifically an offline dependency-investigation benchmark.

Reviewer orientation, established by manually inspecting the pinned assembly:

- `PeriodicBatchingSink` maintains a channel separately from `_currentBatch`.
  `Emit()` uses `TryWrite()`; `LoopAsync()` clears the batch after successful
  emission and consults failure thresholds for dropping batches/queued events.
- Internal `FailureAwareBatchScheduler` owns retry timing. Its constants include
  a five-second minimum backoff base, ten-minute maximum backoff interval,
  eight failures before dropping a batch, and ten before dropping the queue.
  The configured period participates in the interval calculation, so the
  ten-minute constant is not an unconditional cap for every possible period.
- First-event behavior must be traced through
  `PeriodicBatchingSinkOptions.EagerlyEmitFirstEvent` and `LoopAsync()` in this
  version. Do not substitute assumptions from newer Serilog batching implementations.

These notes establish that there is meaningful dependency implementation to
investigate. They are not injected into model prompts, and answer correctness is
not scored by this activation experiment.

## Measurement and interpretation

The primary endpoint for dependency cases is at least one successful ILSpy
decompilation of an assembly whose content hash belongs to the designated package
version. All packaged target-framework variants are recognized, as are copies of
those assemblies. A run needs a zero tool exit code and C#/IL output or newly
written `.cs`/`.il` files. Merely finding an assembly, reading the skill, naming
ILSpy, proposing a command, printing help, listing types, or failing to decompile
does not count. Attempts and successful decompilation of any assembly are also
recorded as diagnostics.

For each model:

```text
activation rate = activated trials / valid matched pairs
uplift (percentage points) = 100 × (skill rate − baseline rate)
```

Only pairs with two observed, non-error trials contribute. Budget exhaustion is
a valid observation within the assigned budget. Provider/infrastructure errors
or missing partners exclude the entire pair. Reports distinguish started pairs,
valid pairs, excluded pairs, and the complete planned schedule. No valid pairs
produces null rates rather than a misleading zero.

Repository-only controls use **any successful assembly decompilation** as their
endpoint, because the question needs no dependency inspection. A positive uplift
there may indicate unnecessary tool use; it is not folded into the primary rate.
The report also includes skill-only and baseline-only discordant pairs, attempts,
skill loads, served model IDs, request IDs in transcripts, token counts, and a
descriptive paired standard error when there are at least two valid pairs.
That standard error does not account for correlation between repeated prompts.
This initial dataset covers one project and one dependency; it does not establish
general behavior across OSS projects, and successful tool use does not establish
that the final answer is correct.

Instrumentation wraps the installed `ilspycmd` entry point, including its normal
absolute path, plus `dnx ilspycmd`. The real executable and DLL can be invoked
directly to bypass those wrappers. Review transcripts for alternative invocation
paths before interpreting a measured zero. The wrapper records are cooperative
measurement instrumentation, not tamper-proof evidence against an adversarial
agent; trials can write their `/tmp` telemetry. The source, tool installation,
packages, and root filesystem are read-only, and trial containers receive no
host mounts or provider keys. Shell output is drained with bounded host buffers.

## Results and local checks

The chosen `--output` JSON is checkpointed after every trial. It includes the
harness revision and source hashes. A sibling directory
with the same stem stores each conversation, model usage, tool results, and
ILSpy execution events. Generated decompilation files are ephemeral; their
hashes and paths are retained. Containers are removed on exit. Results are
ignored by Git.

Deterministic checks, with no paid API calls:

```bash
uv run --frozen pytest -q
uv run --frozen python scripts/validate-datasets.py
uv run --frozen dotnet-evals prepare-ilspy
```

Unit tests use scripted provider responses to exercise tool-loop behavior,
skill availability, score exclusions, paired metrics, error checkpointing,
output limits, and dataset validation. `prepare-ilspy` reaches the actual tool
and binary. Neither establishes real-model activation uplift; that requires the
credentialed comparison run.
