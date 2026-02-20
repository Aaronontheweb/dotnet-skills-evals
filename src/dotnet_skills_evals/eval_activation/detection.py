"""Detect skill references in free-text model responses."""

from __future__ import annotations


def detect_skill_references(
    response: str,
    known_skills: list[str],
) -> list[str]:
    """Find exact skill name matches in a response string.

    Skill names like 'akka-net-best-practices' are distinctive hyphenated
    identifiers that don't appear naturally in prose, so simple substring
    matching is reliable.

    Args:
        response: The model's full response text.
        known_skills: List of all known skill names to search for.

    Returns:
        List of matched skill names (preserving original casing), in the
        order they appear in known_skills.
    """
    response_lower = response.lower()
    found = []
    for skill_name in known_skills:
        if skill_name.lower() in response_lower:
            found.append(skill_name)
    return found
