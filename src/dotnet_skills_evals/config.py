"""Configuration for model providers, paths, and eval settings."""

import os
import subprocess
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

SKILLS_REPO_URL = "https://github.com/Aaronontheweb/dotnet-skills.git"

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


def ensure_skills_repo(repo_path: Path | None = None) -> Path:
    """Ensure the dotnet-skills repo exists locally, cloning if needed.

    Args:
        repo_path: Explicit path override. Defaults to DEFAULT_SKILLS_REPO.

    Returns:
        The validated repo path.

    Raises:
        RuntimeError: If the repo can't be cloned or is missing expected structure.
    """
    path = repo_path or DEFAULT_SKILLS_REPO

    if not path.exists():
        parent = path.parent
        parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", SKILLS_REPO_URL, str(path)],
            check=True,
        )

    # Validate expected structure
    plugin_json = path / ".claude-plugin" / "plugin.json"
    if not plugin_json.exists():
        raise RuntimeError(
            f"dotnet-skills repo at {path} is missing .claude-plugin/plugin.json. "
            f"Expected a clone of {SKILLS_REPO_URL}"
        )

    skills_dir = path / "skills"
    if not skills_dir.exists() or not any(skills_dir.iterdir()):
        raise RuntimeError(
            f"dotnet-skills repo at {path} has no skills/ directory or it's empty."
        )

    return path


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
