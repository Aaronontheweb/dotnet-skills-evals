"""Parse SKILL.md files from the dotnet-skills repository."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import frontmatter


@dataclass
class SkillMetadata:
    """Parsed YAML frontmatter from a SKILL.md file."""

    name: str
    description: str
    invocable: bool
    directory_name: str
    file_path: Path
    line_count: int
    byte_size: int


@dataclass
class Skill:
    """A fully loaded skill with metadata and content."""

    metadata: SkillMetadata
    full_content: str  # Entire SKILL.md body (after frontmatter)

    def truncated_content(self, max_lines: int = 500) -> str:
        """Return the first max_lines of the skill body."""
        lines = self.full_content.splitlines(keepends=True)
        if len(lines) <= max_lines:
            return self.full_content
        return "".join(lines[:max_lines])

    @property
    def is_oversized(self) -> bool:
        """Whether this skill exceeds the recommended 500-line limit."""
        return self.metadata.line_count > 500


def load_skill(skill_dir: Path) -> Skill:
    """Load a single skill from its directory.

    Args:
        skill_dir: Path to a skill directory containing SKILL.md.

    Returns:
        Parsed Skill object.

    Raises:
        FileNotFoundError: If SKILL.md does not exist in the directory.
        ValueError: If required frontmatter fields are missing.
    """
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.exists():
        raise FileNotFoundError(f"No SKILL.md found in {skill_dir}")

    raw = skill_file.read_text(encoding="utf-8")
    post = frontmatter.loads(raw)

    name = post.metadata.get("name")
    description = post.metadata.get("description")
    if not name or not description:
        raise ValueError(
            f"SKILL.md in {skill_dir} missing required frontmatter fields "
            f"(name={name!r}, description={description!r})"
        )

    content = post.content
    line_count = len(raw.splitlines())
    byte_size = len(raw.encode("utf-8"))

    metadata = SkillMetadata(
        name=name,
        description=description,
        invocable=post.metadata.get("invocable", False),
        directory_name=skill_dir.name,
        file_path=skill_file,
        line_count=line_count,
        byte_size=byte_size,
    )

    return Skill(metadata=metadata, full_content=content)


def load_all_skills(skills_dir: Path) -> list[Skill]:
    """Load all skills from the skills directory.

    Args:
        skills_dir: Path to the skills/ directory in the dotnet-skills repo.

    Returns:
        List of all parsed skills, sorted by name.
    """
    skills = []
    for child in sorted(skills_dir.iterdir()):
        if child.is_dir() and (child / "SKILL.md").exists():
            skills.append(load_skill(child))
    return sorted(skills, key=lambda s: s.metadata.name)


def load_skills_from_plugin_json(plugin_json: Path) -> list[Skill]:
    """Load skills listed in plugin.json (the authoritative registry).

    Args:
        plugin_json: Path to .claude-plugin/plugin.json.

    Returns:
        List of skills in the order listed in plugin.json.
    """
    with open(plugin_json, encoding="utf-8") as f:
        manifest = json.load(f)

    repo_root = plugin_json.parent.parent
    skills = []
    for skill_path in manifest.get("skills", []):
        # skill_path is like "./skills/akka-best-practices"
        skill_dir = repo_root / skill_path.lstrip("./")
        skills.append(load_skill(skill_dir))
    return skills


def build_name_to_directory_map(skills: list[Skill]) -> dict[str, str]:
    """Build a mapping from frontmatter name to directory name.

    This is needed because they often differ, e.g.:
    - directory: akka-best-practices
    - frontmatter name: akka-net-best-practices
    """
    return {s.metadata.name: s.metadata.directory_name for s in skills}


def filter_skills_by_prefix(skills: list[Skill], prefix: str) -> list[Skill]:
    """Filter skills whose frontmatter name starts with a given prefix."""
    return [s for s in skills if s.metadata.name.startswith(prefix)]
