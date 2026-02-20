"""Reporting utilities for evaluation results."""

from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console
from rich.table import Table

from ..eval_activation.metrics import ActivationResults
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
