"""Reporting utilities for evaluation results."""

from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console
from rich.table import Table

from ..eval_activation_quiz.metrics import ActivationResults
from ..eval_activation.metrics import ActivationResults as ActivationV2Results
from ..eval_effectiveness.metrics import EffectivenessResults


console = Console()


def print_activation_results(results: ActivationResults) -> None:
    """Print activation evaluation results to console."""
    console.print("\n[bold]Skill Activation Evaluation Results[/bold]\n")

    # Summary table
    summary = Table(title="Summary")
    summary.add_column("Metric", style="cyan")
    summary.add_column("Value", style="green")

    summary.add_row("Total Cases", str(results.total_cases))
    summary.add_row("Exact Matches", str(results.exact_matches))
    summary.add_row("Acceptable Matches", str(results.acceptable_matches))
    summary.add_row("Misses", str(results.misses))
    summary.add_row("Accuracy (weighted)", f"{results.accuracy:.1%}")
    summary.add_row("Exact Accuracy", f"{results.exact_accuracy:.1%}")
    summary.add_row("Mean Precision@1", f"{results.mean_precision_at_1:.1%}")
    summary.add_row("Mean Recall", f"{results.mean_recall:.1%}")
    console.print(summary)

    # Confusion matrix (top confusions)
    confusions = results.top_confusions(10)
    if confusions:
        console.print("\n[bold]Top Confusion Pairs[/bold]")
        confusion_table = Table()
        confusion_table.add_column("Expected", style="cyan")
        confusion_table.add_column("Predicted Instead", style="red")
        confusion_table.add_column("Count", style="yellow")

        for expected, predicted, count in confusions:
            confusion_table.add_row(expected, predicted, str(count))
        console.print(confusion_table)

    # Per-case details
    console.print("\n[bold]Per-Case Results[/bold]")
    detail_table = Table()
    detail_table.add_column("ID", style="dim")
    detail_table.add_column("Accuracy", style="green")
    detail_table.add_column("Expected", style="cyan")
    detail_table.add_column("Predicted", style="yellow")

    for case in results.per_case_results:
        acc = case["accuracy"]
        acc_str = (
            "[green]1.0[/green]"
            if acc == 1.0
            else "[yellow]0.5[/yellow]"
            if acc == 0.5
            else "[red]0.0[/red]"
        )
        detail_table.add_row(
            case["id"],
            acc_str,
            ", ".join(case["expected"]),
            ", ".join(case["predicted"]) or "(none)",
        )
    console.print(detail_table)


def print_effectiveness_results(results: EffectivenessResults) -> None:
    """Print effectiveness evaluation results to console."""
    console.print("\n[bold]Skill Effectiveness Evaluation Results[/bold]\n")

    # Summary
    summary = Table(title="Summary")
    summary.add_column("Metric", style="cyan")
    summary.add_column("Value", style="green")

    summary.add_row("Total Cases", str(results.total_cases))
    summary.add_row("Skill Wins", str(results.skill_wins))
    summary.add_row("Baseline Wins", str(results.baseline_wins))
    summary.add_row("Ties", str(results.ties))
    summary.add_row("Win Rate", f"{results.win_rate:.1%}")
    summary.add_row("Mean Baseline Score", f"{results.mean_baseline_score:.2f}")
    summary.add_row("Mean Enhanced Score", f"{results.mean_enhanced_score:.2f}")
    summary.add_row("Mean Improvement", f"{results.mean_improvement:+.2f}")
    console.print(summary)

    # Per-skill breakdown
    by_skill = results.results_by_skill()
    if len(by_skill) > 1:
        console.print("\n[bold]Per-Skill Breakdown[/bold]")
        skill_table = Table()
        skill_table.add_column("Skill", style="cyan")
        skill_table.add_column("Cases", style="dim")
        skill_table.add_column("Win Rate", style="green")
        skill_table.add_column("Mean Improvement", style="yellow")

        for skill_name, skill_results in sorted(by_skill.items()):
            n = len(skill_results)
            wins = sum(1 for r in skill_results if r.skill_helped)
            mean_imp = sum(r.improvement for r in skill_results) / n
            skill_table.add_row(
                skill_name,
                str(n),
                f"{wins/n:.1%}",
                f"{mean_imp:+.2f}",
            )
        console.print(skill_table)

    # Per-case details
    console.print("\n[bold]Per-Case Results[/bold]")
    detail_table = Table()
    detail_table.add_column("ID", style="dim")
    detail_table.add_column("Skill", style="cyan")
    detail_table.add_column("Baseline", style="yellow")
    detail_table.add_column("Enhanced", style="green")
    detail_table.add_column("Delta", style="bold")
    detail_table.add_column("Winner", style="bold")

    for r in results.results:
        delta_str = f"{r.improvement:+d}"
        if r.improvement > 0:
            delta_str = f"[green]{delta_str}[/green]"
        elif r.improvement < 0:
            delta_str = f"[red]{delta_str}[/red]"

        winner_str = (
            "[green]enhanced[/green]"
            if r.winner == "enhanced"
            else "[red]baseline[/red]"
            if r.winner == "baseline"
            else "tie"
        )

        detail_table.add_row(
            r.case_id,
            r.skill_name,
            str(r.baseline_score),
            str(r.enhanced_score),
            delta_str,
            winner_str,
        )
    console.print(detail_table)


def export_results_json(
    activation_results: ActivationResults | None,
    effectiveness_results: EffectivenessResults | None,
    output_path: Path,
) -> None:
    """Export results to a JSON file."""
    data: dict = {}

    if activation_results:
        data["activation"] = {
            "summary": {
                "total_cases": activation_results.total_cases,
                "exact_matches": activation_results.exact_matches,
                "acceptable_matches": activation_results.acceptable_matches,
                "misses": activation_results.misses,
                "accuracy": activation_results.accuracy,
                "exact_accuracy": activation_results.exact_accuracy,
                "mean_precision_at_1": activation_results.mean_precision_at_1,
                "mean_recall": activation_results.mean_recall,
            },
            "confusions": [
                {"expected": e, "predicted": p, "count": c}
                for e, p, c in activation_results.top_confusions(20)
            ],
            "cases": activation_results.per_case_results,
        }

    if effectiveness_results:
        data["effectiveness"] = {
            "summary": {
                "total_cases": effectiveness_results.total_cases,
                "skill_wins": effectiveness_results.skill_wins,
                "baseline_wins": effectiveness_results.baseline_wins,
                "ties": effectiveness_results.ties,
                "win_rate": effectiveness_results.win_rate,
                "mean_baseline_score": effectiveness_results.mean_baseline_score,
                "mean_enhanced_score": effectiveness_results.mean_enhanced_score,
                "mean_improvement": effectiveness_results.mean_improvement,
            },
            "cases": [
                {
                    "id": r.case_id,
                    "skill": r.skill_name,
                    "task": r.task,
                    "baseline_score": r.baseline_score,
                    "enhanced_score": r.enhanced_score,
                    "improvement": r.improvement,
                    "winner": r.winner,
                    "reasoning": r.reasoning,
                }
                for r in effectiveness_results.results
            ],
        }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    console.print(f"\nResults exported to [bold]{output_path}[/bold]")


# --- V2 Activation Reporting (realistic eval) ---


def print_activation_v2_results(
    results_by_mechanism: dict[str, ActivationV2Results],
) -> None:
    """Print realistic activation eval results with mechanism comparison."""
    console.print("\n[bold]Skill Activation Evaluation Results[/bold]\n")

    # Mechanism comparison table
    comparison = Table(title="Mechanism Comparison")
    comparison.add_column("Metric", style="cyan")
    for mech_name in results_by_mechanism:
        comparison.add_column(mech_name, style="green")

    metrics = [
        ("Total Cases", lambda r: str(r.total_cases)),
        ("Activation Rate", lambda r: f"{r.activation_rate:.1%}"),
        ("True Positive Rate", lambda r: f"{r.true_positive_rate:.1%}"),
        ("False Positive Rate", lambda r: f"{r.false_positive_rate:.1%}"),
        ("Accuracy (when activated)", lambda r: f"{r.accuracy_when_activated:.1%}"),
        ("Mean Prompt Tokens", lambda r: f"{r.mean_prompt_tokens:,.0f}"),
        ("Mean Completion Tokens", lambda r: f"{r.mean_completion_tokens:,.0f}"),
        ("Mean Total Tokens", lambda r: f"{r.mean_total_tokens:,.0f}"),
    ]

    for label, fn in metrics:
        row = [label]
        for results in results_by_mechanism.values():
            row.append(fn(results))
        comparison.add_row(*row)

    console.print(comparison)

    # Per-case detail for each mechanism
    for mech_name, results in results_by_mechanism.items():
        console.print(f"\n[bold]Per-Case: {mech_name}[/bold]")
        detail = Table()
        detail.add_column("ID", style="dim")
        detail.add_column("Should Act?", style="dim")
        detail.add_column("Activated?", style="bold")
        detail.add_column("Skills", style="cyan")
        detail.add_column("Accuracy", style="green")
        detail.add_column("Tokens", style="yellow", justify="right")

        for r in results.results:
            should = "[green]yes[/green]" if r.should_activate else "[dim]no[/dim]"
            activated = (
                "[green]yes[/green]" if r.activated else "[dim]no[/dim]"
            )
            # Color accuracy
            if r.accuracy == 1.0:
                acc_str = "[green]1.0[/green]"
            elif r.accuracy == 0.5:
                acc_str = "[yellow]0.5[/yellow]"
            else:
                acc_str = "[red]0.0[/red]" if r.should_activate else "[dim]—[/dim]"

            detail.add_row(
                r.case_id,
                should,
                activated,
                ", ".join(r.activated_skills) or "—",
                acc_str,
                f"{r.total_tokens:,}",
            )

        console.print(detail)


def export_activation_v2_json(
    results_by_mechanism: dict[str, ActivationV2Results],
    output_path: Path,
) -> None:
    """Export v2 activation results to JSON."""
    data = {}

    for mech_name, results in results_by_mechanism.items():
        data[mech_name] = {
            "summary": {
                "total_cases": results.total_cases,
                "positive_cases": results.positive_cases,
                "negative_cases": results.negative_cases,
                "activation_rate": results.activation_rate,
                "true_positive_rate": results.true_positive_rate,
                "false_positive_rate": results.false_positive_rate,
                "accuracy_when_activated": results.accuracy_when_activated,
                "total_prompt_tokens": results.total_prompt_tokens,
                "total_completion_tokens": results.total_completion_tokens,
                "mean_prompt_tokens": results.mean_prompt_tokens,
                "mean_completion_tokens": results.mean_completion_tokens,
                "mean_total_tokens": results.mean_total_tokens,
            },
            "cases": [
                {
                    "id": r.case_id,
                    "should_activate": r.should_activate,
                    "activated": r.activated,
                    "activated_skills": r.activated_skills,
                    "expected_skills": r.expected_skills,
                    "accuracy": r.accuracy,
                    "prompt_tokens": r.prompt_tokens,
                    "completion_tokens": r.completion_tokens,
                    "total_tokens": r.total_tokens,
                }
                for r in results.results
            ],
        }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    console.print(f"\nResults exported to [bold]{output_path}[/bold]")
