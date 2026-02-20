# dotnet-skills-evals

Evaluation harness for the [dotnet-skills](https://github.com/Aaronontheweb/dotnet-skills) Claude Code plugin. Tests whether AI coding assistants correctly activate and benefit from .NET development skills.

## Goals

1. **Skill Activation Accuracy** - Given a user's .NET development task, does the model correctly identify which skill(s) to use from the catalog of 31 skills?
2. **Skill Effectiveness** - Once activated, does a skill actually improve the quality of generated code compared to a baseline (no skill)?
3. **Size Impact** - Several skills exceed Claude's recommended 500-line limit. Does this hurt effectiveness, or are larger skills fine?

## Platform Parity

The dotnet-skills plugin is consumed by multiple AI coding assistants:
- **Claude Code** (primary) - reads SKILL.md on activation, can read additional files via progressive disclosure
- **GitHub Copilot** - [supports agent skills](https://code.visualstudio.com/docs/copilot/customization/agent-skills) with multi-file progressive disclosure (since Dec 2025)
- **OpenCode** - reads SKILL.md from `~/.config/opencode/skills/`

All three platforms support the same skill directory structure with progressive disclosure: SKILL.md serves as the entry point (<500 lines recommended), with sibling reference files loaded on demand. See [Claude skill best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices#progressive-disclosure-patterns).

## Current Focus: Akka.NET Skills

The initial evaluation targets the 5 Akka.NET skills, which are the most critical and also the most likely to have overlap/confusion issues:

| Skill | Lines | Over 500-line limit? |
|-------|-------|---------------------|
| akka-net-best-practices | 1123 | 2.2x |
| akka-net-testing-patterns | 1280 | 2.6x |
| akka-hosting-actor-patterns | 614 | 1.2x |
| akka-net-management | 685 | 1.4x |
| akka-net-aspire-configuration | 719 | 1.4x |

## Architecture

This harness connects to Claude models via **OpenRouter + LiteLLM** for raw API calls. Claude Code cannot invoke or test itself programmatically. We simulate skill discovery by testing three mechanisms:

1. **Tool-based** (`tool`) — model gets a `Skill` tool listing all skill names + descriptions (mirrors Claude Code's plugin system)
2. **Compressed index** (`compressed`) — the terse Vercel-style routing snippet (~15 lines) injected into the system prompt
3. **Fat index** (`fat`) — all 31 skill names + full descriptions injected into the system prompt

All mechanisms share the same neutral system prompt with no mention of skills or evaluation. Test prompts are goal-oriented developer conversations with C# code snippets — not quiz-style questions about skills.

For effectiveness testing, full SKILL.md content is injected as context.

## Activation Eval Results (31 cases, compressed vs fat)

Full run: 23 Akka.NET positive cases + 8 non-Akka negative cases. The tool mechanism was dropped from comparison — it has 100% activation rate (including 100% FPR on negatives), which measures tool-calling bias rather than skill discovery quality.

### Compressed Index

| Metric | Haiku | Sonnet | Opus |
|--------|-------|--------|------|
| Activation Rate | 45.2% | 41.9% | 16.1% |
| True Positive Rate | 56.5% | 56.5% | 17.4% |
| False Positive Rate | 12.5% | **0.0%** | 12.5% |
| Accuracy (when activated) | 46.2% | **84.6%** | 0.0% |
| Mean Prompt Tokens | 688 | 688 | 689 |
| Mean Completion Tokens | 2,315 | 2,337 | 2,770 |
| Mean Total Tokens | 3,002 | 3,025 | 3,459 |

### Fat Index

| Metric | Haiku | Sonnet | Opus |
|--------|-------|--------|------|
| Activation Rate | 16.1% | 19.4% | 12.9% |
| True Positive Rate | 13.0% | 21.7% | 13.0% |
| False Positive Rate | 25.0% | 12.5% | 12.5% |
| Accuracy (when activated) | 33.3% | 60.0% | 0.0% |
| Mean Prompt Tokens | 1,956 | 1,956 | 1,957 |
| Mean Completion Tokens | 2,262 | 2,123 | 2,643 |
| Mean Total Tokens | 4,217 | 4,078 | 4,600 |

### Key Learnings

1. **Sonnet + compressed index is the clear winner.** 56.5% TPR, 0% FPR, 84.6% accuracy when activated — best activation rate, best precision, zero false positives, all at the lowest token cost (~3K tokens/case).

2. **Compressed index outperforms fat index across all models.** Despite having ~3x fewer tokens (688 vs 1,956 prompt tokens), compressed achieves higher TPR and better accuracy on every model. The fat index's wall of text paradoxically makes models *less* likely to reference skills — information overload suppresses activation.

3. **Opus essentially doesn't activate from index-based discovery.** Every single "activation" across both mechanisms was a "serialization" substring false positive — 0% real accuracy. Opus treats the skill index as informational context but never cites specific skill names in responses. This is a detection methodology issue, not necessarily a model quality issue — Opus may be incorporating the knowledge without naming the skill.

4. **Haiku and Sonnet have identical TPR (56.5%) on compressed**, but Sonnet is far more accurate when it activates (84.6% vs 46.2%). Haiku often activates related-but-wrong Akka skills.

5. **"serialization" false positive in detection.** The skill name `serialization` is short enough that it gets substring-matched when models discuss serialization *concepts* in their responses. This is the only "activation" Opus shows. Need to filter short/generic skill names or require citation format.

6. **Sonnet compressed has perfect negative discrimination.** 0% FPR — never activated on any of the 8 non-Akka negative cases. Haiku and Opus both have 12.5% FPR on compressed (1 false positive each, both "serialization").

## Effectiveness Eval Results (Sonnet, 15 cases)

**Does having a skill loaded produce better code?** For each of 15 tasks across 5 Akka.NET skills, we generate code with and without the skill injected as context. An LLM judge (Sonnet) scores both outputs on a per-skill rubric with randomized A/B ordering to avoid position bias.

### Summary

| Metric | Value |
|--------|-------|
| Total Cases | 15 |
| Skill Wins | 13 |
| Baseline Wins | 2 |
| Ties | 0 |
| **Win Rate** | **86.7%** |
| Mean Baseline Score | 2.80 / 5 |
| Mean Enhanced Score | 4.40 / 5 |
| **Mean Improvement** | **+1.60** |

### Per-Skill Breakdown

| Skill | Cases | Win Rate | Mean Improvement |
|-------|-------|----------|------------------|
| akka-hosting-actor-patterns | 3 | 100.0% | +2.00 |
| akka-net-aspire-configuration | 3 | 100.0% | +2.33 |
| akka-net-testing-patterns | 3 | 100.0% | +2.33 |
| akka-net-management | 3 | 66.7% | +1.00 |
| akka-net-best-practices | 3 | 66.7% | +0.33 |

### Key Findings

1. **Skills overwhelmingly improve output quality.** 86.7% win rate with a +1.60 mean improvement on a 1-5 scale. The judge provides detailed, criterion-by-criterion reasoning referencing specific code patterns.

2. **Specialized skills show the largest gains.** Testing patterns (+2.33), Aspire configuration (+2.33), and hosting patterns (+2.00) teach the model things it genuinely doesn't know — modern Akka.Hosting.TestKit, Aspire orchestration patterns, GenericChildPerEntityParent. The baseline model defaults to legacy patterns (Akka.TestKit.Xunit2, static seed nodes, manual Props).

3. **General best-practices skill shows weakest improvement (+0.33).** Sonnet already knows general Akka.NET patterns like DistributedPubSub vs EventStream and supervision strategies. The skill helps at the margins but doesn't transform output quality.

4. **The two baseline wins are defensible.** eff-002 (RSS polling error handling): the baseline produced cleaner CancellationToken lifecycle management. eff-012 (health endpoints): the baseline used built-in Akka.Hosting health check methods while the enhanced version over-engineered with custom implementations. In both cases, the skill's extra context may have pushed the model toward more complex solutions when simpler ones were better.

## Size Impact Eval Results (Sonnet, 5 skills)

**Do oversized skills (>500 lines) hurt or help?** All 5 Akka skills exceed Claude's recommended 500-line SKILL.md limit. We ran effectiveness evals twice per skill: once with full content, once truncated to 500 lines.

### Comparison

| Skill | Lines | Full Improvement | Truncated (500) Improvement | Winner |
|-------|-------|------------------|----------------------------|--------|
| akka-net-best-practices | 1123 | +0.33 | **+0.67** | Truncated |
| akka-net-testing-patterns | 1280 | +2.67 | +2.67 | Same |
| akka-hosting-actor-patterns | 614 | **+2.67** | +2.33 | Full (+0.33) |
| akka-net-management | 685 | +0.67 | **+1.67** | Truncated |
| akka-net-aspire-configuration | 719 | **+2.33** | +1.67 | Full (+0.67) |

### Key Findings

1. **Truncation doesn't consistently help or hurt — it depends on the skill.** Two skills perform better truncated, one is identical, and two perform better with full content.

2. **For management, truncation dramatically improved results.** Win rate jumped from 66.7% to 100%, and the health endpoint task (eff-012) that was a *baseline win* at full size became an *enhanced win* when truncated. The extra content beyond 500 lines was actively confusing the model.

3. **Specialized skills benefit from full content.** Aspire configuration (+2.33 vs +1.67) and hosting patterns (+2.67 vs +2.33) — the model genuinely lacks training data for these topics, so the extra examples and reference material add real value.

4. **General-knowledge skills perform better truncated.** Best-practices and management cover topics where Sonnet has decent baseline knowledge. The extra content beyond 500 lines becomes noise that dilutes the signal.

5. **Progressive disclosure is the right solution.** Rather than choosing between "full" and "truncated", skills should keep their core patterns in SKILL.md (<500 lines) and move detailed examples/reference material into sibling files that are loaded on demand. This gives the model focused guidance by default while making specialized content available when the task calls for it. All three platforms (Claude Code, Copilot, OpenCode) support this pattern.

## Setup

```bash
# Clone
git clone https://github.com/Aaronontheweb/dotnet-skills-evals.git
cd dotnet-skills-evals

# Install (requires Python 3.11+)
uv sync

# Configure API key
cp .env.example .env
# Edit .env and add your OPENROUTER_API_KEY

# The dotnet-skills repo is cloned automatically on first run.
# Default path: ~/repositories/dotnet-skills
# Override with: export DOTNET_SKILLS_REPO=/path/to/dotnet-skills
```

## Usage

```bash
# Realistic skill activation eval (all 3 discovery mechanisms)
dotnet-evals eval-activation --model haiku --dataset datasets/activation/akka_test_cases.jsonl

# Run specific mechanism(s)
dotnet-evals eval-activation --model sonnet --mechanism compressed --mechanism fat \
    --dataset datasets/activation/akka_test_cases.jsonl

# Skill effectiveness (does the skill improve output quality?)
dotnet-evals eval-effectiveness --model sonnet --skill akka-net-best-practices

# Size impact (full skill vs truncated to 500 lines)
dotnet-evals eval-size --model sonnet --skill akka-net-best-practices --max-lines 500

# Compare authoring strategies (original vs condensed vs progressive disclosure)
dotnet-evals scaffold-variants  # Create template dirs for variant authoring
dotnet-evals eval-variants --model sonnet --skill akka-net-best-practices --dataset datasets/effectiveness/akka_test_cases.jsonl

# List all skills with sizes
dotnet-evals list-skills
```

## Dataset Format

### Activation test cases (`datasets/activation/*.jsonl`)

Test cases use goal-oriented developer prompts with C# code snippets (not documentation-style questions):

```json
{
  "id": "act-001",
  "user_prompt": "I have a notification system where actors publish events... [includes code snippet]",
  "expected_skills": ["akka-net-best-practices"],
  "acceptable_skills": [],
  "should_activate": true,
  "category": "best-practices-pubsub"
}
```

### Effectiveness test cases (`datasets/effectiveness/*.jsonl`)

```json
{
  "id": "eff-001",
  "skill_name": "akka-net-best-practices",
  "task": "Build an actor that publishes user notifications across cluster nodes",
  "rubric_file": "rubrics/akka-best-practices.yaml"
}
```

### Rubrics (`datasets/rubrics/*.yaml`)

Per-skill evaluation criteria with weighted scoring dimensions.

## Future Work

- **Reformat oversized skills with progressive disclosure** — Split the 5 Akka skills (614-1280 lines) into <500 line SKILL.md files with sibling reference files. Eval data shows this should preserve the gains for specialized content while eliminating noise for general-knowledge topics.
- **Run effectiveness evals on Haiku and Opus** — Current results are Sonnet-only. Haiku may need more skill guidance (per Claude docs: "Does the Skill provide enough guidance?"); Opus may need less.
- **Expand beyond Akka skills** — Test the 26 non-Akka skills (e.g., csharp-coding-standards at 1510 lines, testcontainers, aspire-integration-testing) to see if findings generalize.
- **Variant comparison** — Test original vs condensed vs progressive disclosure authoring strategies to quantify the improvement from restructuring.
- **Improve activation eval methodology** — The current text-detection approach has fundamental issues (see activation results above). Consider alternative approaches: semantic similarity matching, structured output with skill selection, or skip activation entirely and focus on effectiveness.

## Cost Estimates

| Eval Type | Cases | API Calls | Cost (Sonnet) |
|-----------|-------|-----------|---------------|
| Activation | ~31 | 31 | ~$0.50 |
| Effectiveness | ~20 | 60 | ~$3-5 |
| Size impact | ~10 | 60 | ~$3-5 |
| **Total MVP** | | | **~$10-15** |

Use `--model haiku` for cheaper iteration during dataset development.

## License

Apache 2.0
