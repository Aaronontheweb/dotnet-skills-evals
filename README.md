# dotnet-skills-evals

Evaluation harness for the [dotnet-skills](https://github.com/Aaronontheweb/dotnet-skills) Claude Code plugin. Tests whether AI coding assistants correctly activate and benefit from .NET development skills.

## Goals

1. **Skill Activation Accuracy** - Given a user's .NET development task, does the model correctly identify which skill(s) to use from the catalog of 31 skills?
2. **Skill Effectiveness** - Once activated, does a skill actually improve the quality of generated code compared to a baseline (no skill)?
3. **Size Impact** - Several skills exceed Claude's recommended 500-line limit. Does this hurt effectiveness, or are larger skills fine?

## Platform Parity Constraint

The dotnet-skills plugin is consumed by multiple AI coding assistants:
- **Claude Code** (primary) - reads SKILL.md on activation, can read additional files
- **GitHub Copilot** - reads SKILL.md from `.github/skills/` directories
- **OpenCode** - reads SKILL.md from `~/.config/opencode/skills/`

**Skills must remain as single SKILL.md files.** Progressive disclosure (splitting into SKILL.md + reference files) is not an option because GitHub Copilot only reads the main SKILL.md and cannot follow references to sibling files. If skills need to shrink, we trim content within the single file rather than splitting.

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

- **Fix "serialization" false positive** — filter short/generic skill names from substring detection, or require explicit citation format (e.g., `[skill:serialization]`)
- **Investigate Opus detection gap** — Opus may be using skill knowledge without citing names; need alternative detection (semantic similarity, rubric-based judging) to determine if Opus is truly ignoring skills or just not naming them
- **Improve skill description differentiation** — Haiku's compressed accuracy of 46.2% suggests Akka skill descriptions overlap too much; need clearer boundaries between `akka-net-management`, `akka-net-aspire-configuration`, and `akka-net-best-practices`
- **Effectiveness evals** — measure whether skills actually improve code quality vs. baseline (no skill injected)
- **Size impact evals** — test full SKILL.md vs truncated-to-500-lines to determine if oversized skills hurt or help
- **Variant comparison** — test original vs condensed authoring strategies for oversized skills

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
