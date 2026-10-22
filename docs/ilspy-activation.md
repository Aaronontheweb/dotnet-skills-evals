# ILSpy activation uplift

This experiment asks: **how much does making `ilspy-decompile` available increase
successful use of ILSpy to inspect a relevant NuGet dependency?**

Each model/case/repetition gets a matched pair of fresh containers and separate
conversations. Baseline has the registered skill catalog minus `ilspy-decompile`;
treatment has the full catalog. Both have the same installed ILSpy, shell and
research tools, source, packages, prompt, resource limits, and model settings. The treatment
advertises the skill through `invoke_skill`; its instructions are loaded only if
the model requests them. Skill loading is recorded separately from ILSpy use.

The shared system prompt asks agents to consider the index explicitly:

> Decide if any of the skills in your index might be helpful towards accomplishing your goals.

It identifies the `invoke_skill` tool description as the index and shows the
arguments for loading a helpful skill: `{"skill_name": "<skill name from the index>"}`.
Both conditions receive this instruction. The completed 54-trial pilot used the
earlier optional wording, "You may load available skills with invoke_skill when useful."

This uses a controlled LiteLLM/OpenRouter tool loop, rather than a native coding
assistant's system prompt, permission model, or built-in tools. Conclusions apply
to this agent environment. There are no API calls to a judge.

## Setup and credentials

Requires Linux or macOS with Docker running, Git, and uv. Docker runs Linux
containers. Python 3.11+ is managed by uv; .NET and ILSpy live inside the fixture.
The fixture build needs public GitHub, NuGet, Debian and Microsoft registry access.
Trial shells run offline, with no host mounts or credentials passed in. Research
tools retrieve public internet content through the runner and copy requested
source snapshots or symbols into the container.

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

No separate Anthropic or OpenAI key is required. Public GitHub code search needs
`GITHUB_TOKEN` or `GH_TOKEN`, or an existing local `gh auth login`. The runner
captures that token internally; it is never included in tool arguments, prompts,
reports, or containers. No private repository access is needed. Runs require this
credential so code search is available in both arms; preflight reports whether
one is configured without validating it. The existing harness routes all subject
models through OpenRouter, including web search. A model must support function tools.
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

## Available investigation methods

Both arms receive these tools from the first model request:

| Tool | Behavior |
| --- | --- |
| `shell` | Search the project, restored packages, downloaded source, and run the installed SDK or ILSpy. The shell has no network. |
| `openrouter:web_search` | Native server search using Exa: at most 3 uses per model request, 5 results per search, 2,000 characters per result. Uses the OpenRouter key and incurs search charges. |
| `fetch_url` | Retrieve a public page or raw source URL, returning text and a content hash. |
| `github_search` | Search public repositories or issues/PRs; search code using `repo:owner/name` scopes validated as public before searching. Code search covers the default branch. |
| `checkout_repository` | Resolve a public tag/branch/commit to its full SHA and put that source snapshot in the container. Returns the SHA and archive hash. |
| `sourcelink_documents` | Read assembly debug metadata and matching Portable PDBs, including embedded PDBs or downloads from NuGet/Microsoft symbol servers; list source documents and SourceLink URLs. |
| `read_source` | Retrieve SourceLink or embedded source and verify its checksum against the matching PDB. |
| `invoke_skill` | Load a registered skill on request; only the target skill's availability differs between arms. |

Nothing forces the model to inspect a dependency, search, or use ILSpy. SourceLink
failures remain visible tool errors or symbol lookup failures, so the model can
try another method. GitHub code search does not prove what an older package
version contains; a resolved checkout or matching PDB provides version evidence.

At implementation time, the NuGet symbol server and symbol-package endpoint
returned 404 for `Serilog.Sinks.PeriodicBatching` 4.0.0. Its `v4.0.0` GitHub
checkout remains available. The live SourceLink test uses the fixture's restored
`Serilog` 3.1.1 assembly, whose published PDB and original source are available.
Adding the tools cannot supply symbols a package author did not publish.

Public pages and source can change. The run saves retrieved bytes, hashes,
timestamps and URLs under `retrieval-cache`, plus client tool arguments and
results in each trial artifact. OpenRouter search usage and returned citations
are retained as supplied by the API; this is not a full search-result replay.
The HTTP cache is shared across arms within a run. Credentials are excluded from
cache metadata. Host retrieval rejects nonpublic addresses and archive links or
path traversal; repository code is never executed on the host.

Rebuild with `prepare-ilspy` after pulling these changes; the image now includes
the metadata reader. Earlier offline-only pilot results belong to a different
tool environment and should be reported separately.

## Pilot size

Run the three dependency cases with **3 repetitions per model**. Across
three models this schedules **54 trials** (3 cases × 3 models × 3 repetitions × 2 arms),
or 27 matched pairs. Five repetitions would schedule **90 trials**. Review transcripts to confirm
the research tools work and that the model has a meaningful choice of methods
before expanding. Neither size supports a precise general activation-rate claim;
these questions cover one project/dependency. Selecting just one case schedules
18 trials at three repetitions, or 30 at five repetitions, across three models.

For example, repeat `--model` with each explicit subject model ID:

```bash
uv run --frozen dotnet-evals eval-ilspy \
  --model 'openrouter/<provider>/<opus-model-id>' \
  --model 'openrouter/<provider>/<sonnet-model-id>' \
  --model 'openrouter/<provider>/<haiku-model-id>' \
  --case seq-queue-retry --case seq-retry-timing --case seq-first-event \
  --repetitions 3 \
  --output results/ilspy/research-pilot-3x.json
```

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
completion tokens per request, a 200,000 total-token stopping threshold, 900
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
ILSpy nor decompilation. All three ask operational questions without directing
the model to inspect a dependency, trace implementations, or identify types and methods. The two
repository-only controls ask about configuration
branching and argument validation that are visible directly in the checkout.

The model starts with the project source and restored packages. It may retrieve
dependency source, search public material, or decompile the installed assembly.
Those alternatives are identical in both conditions. The retry-timing and
first-event prompts use the approved issue-report replacements. Repository-only
controls remain explicit repository investigations and are reported separately.

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

### Exposure, loading, and execution diagnostics

**Availability includes the index entry.** The name and description can cue an
ILSpy command without the model ever opening `SKILL.md`. Such execution counts
toward the primary outcome. A zero body-load count does not establish zero impact
from making the skill available.

Schema version 3 adds `skill_diagnostics` to trial records and transcripts:

| Diagnostic | Evidence |
| --- | --- |
| `target_index_present`, `index_evidence` | Whether the outgoing skill-router description includes the target entry. This records inclusion in a request, not proof the model attended to it. Historical reports can reconstruct inclusion from condition and skill-snapshot provenance; they label that evidence separately. |
| `skill_reads`, `target_body_loaded` | Successful `invoke_skill` results, matched by tool-call ID. Failed requests do not count. `SKILL.md` reads are distinguished from reference reads. |
| `target_body_in_model_request` | Whether a subsequent model request actually included the returned instructions. A shell call in the same response as a skill-load call has not yet received those instructions. |
| `target_reference_reads` | Successful reads of the target skill's supporting markdown, including repeated reads. |
| `target_execution_without_body_load`, `target_execution_after_body_load` | Successful target decompilation before/after the first model request containing the body. Missing historical timing is unknown, not a zero. Neither label attributes motivation or causation. A trial can have both kinds of execution. |

The `summary` retains the existing execution rates and adds per-arm `diagnostics`
using **only valid matched pairs**, plus `saved_trials` with stopping reasons for
**all saved trials**, including excluded partners. The console shows these
denominators separately. Attempts, successful decompilation of any assembly, and
successful target decompilation remain separate measurements. Reference reads
count requests; other diagnostic counts are trials.

The legacy `loaded_skills` field records any successful file read for a skill;
use `skill_diagnostics.target_body_loaded` for a precise body-load measurement.

### Harness fidelity

The current profile is explicitly named `custom-tool-index-v1`. Its catalog lives
in a tool description, and its skill files live on the host, accessible through
`invoke_skill`. There are no native skill directories or paths in trial
containers. These diagnostics establish what this custom loop supplied and did;
they do not establish parity with Claude Code or Codex.

This controlled loop can test whether skill availability changes ILSpy use in
this environment. Native-harness fidelity is not a prerequisite for that
comparison. Claims specifically about Claude Code or Codex would require a
separate native-harness evaluation. Keep the baseline/treatment difference limited
to the target skill, and report results from different harness profiles separately.

Instrumentation wraps the installed `ilspycmd` entry point, including its normal
absolute path, plus `dnx ilspycmd`. The real executable and DLL can be invoked
directly to bypass those wrappers. Review transcripts for alternative invocation
paths before interpreting a measured zero. The wrapper records are cooperative
measurement instrumentation, not tamper-proof evidence against an adversarial
agent; trials can write their `/tmp` telemetry. The source, tool installation,
packages, and root filesystem are read-only, and trial containers receive no
host mounts or provider keys. Shell output is drained with bounded host buffers.

## Petabridge.Cmd case

`datasets/ilspy/petabridge-cmd.jsonl` contains a separate support-console case using
`Petabridge.Cmd.Common` 1.5.2, the command parser used by Petabridge.Cmd. The small
application demonstrates quote characters changing before its echo handler
receives the message. The prompt asks for the cause and a reliable way to preserve
the message; it does not suggest a tool or mention source availability.

The package is downloaded from NuGet with a committed dependency lock. Its matching
source repository is not publicly accessible. Research tools remain available in
both arms. Only successful decompilation of `Petabridge.Cmd.Common.dll` counts as
the primary endpoint; answer correctness remains ungraded.

The fixture derives from the Seq image to retain the same SDK, ILSpy wrappers and
source metadata helper. It replaces the project checkout with a deterministic Git
snapshot of the support console, and builds it so local execution works offline.
The original Seq dataset and image remain separate.

```bash
# Prepare the common base first if it is not already present.
uv run --frozen dotnet-evals prepare-ilspy
uv run --frozen dotnet-evals prepare-ilspy --fixture petabridge-cmd

# Independent case: three repetitions, both conditions, per selected model.
uv run --frozen dotnet-evals eval-ilspy \
  --dataset datasets/ilspy/petabridge-cmd.jsonl \
  --case petabridge-cmd-quotes \
  --image dotnet-evals-ilspy:petabridge-cmd-1.5.2 \
  --model openrouter/anthropic/claude-opus-5.5 \
  --model openrouter/anthropic/claude-sonnet-5.5 \
  --model openrouter/anthropic/claude-haiku-5.5 \
  --repetitions 3 --max-total-tokens 200000 \
  --output results/ilspy/petabridge-cmd-independent.json
```

Add `--preflight-only` to check the fixture and count the 18 planned trials without
model API calls. Use a fresh output path for each run. The runtime reproduction,
dependency hashes and real ILSpy execution control are checked before paid runs.

## Results and local checks

The chosen `--output` JSON is checkpointed after every trial. It includes the
harness revision and source hashes. A sibling directory
with the same stem stores each conversation, model usage, tool results, and
research tool events, search usage/citations and ILSpy execution events. Generated decompilation files are ephemeral; their
hashes and paths are retained. Containers are removed on exit. Results are
ignored by Git.

New transcripts also contain `request_context`: the exact initial messages,
condition-specific catalog, and tool definitions supplied to LiteLLM. Each
`requests` entry records the request parameters, timestamp, transcript-prefix
length, and hashes of its messages and tools. The prefix reconstructs that
request's history without duplicating the full conversation on every step.
Credentials are not included. This captures the client's input to LiteLLM;
OpenRouter's downstream transformation or provider rendering is not recorded.

### Re-summarize saved results without API calls

```bash
uv run --frozen dotnet-evals summarize-ilspy \
  results/ilspy/original-run.json \
  --output results/ilspy/original-run-diagnostics.json
```

This command needs no credentials, Docker, or skill checkout. It re-scores saved
wrapper events against the original fixture hashes, extracts successful skill
reads from the transcripts, and writes a **new** report. Original reports and
transcripts are preserved; an existing output path is rejected. Keep transcripts
beside the original report in its same-stem directory when moving a results
bundle. Missing transcripts cause an error rather than invented zeros.

Derived reports retain the original run status, schedule, budgets and harness
provenance. `reanalysis` records input hashes, diagnostic-code hashes, and any
execution-score changes. Historical requests that were not captured stay
unavailable; reconstructed exposure is explicitly labeled. The CLI verifies
request hashes when processing newly captured artifacts.

See [the saved-run diagnostic summary](ilspy-results-2026-10-20.md) for the
completed pilot and separately reported, user-stopped prompt-only rerun.
The [2026-10-21 rerun](ilspy-results-2026-10-21.md) completed the same 54-trial
comparison using the existing harness and updated diagnostics.

Deterministic checks, with no paid API calls:

```bash
uv run --frozen pytest -q -m 'not openrouter and not network'
uv run --frozen python scripts/validate-datasets.py
uv run --frozen dotnet-evals prepare-ilspy
```

The source metadata integration tests require a local .NET 10 SDK. They compile
real Portable PDBs and exercise HTTP source/symbol retrieval, embedded source,
missing symbols, mismatched PDBs, and incorrect source checksums. A separate CI
job runs these tests; the Python matrix runs the other deterministic checks.

Optional live checks, outside CI:

```bash
# Public GitHub search, versioned checkout and actual NuGet SourceLink through Docker.
uv run --frozen pytest -q -m network --run-network

# One bounded paid web-search request. Uses Haiku by default; override via
# OPENROUTER_TEST_MODEL=openrouter/<provider>/<model-id>.
uv run --frozen pytest -q -m openrouter --run-openrouter
```

These are tool integration checks, not activation evals. OpenRouter checks are
skipped unless explicitly enabled locally and are **always skipped when `CI` is
set**, including manual workflows. CI also clears `OPENROUTER_API_KEY` and excludes
the paid tests. No API key is configured as a CI secret.

Unit tests use scripted provider responses to exercise tool-loop behavior,
skill availability, score exclusions, paired metrics, error checkpointing,
output limits, and dataset validation. `prepare-ilspy` reaches the actual tool
and binary. Neither establishes real-model activation uplift; that requires the
credentialed comparison run.
