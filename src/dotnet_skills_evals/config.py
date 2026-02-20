"""Configuration for model providers, paths, and eval settings."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# --- Model Provider Configuration ---
# Uses OpenRouter by default. Set OPENROUTER_API_KEY in .env.
# DSPy uses LiteLLM under the hood, which supports OpenRouter with the
# "openrouter/" prefix on model names.

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

# Model name mapping - all go through OpenRouter
MODELS = {
    "haiku": "openrouter/anthropic/claude-haiku-4-5",
    "sonnet": "openrouter/anthropic/claude-sonnet-4-5",
    "opus": "openrouter/anthropic/claude-opus-4.6",
}

# Judge model for effectiveness evaluation (should differ from subject model)
DEFAULT_JUDGE_MODEL = "sonnet"

# --- Paths ---
DEFAULT_SKILLS_REPO = Path(
    os.getenv("DOTNET_SKILLS_REPO", Path.home() / "repositories" / "dotnet-skills")
)

SKILLS_DIR = DEFAULT_SKILLS_REPO / "skills"
AGENTS_DIR = DEFAULT_SKILLS_REPO / "agents"
PLUGIN_JSON = DEFAULT_SKILLS_REPO / ".claude-plugin" / "plugin.json"

# Datasets
DATASETS_DIR = Path(__file__).parent.parent.parent / "datasets"
ACTIVATION_DATASET_DIR = DATASETS_DIR / "activation"
EFFECTIVENESS_DATASET_DIR = DATASETS_DIR / "effectiveness"
RUBRICS_DIR = DATASETS_DIR / "rubrics"

# --- Eval Settings ---
# Maximum lines for truncated skill variants (Claude best practice recommendation)
SKILL_LINE_LIMIT = 500

# Temperature for reproducible evals
EVAL_TEMPERATURE = 0.0

# Number of runs to average for final scores
DEFAULT_NUM_RUNS = 1


def get_model_id(model_name: str) -> str:
    """Resolve a short model name to its full LiteLLM model ID."""
    if model_name in MODELS:
        return MODELS[model_name]
    # Allow passing full model IDs directly
    return model_name


def configure_dspy(model_name: str) -> None:
    """Configure DSPy to use the specified model via OpenRouter."""
    import dspy

    model_id = get_model_id(model_name)
    lm = dspy.LM(
        model_id,
        api_key=OPENROUTER_API_KEY,
        api_base="https://openrouter.ai/api/v1",
        temperature=EVAL_TEMPERATURE,
    )
    dspy.configure(lm=lm)
