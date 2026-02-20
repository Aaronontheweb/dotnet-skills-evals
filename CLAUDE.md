# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

## Repository Purpose

Evaluation harness for the [dotnet-skills](https://github.com/Aaronontheweb/dotnet-skills) Claude Code marketplace plugin. Uses DSPy to test skill activation accuracy, skill effectiveness, and size impact via the Anthropic API.

## Key Constraint: Single-File Skills

**Skills must remain as single SKILL.md files.** The dotnet-skills plugin serves Claude Code, GitHub Copilot, and OpenCode. Copilot only reads the main SKILL.md file and cannot follow references to sibling files. Progressive disclosure (multi-file splitting) is off the table. If skills need improvement, restructure or trim within the single file.

## Project Layout

- `src/dotnet_skills_evals/` - Main Python package
  - `skills/` - Loader and catalog builder for parsing dotnet-skills repo
  - `eval_activation/` - Skill routing accuracy evaluation
  - `eval_effectiveness/` - Skill quality impact evaluation (baseline vs enhanced)
  - `reporting/` - Results aggregation and display
  - `cli.py` - Click CLI entry point
  - `config.py` - Model IDs, paths, constants
- `datasets/` - Test cases (JSONL) and rubrics (YAML)
- `tests/` - pytest unit tests

## External Dependencies

- **dotnet-skills repo**: Located at `~/repositories/dotnet-skills`. The skill loader reads SKILL.md files directly from this path. Configurable via `DOTNET_SKILLS_REPO` env var.
- **Anthropic API**: Required for running evals. Set `ANTHROPIC_API_KEY` in `.env`.

## Development

```bash
# Install dependencies
uv sync

# Install with dev dependencies
uv sync --extra dev

# Run tests
uv run pytest

# Run evals
uv run dotnet-evals eval-activation --model haiku --dataset datasets/activation/akka_test_cases.jsonl
```

## Conventions

- Python 3.11+ with type hints
- DSPy signatures for all LLM interactions
- JSONL for test case datasets, YAML for evaluation rubrics
- `click` for CLI, `rich` for console output
- All eval commands support `--model` flag (haiku/sonnet/opus)

## Dataset Authoring

Test cases should be realistic .NET development scenarios. For activation tests, include:
- `expected_skills`: The primary skill(s) that should be selected
- `acceptable_skills`: Skills that are reasonable but not ideal
- `category`: For grouping in reports

For effectiveness tests, pair each task with a rubric file that defines weighted scoring criteria specific to that skill's domain expertise.
