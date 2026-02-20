"""Metrics for realistic skill activation evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ActivationResult:
    """Result from a single test case on a single mechanism."""

    case_id: str
    mechanism: str
    should_activate: bool
    activated: bool
    activated_skills: list[str]
    expected_skills: list[str]
    acceptable_skills: list[str]
    accuracy: float  # 1.0 exact, 0.5 acceptable, 0.0 miss/wrong
    response_text: str
    prompt_tokens: int
    completion_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def true_positive(self) -> bool:
        """Activated when it should have."""
        return self.should_activate and self.activated

    @property
    def false_positive(self) -> bool:
        """Activated when it should NOT have."""
        return not self.should_activate and self.activated

    @property
    def true_negative(self) -> bool:
        """Did not activate when it should NOT have."""
        return not self.should_activate and not self.activated

    @property
    def false_negative(self) -> bool:
        """Did not activate when it should have."""
        return self.should_activate and not self.activated


def compute_accuracy(
    activated_skills: list[str],
    expected_skills: list[str],
    acceptable_skills: list[str],
) -> float:
    """Compute accuracy score for activated skills.

    Returns:
        1.0 if any expected skill was activated.
        0.5 if any acceptable skill was activated.
        0.0 otherwise.
    """
    if not activated_skills:
        return 0.0

    activated_set = set(s.lower() for s in activated_skills)
    expected_set = set(s.lower() for s in expected_skills)
    acceptable_set = set(s.lower() for s in acceptable_skills)

    if activated_set & expected_set:
        return 1.0
    if activated_set & acceptable_set:
        return 0.5
    return 0.0


@dataclass
class ActivationResults:
    """Aggregated results for a single mechanism across all test cases."""

    mechanism: str = ""
    results: list[ActivationResult] = field(default_factory=list)

    def record(self, result: ActivationResult) -> None:
        self.results.append(result)

    @property
    def total_cases(self) -> int:
        return len(self.results)

    @property
    def positive_cases(self) -> int:
        """Cases where activation was expected."""
        return sum(1 for r in self.results if r.should_activate)

    @property
    def negative_cases(self) -> int:
        """Cases where activation was NOT expected."""
        return sum(1 for r in self.results if not r.should_activate)

    @property
    def activation_rate(self) -> float:
        """Fraction of ALL cases where the model activated any skill."""
        if not self.results:
            return 0.0
        return sum(1 for r in self.results if r.activated) / len(self.results)

    @property
    def true_positive_rate(self) -> float:
        """Fraction of positive cases where model activated."""
        pos = [r for r in self.results if r.should_activate]
        if not pos:
            return 0.0
        return sum(1 for r in pos if r.activated) / len(pos)

    @property
    def false_positive_rate(self) -> float:
        """Fraction of negative cases where model activated anyway."""
        neg = [r for r in self.results if not r.should_activate]
        if not neg:
            return 0.0
        return sum(1 for r in neg if r.activated) / len(neg)

    @property
    def accuracy_when_activated(self) -> float:
        """Among cases where the model activated, was it the right skill?"""
        activated = [r for r in self.results if r.activated and r.should_activate]
        if not activated:
            return 0.0
        return sum(r.accuracy for r in activated) / len(activated)

    @property
    def total_prompt_tokens(self) -> int:
        return sum(r.prompt_tokens for r in self.results)

    @property
    def total_completion_tokens(self) -> int:
        return sum(r.completion_tokens for r in self.results)

    @property
    def mean_prompt_tokens(self) -> float:
        if not self.results:
            return 0.0
        return self.total_prompt_tokens / len(self.results)

    @property
    def mean_completion_tokens(self) -> float:
        if not self.results:
            return 0.0
        return self.total_completion_tokens / len(self.results)

    @property
    def mean_total_tokens(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.total_tokens for r in self.results) / len(self.results)
