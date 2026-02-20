"""Build skill catalogs that simulate how Claude Code presents skills at startup."""

from __future__ import annotations

from pathlib import Path

from .loader import Skill


def build_skill_catalog(skills: list[Skill]) -> str:
    """Format all skill names + descriptions as Claude Code would inject at startup.

    Claude Code loads skill name and description into the system prompt at startup.
    The model uses these to decide which skill to activate for a given task.

    Args:
        skills: All available skills.

    Returns:
        Formatted catalog string with one skill per line.
    """
    lines = ["# Available Skills", ""]
    for skill in skills:
        lines.append(
            f"- **{skill.metadata.name}**: {skill.metadata.description}"
        )
    return "\n".join(lines)


def build_compressed_index(index_skill_path: Path) -> str:
    """Load the compressed Vercel-style routing index.

    The compressed index is maintained in skills-index-snippets/SKILL.md
    and also rendered in the README.md between marker comments.

    Args:
        index_skill_path: Path to skills-index-snippets/SKILL.md or README.md.

    Returns:
        The compressed index block as a string.
    """
    content = index_skill_path.read_text(encoding="utf-8")

    # Try to extract from README marker comments
    start_marker = "<!-- BEGIN DOTNET-SKILLS COMPRESSED INDEX -->"
    end_marker = "<!-- END DOTNET-SKILLS COMPRESSED INDEX -->"

    if start_marker in content:
        start = content.index(start_marker) + len(start_marker)
        end = content.index(end_marker)
        block = content[start:end].strip()
        # Strip markdown code fence if present
        if block.startswith("```"):
            lines = block.splitlines()
            # Remove first (```markdown) and last (```) lines
            lines = [l for l in lines if not l.strip().startswith("```")]
            block = "\n".join(lines)
        return block

    # If reading the SKILL.md directly, find the compressed snippet section
    if "## Compressed Snippet Template" in content:
        # Extract the code block after the compressed snippet header
        sections = content.split("## Compressed Snippet Template")
        if len(sections) > 1:
            rest = sections[1]
            # Find the code block
            if "```" in rest:
                blocks = rest.split("```")
                if len(blocks) >= 3:
                    return blocks[1].strip().removeprefix("markdown").strip()

    return ""


def build_skill_context_for_eval(
    skill: Skill, truncate_at: int | None = None
) -> str:
    """Build the full context string for a skill, as it would appear when activated.

    Args:
        skill: The skill to build context for.
        truncate_at: If set, truncate the skill body to this many lines.

    Returns:
        The skill content that would be injected when the skill is activated.
    """
    if truncate_at is not None:
        return skill.truncated_content(truncate_at)
    return skill.full_content
