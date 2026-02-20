"""DSPy signatures for skill effectiveness evaluation."""

import dspy


class DotNetTaskCompletion(dspy.Signature):
    """Complete a .NET development task. If skill guidance is provided,
    follow its patterns and recommendations closely."""

    skill_guidance: str = dspy.InputField(
        desc="Domain-specific skill guidance for this task. "
        "May be empty (baseline) or contain full skill content (enhanced)."
    )
    task: str = dspy.InputField(
        desc="The .NET development task to complete"
    )
    code: str = dspy.OutputField(
        desc="The generated code solution"
    )


class QualityJudge(dspy.Signature):
    """You are an expert .NET code reviewer. Compare two code responses to the
    same task and judge which one is better according to the rubric.

    Response A and Response B are presented in random order - judge purely on
    quality, not position. Be specific about what makes one better."""

    task: str = dspy.InputField(
        desc="The original .NET development task"
    )
    response_a: str = dspy.InputField(
        desc="First code response"
    )
    response_b: str = dspy.InputField(
        desc="Second code response"
    )
    rubric: str = dspy.InputField(
        desc="Evaluation criteria with weighted scoring dimensions"
    )
    winner: str = dspy.OutputField(
        desc="Which response is better: 'A', 'B', or 'tie'"
    )
    score_a: int = dspy.OutputField(
        desc="Score for response A on a scale of 1-5"
    )
    score_b: int = dspy.OutputField(
        desc="Score for response B on a scale of 1-5"
    )
    reasoning: str = dspy.OutputField(
        desc="Detailed explanation of the judgment, referencing specific rubric criteria"
    )
