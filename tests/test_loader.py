"""Tests for skill loader and catalog builder."""

from pathlib import Path

import pytest

from dotnet_skills_evals.skills.loader import (
    load_skill,
    load_all_skills,
    load_skills_from_plugin_json,
    build_name_to_directory_map,
    filter_skills_by_prefix,
)
from dotnet_skills_evals.skills.catalog import (
    build_skill_catalog,
    build_compressed_index,
)
from dotnet_skills_evals.config import DEFAULT_SKILLS_REPO, PLUGIN_JSON


SKILLS_DIR = DEFAULT_SKILLS_REPO / "skills"


@pytest.fixture
def all_skills():
    """Load all skills from the dotnet-skills repo."""
    return load_all_skills(SKILLS_DIR)


class TestSkillLoader:
    def test_load_single_skill(self):
        """Can load a specific skill directory."""
        skill = load_skill(SKILLS_DIR / "akka-best-practices")
        assert skill.metadata.name == "akka-net-best-practices"
        assert "best practices" in skill.metadata.description.lower()
        assert skill.metadata.directory_name == "akka-best-practices"
        assert skill.metadata.line_count > 0
        assert len(skill.full_content) > 0

    def test_load_all_skills(self, all_skills):
        """Can load all skills from the repository."""
        assert len(all_skills) >= 30  # Should have ~31 skills
        names = [s.metadata.name for s in all_skills]
        assert "akka-net-best-practices" in names
        assert "modern-csharp-coding-standards" in names

    def test_load_from_plugin_json(self):
        """Skills loaded from plugin.json match expected count."""
        if not PLUGIN_JSON.exists():
            pytest.skip("plugin.json not found")
        skills = load_skills_from_plugin_json(PLUGIN_JSON)
        assert len(skills) >= 30

    def test_name_directory_mismatch(self, all_skills):
        """Verify that name != directory_name for known cases."""
        name_map = build_name_to_directory_map(all_skills)
        # akka-best-practices dir has name akka-net-best-practices
        assert name_map["akka-net-best-practices"] == "akka-best-practices"

    def test_filter_by_prefix(self, all_skills):
        """Can filter skills by frontmatter name prefix."""
        akka_skills = filter_skills_by_prefix(all_skills, "akka")
        assert len(akka_skills) >= 4
        for s in akka_skills:
            assert s.metadata.name.startswith("akka")

    def test_oversized_detection(self):
        """Detects oversized skills (>500 lines)."""
        skill = load_skill(SKILLS_DIR / "akka-best-practices")
        assert skill.is_oversized  # 1123 lines

    def test_truncation(self):
        """Can truncate skill content to N lines."""
        skill = load_skill(SKILLS_DIR / "akka-best-practices")
        truncated = skill.truncated_content(100)
        assert len(truncated.splitlines()) <= 100
        assert len(truncated) < len(skill.full_content)

    def test_truncation_noop_for_small_skills(self):
        """Truncation is a no-op if skill is smaller than the limit."""
        skill = load_skill(SKILLS_DIR / "akka-best-practices")
        full = skill.truncated_content(99999)
        assert full == skill.full_content

    def test_missing_skill_raises(self):
        """Loading a nonexistent skill raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            load_skill(SKILLS_DIR / "nonexistent-skill")


class TestCatalogBuilder:
    def test_build_catalog(self, all_skills):
        """Builds a catalog string with all skill names and descriptions."""
        catalog = build_skill_catalog(all_skills)
        assert "# Available Skills" in catalog
        assert "akka-net-best-practices" in catalog
        assert "modern-csharp-coding-standards" in catalog
        # Each skill should have name and description
        for skill in all_skills:
            assert skill.metadata.name in catalog

    def test_build_compressed_index(self):
        """Can extract compressed index from README.md."""
        readme = DEFAULT_SKILLS_REPO / "README.md"
        if not readme.exists():
            pytest.skip("README.md not found")
        index = build_compressed_index(readme)
        assert len(index) > 0
        assert "dotnet-skills" in index
        assert "akka" in index
