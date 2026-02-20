"""Runner for realistic skill activation evaluation."""

from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console

from ..config import (
    DEFAULT_SKILLS_REPO,
    OPENROUTER_API_KEY,
    get_model_id,
)
from ..skills.catalog import build_skill_catalog, build_compressed_index
from ..skills.loader import load_skills_from_plugin_json
from .detection import detect_skill_references
from .mechanisms import (
    CompressedIndexDiscovery,
    DiscoveryMechanism,
    FatIndexDiscovery,
    ToolBasedDiscovery,
)
from .metrics import ActivationResult, ActivationResults, compute_accuracy

console = Console()


def load_activation_dataset(dataset_path: Path) -> list[dict]:
    """Load test cases from a JSONL file."""
    cases = []
    with open(dataset_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


def build_mechanisms(
    mechanism_names: list[str],
    skills_repo: Path,
) -> dict[str, DiscoveryMechanism]:
    """Build the requested discovery mechanisms."""
    repo = skills_repo
    plugin_json = repo / ".claude-plugin" / "plugin.json"
    skills = load_skills_from_plugin_json(plugin_json)
    all_skill_names = [s.metadata.name for s in skills]

    mechanisms: dict[str, DiscoveryMechanism] = {}

    if "tool" in mechanism_names:
        mechanisms["tool"] = ToolBasedDiscovery(skills)

    if "compressed" in mechanism_names:
        readme = repo / "README.md"
        compressed_index = build_compressed_index(readme) if readme.exists() else ""
        mechanisms["compressed"] = CompressedIndexDiscovery(
            compressed_index, all_skill_names
        )

    if "fat" in mechanism_names:
        catalog = build_skill_catalog(skills)
        mechanisms["fat"] = FatIndexDiscovery(catalog, all_skill_names)

    return mechanisms


def run_activation_eval(
    model: str,
    dataset_path: Path,
    mechanism_names: list[str] | None = None,
    skills_repo: Path | None = None,
) -> dict[str, ActivationResults]:
    """Run the realistic activation evaluation.

    Args:
        model: Model name (haiku/sonnet/opus) or full model ID.
        dataset_path: Path to JSONL dataset file.
        mechanism_names: Which mechanisms to test. Defaults to all three.
        skills_repo: Path to dotnet-skills repo.

    Returns:
        Dict mapping mechanism name to aggregated results.
    """
    if mechanism_names is None:
        mechanism_names = ["tool", "compressed", "fat"]

    repo = skills_repo or DEFAULT_SKILLS_REPO
    model_id = get_model_id(model)
    api_key = OPENROUTER_API_KEY
    api_base = "https://openrouter.ai/api/v1"

    mechanisms = build_mechanisms(mechanism_names, repo)
    cases = load_activation_dataset(dataset_path)

    # Load all skill names for accuracy computation
    plugin_json = repo / ".claude-plugin" / "plugin.json"
    skills = load_skills_from_plugin_json(plugin_json)
    all_skill_names = [s.metadata.name for s in skills]

    results_by_mechanism: dict[str, ActivationResults] = {}

    for mech_name, mechanism in mechanisms.items():
        console.print(f"\n[bold cyan]--- Mechanism: {mech_name} ---[/bold cyan]")
        agg = ActivationResults(mechanism=mech_name)

        for i, case in enumerate(cases):
            case_id = case["id"]
            expected_skills = case.get("expected_skills", [])
            acceptable_skills = case.get("acceptable_skills", [])
            should_activate = case.get("should_activate", len(expected_skills) > 0)

            console.print(
                f"  [{i+1}/{len(cases)}] {case_id}...",
                end=" ",
            )

            try:
                mech_result = mechanism.run(
                    task=case["user_prompt"],
                    model=model_id,
                    api_key=api_key,
                    api_base=api_base,
                )

                accuracy = compute_accuracy(
                    mech_result.activated_skills,
                    expected_skills,
                    acceptable_skills,
                )

                status = (
                    "[green]activated[/green]" if mech_result.activated
                    else "[dim]no activation[/dim]"
                )
                if mech_result.activated:
                    status += f" → {', '.join(mech_result.activated_skills)}"
                console.print(status)

                result = ActivationResult(
                    case_id=case_id,
                    mechanism=mech_name,
                    should_activate=should_activate,
                    activated=mech_result.activated,
                    activated_skills=mech_result.activated_skills,
                    expected_skills=expected_skills,
                    acceptable_skills=acceptable_skills,
                    accuracy=accuracy,
                    response_text=mech_result.response_text,
                    prompt_tokens=mech_result.prompt_tokens,
                    completion_tokens=mech_result.completion_tokens,
                )

            except Exception as e:
                console.print(f"[red]ERROR: {e}[/red]")
                result = ActivationResult(
                    case_id=case_id,
                    mechanism=mech_name,
                    should_activate=should_activate,
                    activated=False,
                    activated_skills=[],
                    expected_skills=expected_skills,
                    acceptable_skills=acceptable_skills,
                    accuracy=0.0,
                    response_text=f"ERROR: {e}",
                    prompt_tokens=0,
                    completion_tokens=0,
                )

            agg.record(result)

        results_by_mechanism[mech_name] = agg

    return results_by_mechanism
