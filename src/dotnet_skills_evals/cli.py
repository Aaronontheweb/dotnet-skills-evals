"""CLI entry point for dotnet-skills evaluation harness."""

from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console

console = Console()


@click.group()
@click.version_option(version="0.1.0")
def cli():
    """dotnet-skills evaluation harness.

    Tests skill activation accuracy, skill effectiveness, and size impact
    for the dotnet-skills Claude Code plugin.
    """


@cli.command()
@click.option(
    "--model",
    type=click.Choice(["haiku", "sonnet", "opus"]),
    default="haiku",
    help="Model to use for evaluation.",
)
@click.option(
    "--with-index/--without-index",
    default=False,
    help="Include the compressed routing index in the prompt.",
)
@click.option(
    "--dataset",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="Path to JSONL dataset file.",
)
@click.option(
    "--skills-repo",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Path to dotnet-skills repository.",
)
@click.option(
    "--output",
    type=click.Path(path_type=Path),
    default=None,
    help="Path to write JSON results file.",
)
def eval_activation(
    model: str,
    with_index: bool,
    dataset: Path,
    skills_repo: Path | None,
    output: Path | None,
):
    """Evaluate skill activation accuracy.

    Tests whether the model correctly selects the right skill(s)
    for given .NET development tasks.
    """
    from .eval_activation.runner import run_activation_eval
    from .reporting.results import print_activation_results, export_results_json

    console.print(f"[bold]Running activation eval[/bold] (model={model}, index={with_index})")
    console.print(f"Dataset: {dataset}")

    results = run_activation_eval(
        model=model,
        dataset_path=dataset,
        with_index=with_index,
        skills_repo=skills_repo,
    )

    print_activation_results(results)

    if output:
        export_results_json(
            activation_results=results,
            effectiveness_results=None,
            output_path=output,
        )


@cli.command()
@click.option(
    "--model",
    type=click.Choice(["haiku", "sonnet", "opus"]),
    default="sonnet",
    help="Model to generate code responses.",
)
@click.option(
    "--judge-model",
    type=click.Choice(["haiku", "sonnet", "opus"]),
    default=None,
    help="Model to judge quality (defaults to sonnet).",
)
@click.option(
    "--skill",
    "skill_filter",
    default=None,
    help="Filter to a specific skill name.",
)
@click.option(
    "--dataset",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="Path to JSONL dataset file.",
)
@click.option(
    "--skills-repo",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Path to dotnet-skills repository.",
)
@click.option(
    "--output",
    type=click.Path(path_type=Path),
    default=None,
    help="Path to write JSON results file.",
)
def eval_effectiveness(
    model: str,
    judge_model: str | None,
    skill_filter: str | None,
    dataset: Path,
    skills_repo: Path | None,
    output: Path | None,
):
    """Evaluate skill effectiveness.

    Compares code quality WITH a skill vs WITHOUT it using an LLM-as-judge.
    """
    from .eval_effectiveness.runner import run_effectiveness_eval
    from .reporting.results import print_effectiveness_results, export_results_json

    console.print(f"[bold]Running effectiveness eval[/bold] (model={model})")
    if skill_filter:
        console.print(f"Filtering to skill: {skill_filter}")
    console.print(f"Dataset: {dataset}")

    results = run_effectiveness_eval(
        model=model,
        dataset_path=dataset,
        skill_filter=skill_filter,
        judge_model=judge_model,
        skills_repo=skills_repo,
    )

    print_effectiveness_results(results)

    if output:
        export_results_json(
            activation_results=None,
            effectiveness_results=results,
            output_path=output,
        )


@cli.command()
@click.option(
    "--model",
    type=click.Choice(["haiku", "sonnet", "opus"]),
    default="sonnet",
    help="Model to generate code responses.",
)
@click.option(
    "--judge-model",
    type=click.Choice(["haiku", "sonnet", "opus"]),
    default=None,
    help="Model to judge quality.",
)
@click.option(
    "--skill",
    "skill_name",
    required=True,
    help="Skill name to test size impact for.",
)
@click.option(
    "--max-lines",
    type=int,
    default=500,
    help="Maximum lines for the truncated variant.",
)
@click.option(
    "--dataset",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="Path to JSONL dataset file.",
)
@click.option(
    "--skills-repo",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Path to dotnet-skills repository.",
)
@click.option(
    "--output",
    type=click.Path(path_type=Path),
    default=None,
    help="Path to write JSON results file.",
)
def eval_size(
    model: str,
    judge_model: str | None,
    skill_name: str,
    max_lines: int,
    dataset: Path,
    skills_repo: Path | None,
    output: Path | None,
):
    """Evaluate size impact on skill effectiveness.

    Runs effectiveness eval twice: once with full skill content,
    once truncated to --max-lines. Compares the results.
    """
    from .eval_effectiveness.runner import run_effectiveness_eval
    from .reporting.results import print_effectiveness_results, export_results_json

    console.print(f"[bold]Running size impact eval[/bold] (model={model}, skill={skill_name})")
    console.print(f"Comparing: full content vs truncated to {max_lines} lines")

    # Full content run
    console.print("\n[bold cyan]--- Full Content ---[/bold cyan]")
    full_results = run_effectiveness_eval(
        model=model,
        dataset_path=dataset,
        skill_filter=skill_name,
        judge_model=judge_model,
        skills_repo=skills_repo,
        truncate_at=None,
    )
    print_effectiveness_results(full_results)

    # Truncated run
    console.print(f"\n[bold cyan]--- Truncated to {max_lines} lines ---[/bold cyan]")
    truncated_results = run_effectiveness_eval(
        model=model,
        dataset_path=dataset,
        skill_filter=skill_name,
        judge_model=judge_model,
        skills_repo=skills_repo,
        truncate_at=max_lines,
    )
    print_effectiveness_results(truncated_results)

    # Comparison
    console.print("\n[bold]Size Impact Comparison[/bold]")
    from rich.table import Table

    comparison = Table()
    comparison.add_column("Metric", style="cyan")
    comparison.add_column("Full", style="green")
    comparison.add_column(f"Truncated ({max_lines})", style="yellow")
    comparison.add_column("Difference", style="bold")

    for label, full_val, trunc_val in [
        ("Win Rate", full_results.win_rate, truncated_results.win_rate),
        ("Mean Enhanced Score", full_results.mean_enhanced_score, truncated_results.mean_enhanced_score),
        ("Mean Improvement", full_results.mean_improvement, truncated_results.mean_improvement),
    ]:
        diff = full_val - trunc_val
        diff_str = f"{diff:+.2f}"
        if diff > 0:
            diff_str = f"[green]{diff_str} (full better)[/green]"
        elif diff < 0:
            diff_str = f"[red]{diff_str} (truncated better)[/red]"
        else:
            diff_str = "0.00 (same)"

        comparison.add_row(
            label,
            f"{full_val:.2f}",
            f"{trunc_val:.2f}",
            diff_str,
        )

    console.print(comparison)

    if output:
        export_results_json(
            activation_results=None,
            effectiveness_results=full_results,
            output_path=output,
        )


@cli.command()
def list_skills():
    """List all skills from the dotnet-skills repository with sizes."""
    from .config import DEFAULT_SKILLS_REPO
    from .skills.loader import load_all_skills

    skills = load_all_skills(DEFAULT_SKILLS_REPO / "skills")

    from rich.table import Table

    table = Table(title="dotnet-skills Catalog")
    table.add_column("Name", style="cyan")
    table.add_column("Directory", style="dim")
    table.add_column("Lines", style="yellow", justify="right")
    table.add_column("Size", style="dim", justify="right")
    table.add_column("Over 500?", style="bold")

    for s in skills:
        over = "[red]Yes[/red]" if s.is_oversized else "[green]No[/green]"
        size_kb = f"{s.metadata.byte_size / 1024:.1f}KB"
        table.add_row(
            s.metadata.name,
            s.metadata.directory_name,
            str(s.metadata.line_count),
            size_kb,
            over,
        )

    console.print(table)


@cli.command()
@click.option(
    "--model",
    type=click.Choice(["haiku", "sonnet", "opus"]),
    default="sonnet",
    help="Model to generate code responses.",
)
@click.option(
    "--judge-model",
    type=click.Choice(["haiku", "sonnet", "opus"]),
    default=None,
    help="Model to judge quality.",
)
@click.option(
    "--skill",
    "skill_name",
    required=True,
    help="Skill name to compare variants for.",
)
@click.option(
    "--dataset",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="Path to JSONL dataset file.",
)
@click.option(
    "--variants-dir",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Path to variants directory (defaults to datasets/variants/).",
)
@click.option(
    "--skills-repo",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Path to dotnet-skills repository.",
)
@click.option(
    "--output",
    type=click.Path(path_type=Path),
    default=None,
    help="Path to write JSON results file.",
)
def eval_variants(
    model: str,
    judge_model: str | None,
    skill_name: str,
    dataset: Path,
    variants_dir: Path | None,
    skills_repo: Path | None,
    output: Path | None,
):
    """Compare authoring strategies for a skill.

    Tests original vs condensed vs progressive disclosure variants
    of the same skill to determine which authoring approach produces
    the best results.
    """
    from .eval_effectiveness.runner import run_variant_comparison
    from .reporting.results import print_effectiveness_results

    default_variants = Path(__file__).parent.parent.parent / "datasets" / "variants"
    vdir = variants_dir or default_variants

    console.print(f"[bold]Running variant comparison[/bold] (model={model}, skill={skill_name})")

    results_by_strategy = run_variant_comparison(
        model=model,
        dataset_path=dataset,
        skill_name=skill_name,
        variants_dir=vdir,
        judge_model=judge_model,
        skills_repo=skills_repo,
    )

    # Print results for each variant
    for strategy, results in sorted(results_by_strategy.items()):
        console.print(f"\n[bold cyan]--- Strategy: {strategy} ---[/bold cyan]")
        print_effectiveness_results(results)

    # Comparison table
    console.print("\n[bold]Variant Comparison Summary[/bold]")
    from rich.table import Table

    comparison = Table()
    comparison.add_column("Strategy", style="cyan")
    comparison.add_column("Win Rate", style="green")
    comparison.add_column("Mean Enhanced", style="yellow")
    comparison.add_column("Mean Improvement", style="bold")

    for strategy, results in sorted(results_by_strategy.items()):
        comparison.add_row(
            strategy,
            f"{results.win_rate:.1%}",
            f"{results.mean_enhanced_score:.2f}",
            f"{results.mean_improvement:+.2f}",
        )

    console.print(comparison)

    if output:
        import json
        output.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        for strategy, results in results_by_strategy.items():
            data[strategy] = {
                "win_rate": results.win_rate,
                "mean_enhanced_score": results.mean_enhanced_score,
                "mean_improvement": results.mean_improvement,
                "cases": [
                    {
                        "id": r.case_id,
                        "baseline_score": r.baseline_score,
                        "enhanced_score": r.enhanced_score,
                        "winner": r.winner,
                        "reasoning": r.reasoning,
                    }
                    for r in results.results
                ],
            }
        with open(output, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        console.print(f"\nResults exported to [bold]{output}[/bold]")


@cli.command()
@click.option(
    "--skill",
    "skill_names",
    multiple=True,
    help="Skill name(s) to scaffold variants for. Omit for all Akka skills.",
)
@click.option(
    "--variants-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Path to variants directory (defaults to datasets/variants/).",
)
def scaffold_variants(
    skill_names: tuple[str, ...],
    variants_dir: Path | None,
):
    """Create directory structure for skill variant authoring.

    Creates condensed/ and progressive/ subdirectories with placeholder
    SKILL.md files for you to fill in.
    """
    from .skills.variants import scaffold_variant_dirs
    from .config import DEFAULT_SKILLS_REPO
    from .skills.loader import load_all_skills, filter_skills_by_prefix

    default_variants = Path(__file__).parent.parent.parent / "datasets" / "variants"
    vdir = variants_dir or default_variants

    if not skill_names:
        # Default to Akka skills
        skills = load_all_skills(DEFAULT_SKILLS_REPO / "skills")
        akka_skills = filter_skills_by_prefix(skills, "akka")
        names = [s.metadata.name for s in akka_skills]
    else:
        names = list(skill_names)

    scaffold_variant_dirs(vdir, names)
    console.print(f"[green]Scaffolded variant directories for {len(names)} skills in {vdir}[/green]")
    for name in names:
        console.print(f"  - {vdir / name}/condensed/SKILL.md")
        console.print(f"  - {vdir / name}/progressive/SKILL.md")
        console.print(f"  - {vdir / name}/progressive/reference.md")
        console.print(f"  - {vdir / name}/progressive/examples.md")
