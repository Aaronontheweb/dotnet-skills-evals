"""DSPy signatures for skill activation evaluation."""

import dspy


class SkillActivation(dspy.Signature):
    """You are a .NET development assistant with access to specialized skills.
    Given a user's development task, determine which skill(s) from the available
    catalog should be activated to best assist with the task.

    Select only skills that are directly relevant. Return skill names exactly as
    they appear in the catalog. If no skill is relevant, return an empty list."""

    available_skills: str = dspy.InputField(
        desc="Catalog of available skills with names and descriptions"
    )
    user_task: str = dspy.InputField(
        desc="The user's .NET development task or question"
    )
    selected_skills: list[str] = dspy.OutputField(
        desc="List of skill name(s) to activate, ordered by relevance. "
        "Use exact names from the catalog."
    )
    reasoning: str = dspy.OutputField(
        desc="Brief explanation of why these skills were selected"
    )


class SkillActivationWithIndex(dspy.Signature):
    """You are a .NET development assistant with access to specialized skills.
    You have both a skill catalog and a compressed routing index to help
    select the right skill(s) for the user's task.

    Select only skills that are directly relevant. Return skill names exactly as
    they appear in the catalog. If no skill is relevant, return an empty list."""

    available_skills: str = dspy.InputField(
        desc="Catalog of available skills with names and descriptions"
    )
    compressed_index: str = dspy.InputField(
        desc="Compressed routing index that maps task categories to skill names"
    )
    user_task: str = dspy.InputField(
        desc="The user's .NET development task or question"
    )
    selected_skills: list[str] = dspy.OutputField(
        desc="List of skill name(s) to activate, ordered by relevance. "
        "Use exact names from the catalog."
    )
    reasoning: str = dspy.OutputField(
        desc="Brief explanation of why these skills were selected"
    )
