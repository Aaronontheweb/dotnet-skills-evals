"""Runner for skill activation evaluation."""

from __future__ import annotations

import json
from pathlib import Path

import dspy

from ..config import configure_dspy, PLUGIN_JSON, DEFAULT_SKILLS_REPO
from ..skills.catalog import build_skill_catalog, build_compressed_index
from ..skills.loader import load_skills_from_plugin_json
from .metrics import ActivationResults
from .signatures import SkillActivation, SkillActivationWithIndex


def load_activation_dataset(dataset_path: Path) -> list[dict]:
    """Load test cases from a JSONL file."""
    cases = []
    with open(dataset_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


def run_activation_eval(
    model: str,
    dataset_path: Path,
    with_index: bool = False,
    skills_repo: Path | None = None,
) -> ActivationResults:
    """Run the activation evaluation.

    Args:
        model: Model name (haiku/sonnet/opus) or full model ID.
        dataset_path: Path to JSONL dataset file.
        with_index: Whether to include the compressed routing index.
        skills_repo: Path to dotnet-skills repo (defaults to config).

    Returns:
        Aggregated evaluation results.
    """
    configure_dspy(model)

    # Load skills and build catalog
    repo = skills_repo or DEFAULT_SKILLS_REPO
    plugin_json = repo / ".claude-plugin" / "plugin.json"
    skills = load_skills_from_plugin_json(plugin_json)
    catalog = build_skill_catalog(skills)

    # Optionally load compressed index
    compressed_index = ""
    if with_index:
        readme = repo / "README.md"
        if readme.exists():
            compressed_index = build_compressed_index(readme)

    # Set up DSPy module
    if with_index and compressed_index:
        predictor = dspy.ChainOfThought(SkillActivationWithIndex)
    else:
        predictor = dspy.ChainOfThought(SkillActivation)

    # Load dataset
    cases = load_activation_dataset(dataset_path)
    results = ActivationResults()

    for case in cases:
        try:
            if with_index and compressed_index:
                prediction = predictor(
                    available_skills=catalog,
                    compressed_index=compressed_index,
                    user_task=case["user_prompt"],
                )
            else:
                prediction = predictor(
                    available_skills=catalog,
                    user_task=case["user_prompt"],
                )

            predicted = prediction.selected_skills
            # Handle case where DSPy returns strings instead of lists
            if isinstance(predicted, str):
                predicted = [s.strip() for s in predicted.split(",") if s.strip()]

            reasoning = getattr(prediction, "reasoning", "")

        except Exception as e:
            predicted = []
            reasoning = f"ERROR: {e}"

        results.record(
            case_id=case["id"],
            expected_skills=case["expected_skills"],
            acceptable_skills=case.get("acceptable_skills", []),
            predicted_skills=predicted,
            reasoning=reasoning,
        )

    return results
