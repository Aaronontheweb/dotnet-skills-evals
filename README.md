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

This harness connects **directly to the Anthropic API via DSPy** - Claude Code cannot invoke or test itself programmatically. We simulate Claude Code's skill activation by:
1. Building a system prompt containing all skill names + descriptions (how Claude Code discovers skills)
2. Passing the user's task and asking the model to select skills
3. For effectiveness testing, injecting full SKILL.md content as context

## Setup

```bash
# Clone
git clone https://github.com/Aaronontheweb/dotnet-skills-evals.git
cd dotnet-skills-evals

# Install (requires Python 3.11+)
uv sync

# Configure API key
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY

# Ensure dotnet-skills repo is available locally
# Default path: ~/repositories/dotnet-skills
```

## Usage

```bash
# Skill activation accuracy (which skill gets selected?)
dotnet-evals eval-activation --model haiku --dataset datasets/activation/akka_test_cases.jsonl

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

```json
{
  "id": "act-001",
  "user_prompt": "My Akka.NET actors need to communicate across cluster nodes",
  "expected_skills": ["akka-net-best-practices"],
  "acceptable_skills": [],
  "category": "akka-pubsub"
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

## Cost Estimates

| Eval Type | Cases | API Calls | Cost (Sonnet) |
|-----------|-------|-----------|---------------|
| Activation | ~25 | 25 | ~$0.50 |
| Effectiveness | ~20 | 60 | ~$3-5 |
| Size impact | ~10 | 60 | ~$3-5 |
| **Total MVP** | | | **~$10-15** |

Use `--model haiku` for cheaper iteration during dataset development.

## License

Apache 2.0
