"""Skill variant management for A/B testing different authoring strategies.

Supports three authoring strategies:
1. "original" - The full, unmodified SKILL.md from the dotnet-skills repo
2. "condensed" - A manually trimmed single-file version (~500 lines)
3. "progressive" - Split into core SKILL.md + reference files (simulates
   Claude Code's progressive disclosure pattern)

Variants are stored in datasets/variants/<skill-name>/<strategy>/
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .loader import Skill, load_skill


VARIANT_STRATEGIES = ("original", "condensed", "progressive")


@dataclass
class SkillVariant:
    """A specific authoring variant of a skill."""

    skill_name: str
    strategy: str  # "original", "condensed", or "progressive"
    main_content: str  # The primary SKILL.md content
    reference_files: dict[str, str]  # filename -> content (for progressive)

    @property
    def full_context(self) -> str:
        """All content concatenated - what the LLM would see if everything
        is loaded."""
        parts = [self.main_content]
        for filename, content in sorted(self.reference_files.items()):
            parts.append(f"\n\n---\n\n# Reference: {filename}\n\n{content}")
        return "\n".join(parts)

    @property
    def main_only_context(self) -> str:
        """Just the main SKILL.md - what a platform like Copilot would see."""
        return self.main_content

    @property
    def has_references(self) -> bool:
        return bool(self.reference_files)


def load_variant(
    variants_dir: Path, skill_name: str, strategy: str
) -> SkillVariant | None:
    """Load a skill variant from the variants directory.

    Directory structure:
        variants_dir/<skill-name>/condensed/SKILL.md
        variants_dir/<skill-name>/progressive/SKILL.md
        variants_dir/<skill-name>/progressive/reference.md
        variants_dir/<skill-name>/progressive/examples.md

    The "original" strategy loads directly from the dotnet-skills repo
    and does not use the variants directory.
    """
    if strategy not in VARIANT_STRATEGIES:
        raise ValueError(f"Unknown strategy: {strategy}. Must be one of {VARIANT_STRATEGIES}")

    variant_dir = variants_dir / skill_name / strategy
    skill_file = variant_dir / "SKILL.md"

    if not skill_file.exists():
        return None

    main_content = skill_file.read_text(encoding="utf-8")

    # Load reference files (for progressive disclosure)
    reference_files: dict[str, str] = {}
    for ref_file in sorted(variant_dir.iterdir()):
        if ref_file.name != "SKILL.md" and ref_file.suffix == ".md":
            reference_files[ref_file.name] = ref_file.read_text(encoding="utf-8")

    return SkillVariant(
        skill_name=skill_name,
        strategy=strategy,
        main_content=main_content,
        reference_files=reference_files,
    )


def load_original_variant(skill: Skill) -> SkillVariant:
    """Create a variant from the original skill (no modifications)."""
    return SkillVariant(
        skill_name=skill.metadata.name,
        strategy="original",
        main_content=skill.full_content,
        reference_files={},
    )


def get_all_variants(
    skill: Skill, variants_dir: Path
) -> dict[str, SkillVariant]:
    """Load all available variants for a skill.

    Always includes "original". Also includes "condensed" and "progressive"
    if they exist in the variants directory.
    """
    variants: dict[str, SkillVariant] = {
        "original": load_original_variant(skill),
    }

    for strategy in ("condensed", "progressive"):
        variant = load_variant(variants_dir, skill.metadata.name, strategy)
        if variant is not None:
            variants[strategy] = variant

    return variants


def scaffold_variant_dirs(variants_dir: Path, skill_names: list[str]) -> None:
    """Create the directory structure for skill variants.

    Call this to set up the skeleton for manually authoring condensed
    and progressive variants.
    """
    for skill_name in skill_names:
        for strategy in ("condensed", "progressive"):
            dir_path = variants_dir / skill_name / strategy
            dir_path.mkdir(parents=True, exist_ok=True)

            skill_file = dir_path / "SKILL.md"
            if not skill_file.exists():
                skill_file.write_text(
                    f"---\nname: {skill_name}\n"
                    f"description: TODO - {strategy} variant\n"
                    f"invocable: false\n---\n\n"
                    f"# {skill_name} ({strategy} variant)\n\n"
                    f"TODO: Author this variant.\n",
                    encoding="utf-8",
                )

            if strategy == "progressive":
                for ref_name in ("reference.md", "examples.md"):
                    ref_file = dir_path / ref_name
                    if not ref_file.exists():
                        ref_file.write_text(
                            f"# {ref_name.replace('.md', '').title()}\n\n"
                            f"TODO: Move detailed content here from SKILL.md.\n",
                            encoding="utf-8",
                        )
