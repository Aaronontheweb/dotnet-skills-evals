"""Runner for skill effectiveness evaluation."""

from __future__ import annotations

import json
import random
from pathlib import Path

import dspy
import yaml

from ..config import (
    configure_dspy,
    ensure_skills_repo,
    get_model_id,
    DEFAULT_JUDGE_MODEL,
    DEFAULT_SKILLS_REPO,
    OPENROUTER_API_KEY,
    EVAL_TEMPERATURE,
    RUBRICS_DIR,
)
from ..skills.catalog import build_skill_context_for_eval
from ..skills.loader import load_all_skills, Skill
from ..skills.variants import SkillVariant, get_all_variants, load_original_variant
from .metrics import EffectivenessResults
from .signatures import DotNetTaskCompletion, QualityJudge


def load_effectiveness_dataset(dataset_path: Path) -> list[dict]:
    """Load test cases from a JSONL file."""
    cases = []
    with open(dataset_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


def load_rubric(rubric_file: str) -> str:
    """Load a rubric YAML file and format it as a string for the judge."""
    rubric_path = RUBRICS_DIR / rubric_file
    with open(rubric_path, encoding="utf-8") as f:
        rubric = yaml.safe_load(f)

    lines = [f"Skill: {rubric['skill_name']}", "Criteria:"]
    for criterion in rubric["criteria"]:
        lines.append(
            f"  - {criterion['name']} (weight: {criterion['weight']}): "
            f"{criterion['description']}"
        )
    return "\n".join(lines)


def run_effectiveness_eval(
    model: str,
    dataset_path: Path,
    skill_filter: str | None = None,
    truncate_at: int | None = None,
    judge_model: str | None = None,
    skills_repo: Path | None = None,
) -> EffectivenessResults:
    """Run the effectiveness evaluation.

    For each test case:
    1. Generate a baseline response (no skill guidance)
    2. Generate an enhanced response (with full skill content)
    3. Use a judge model to compare them against a rubric

    Args:
        model: Model name for generating responses.
        dataset_path: Path to JSONL dataset file.
        skill_filter: If set, only run cases for this skill name.
        truncate_at: If set, truncate skill content to this many lines.
        judge_model: Model name for the judge (defaults to DEFAULT_JUDGE_MODEL).
        skills_repo: Path to dotnet-skills repo.

    Returns:
        Aggregated effectiveness results.
    """
    # Configure subject model
    configure_dspy(model)
    subject_predictor = dspy.Predict(DotNetTaskCompletion)

    # Load skills
    repo = ensure_skills_repo(skills_repo)
    skills = load_all_skills(repo / "skills")
    skill_map = {s.metadata.name: s for s in skills}

    # Load dataset
    cases = load_effectiveness_dataset(dataset_path)
    if skill_filter:
        cases = [c for c in cases if c["skill_name"] == skill_filter]

    results = EffectivenessResults()

    for case in cases:
        skill_name = case["skill_name"]
        skill = skill_map.get(skill_name)
        if not skill:
            continue

        task = case["task"]
        rubric_str = load_rubric(case["rubric_file"])

        # 1. Generate baseline (no skill)
        try:
            baseline_pred = subject_predictor(
                skill_guidance="",
                task=task,
            )
            baseline_code = baseline_pred.code
        except Exception as e:
            baseline_code = f"ERROR: {e}"

        # 2. Generate enhanced (with skill)
        skill_content = build_skill_context_for_eval(skill, truncate_at)
        try:
            enhanced_pred = subject_predictor(
                skill_guidance=skill_content,
                task=task,
            )
            enhanced_code = enhanced_pred.code
        except Exception as e:
            enhanced_code = f"ERROR: {e}"

        # 3. Judge the comparison
        # Use a separate model for judging
        judge_model_name = judge_model or DEFAULT_JUDGE_MODEL
        judge_model_id = get_model_id(judge_model_name)
        judge_lm = dspy.LM(
            judge_model_id,
            api_key=OPENROUTER_API_KEY,
            api_base="https://openrouter.ai/api/v1",
            temperature=EVAL_TEMPERATURE,
        )

        # Randomize order to avoid position bias
        if random.random() < 0.5:
            a_code, b_code = baseline_code, enhanced_code
            a_is_baseline = True
        else:
            a_code, b_code = enhanced_code, baseline_code
            a_is_baseline = False

        try:
            with dspy.context(lm=judge_lm):
                judge_predictor = dspy.ChainOfThought(QualityJudge)
                judgment = judge_predictor(
                    task=task,
                    response_a=a_code,
                    response_b=b_code,
                    rubric=rubric_str,
                )

            # Map scores back to baseline/enhanced
            score_a = int(judgment.score_a) if judgment.score_a else 3
            score_b = int(judgment.score_b) if judgment.score_b else 3

            if a_is_baseline:
                baseline_score, enhanced_score = score_a, score_b
            else:
                baseline_score, enhanced_score = score_b, score_a

            # Determine winner in baseline/enhanced terms
            winner_raw = str(judgment.winner).strip().upper()
            if winner_raw == "TIE":
                winner = "tie"
            elif (winner_raw == "A" and a_is_baseline) or (
                winner_raw == "B" and not a_is_baseline
            ):
                winner = "baseline"
            else:
                winner = "enhanced"

            reasoning = getattr(judgment, "reasoning", "")

        except Exception as e:
            baseline_score = 3
            enhanced_score = 3
            winner = "tie"
            reasoning = f"JUDGE ERROR: {e}"

        results.record(
            case_id=case["id"],
            skill_name=skill_name,
            task=task,
            baseline_score=baseline_score,
            enhanced_score=enhanced_score,
            winner=winner,
            reasoning=reasoning,
            baseline_response=baseline_code,
            enhanced_response=enhanced_code,
        )

    return results


def _judge_pair(
    task: str,
    code_a: str,
    code_b: str,
    rubric_str: str,
    label_a: str,
    label_b: str,
    judge_model: str | None = None,
) -> tuple[int, int, str, str]:
    """Run the LLM-as-judge comparison between two code outputs.

    Returns (score_a, score_b, winner_label, reasoning).
    winner_label is label_a, label_b, or "tie".
    """
    judge_model_name = judge_model or DEFAULT_JUDGE_MODEL
    judge_model_id = get_model_id(judge_model_name)
    judge_lm = dspy.LM(
        judge_model_id,
        api_key=OPENROUTER_API_KEY,
        api_base="https://openrouter.ai/api/v1",
        temperature=EVAL_TEMPERATURE,
    )

    # Randomize order to avoid position bias
    if random.random() < 0.5:
        resp_a, resp_b = code_a, code_b
        first_is_a = True
    else:
        resp_a, resp_b = code_b, code_a
        first_is_a = False

    try:
        with dspy.context(lm=judge_lm):
            judge_predictor = dspy.ChainOfThought(QualityJudge)
            judgment = judge_predictor(
                task=task,
                response_a=resp_a,
                response_b=resp_b,
                rubric=rubric_str,
            )

        score_first = int(judgment.score_a) if judgment.score_a else 3
        score_second = int(judgment.score_b) if judgment.score_b else 3

        if first_is_a:
            score_a, score_b = score_first, score_second
        else:
            score_a, score_b = score_second, score_first

        winner_raw = str(judgment.winner).strip().upper()
        if winner_raw == "TIE":
            winner = "tie"
        elif (winner_raw == "A" and first_is_a) or (winner_raw == "B" and not first_is_a):
            winner = label_a
        else:
            winner = label_b

        reasoning = getattr(judgment, "reasoning", "")

    except Exception as e:
        score_a = 3
        score_b = 3
        winner = "tie"
        reasoning = f"JUDGE ERROR: {e}"

    return score_a, score_b, winner, reasoning


def run_variant_comparison(
    model: str,
    dataset_path: Path,
    skill_name: str,
    variants_dir: Path,
    judge_model: str | None = None,
    skills_repo: Path | None = None,
) -> dict[str, EffectivenessResults]:
    """Compare multiple authoring variants of the same skill.

    Runs each variant against the baseline (no skill) and also compares
    variants head-to-head.

    Args:
        model: Model name for generating responses.
        dataset_path: Path to JSONL dataset file.
        skill_name: The skill to compare variants for.
        variants_dir: Path to the variants directory.
        judge_model: Model name for the judge.
        skills_repo: Path to dotnet-skills repo.

    Returns:
        Dict mapping variant strategy name to its effectiveness results.
    """
    configure_dspy(model)
    subject_predictor = dspy.Predict(DotNetTaskCompletion)

    # Load the original skill
    repo = ensure_skills_repo(skills_repo)
    skills = load_all_skills(repo / "skills")
    skill_map = {s.metadata.name: s for s in skills}
    skill = skill_map.get(skill_name)
    if not skill:
        raise ValueError(f"Skill not found: {skill_name}")

    # Load all variants
    variants = get_all_variants(skill, variants_dir)

    # Load dataset (filtered to this skill)
    cases = load_effectiveness_dataset(dataset_path)
    cases = [c for c in cases if c["skill_name"] == skill_name]

    # Run each variant vs baseline
    all_results: dict[str, EffectivenessResults] = {}

    for strategy, variant in variants.items():
        results = EffectivenessResults()

        for case in cases:
            task = case["task"]
            rubric_str = load_rubric(case["rubric_file"])

            # Baseline (no skill)
            try:
                baseline_pred = subject_predictor(
                    skill_guidance="",
                    task=task,
                )
                baseline_code = baseline_pred.code
            except Exception as e:
                baseline_code = f"ERROR: {e}"

            # Enhanced (with variant content)
            # For progressive: use full_context (all files concatenated)
            # This simulates Claude Code loading the main file + references
            context = variant.full_context
            try:
                enhanced_pred = subject_predictor(
                    skill_guidance=context,
                    task=task,
                )
                enhanced_code = enhanced_pred.code
            except Exception as e:
                enhanced_code = f"ERROR: {e}"

            # Judge
            baseline_score, enhanced_score, winner, reasoning = _judge_pair(
                task=task,
                code_a=baseline_code,
                code_b=enhanced_code,
                rubric_str=rubric_str,
                label_a="baseline",
                label_b="enhanced",
                judge_model=judge_model,
            )

            results.record(
                case_id=f"{case['id']}-{strategy}",
                skill_name=skill_name,
                task=task,
                baseline_score=baseline_score,
                enhanced_score=enhanced_score,
                winner=winner,
                reasoning=reasoning,
                baseline_response=baseline_code,
                enhanced_response=enhanced_code,
            )

        all_results[strategy] = results

    return all_results
