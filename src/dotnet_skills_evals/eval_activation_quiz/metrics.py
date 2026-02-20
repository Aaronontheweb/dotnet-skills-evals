"""Metrics for skill activation evaluation."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field


def activation_accuracy(
    expected_skills: list[str],
    acceptable_skills: list[str],
    predicted_skills: list[str],
) -> float:
    """Multi-level scoring for skill activation accuracy.

    Returns:
        1.0 if any expected skill was selected.
        0.5 if an acceptable (but not ideal) skill was selected.
        0.0 if no relevant skill was selected.
    """
    predicted_set = set(predicted_skills)
    expected_set = set(expected_skills)
    acceptable_set = set(acceptable_skills)

    if predicted_set & expected_set:
        return 1.0
    if predicted_set & acceptable_set:
        return 0.5
    return 0.0


def precision_at_k(
    expected_skills: list[str],
    predicted_skills: list[str],
    k: int = 1,
) -> float:
    """Was the top-k prediction correct?

    Returns:
        1.0 if any of the top-k predictions is in expected_skills.
        0.0 otherwise.
    """
    if not predicted_skills:
        return 0.0
    top_k = set(predicted_skills[:k])
    return 1.0 if top_k & set(expected_skills) else 0.0


def recall(
    expected_skills: list[str],
    predicted_skills: list[str],
) -> float:
    """What fraction of expected skills were selected?"""
    if not expected_skills:
        return 1.0
    predicted_set = set(predicted_skills)
    hits = sum(1 for s in expected_skills if s in predicted_set)
    return hits / len(expected_skills)


@dataclass
class ConfusionEntry:
    """Tracks how often skill A was predicted when skill B was expected."""

    expected: str
    predicted: str
    count: int = 0


@dataclass
class ActivationResults:
    """Aggregated results from an activation evaluation run."""

    total_cases: int = 0
    exact_matches: int = 0
    acceptable_matches: int = 0
    misses: int = 0
    precision_at_1_sum: float = 0.0
    recall_sum: float = 0.0
    confusion: dict[str, dict[str, int]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(int))
    )
    per_case_results: list[dict] = field(default_factory=list)

    def record(
        self,
        case_id: str,
        expected_skills: list[str],
        acceptable_skills: list[str],
        predicted_skills: list[str],
        reasoning: str = "",
    ) -> None:
        """Record a single evaluation result."""
        self.total_cases += 1

        acc = activation_accuracy(expected_skills, acceptable_skills, predicted_skills)
        p1 = precision_at_k(expected_skills, predicted_skills, k=1)
        rec = recall(expected_skills, predicted_skills)

        if acc == 1.0:
            self.exact_matches += 1
        elif acc == 0.5:
            self.acceptable_matches += 1
        else:
            self.misses += 1

        self.precision_at_1_sum += p1
        self.recall_sum += rec

        # Track confusion
        for expected in expected_skills:
            for predicted in predicted_skills:
                if predicted != expected:
                    self.confusion[expected][predicted] += 1

        self.per_case_results.append(
            {
                "id": case_id,
                "expected": expected_skills,
                "acceptable": acceptable_skills,
                "predicted": predicted_skills,
                "accuracy": acc,
                "precision_at_1": p1,
                "recall": rec,
                "reasoning": reasoning,
            }
        )

    @property
    def accuracy(self) -> float:
        """Overall accuracy (exact + acceptable / total)."""
        if self.total_cases == 0:
            return 0.0
        return (self.exact_matches + 0.5 * self.acceptable_matches) / self.total_cases

    @property
    def exact_accuracy(self) -> float:
        """Strict accuracy (exact matches only)."""
        if self.total_cases == 0:
            return 0.0
        return self.exact_matches / self.total_cases

    @property
    def mean_precision_at_1(self) -> float:
        if self.total_cases == 0:
            return 0.0
        return self.precision_at_1_sum / self.total_cases

    @property
    def mean_recall(self) -> float:
        if self.total_cases == 0:
            return 0.0
        return self.recall_sum / self.total_cases

    def top_confusions(self, n: int = 10) -> list[tuple[str, str, int]]:
        """Return the most common confusion pairs."""
        pairs = []
        for expected, predicted_map in self.confusion.items():
            for predicted, count in predicted_map.items():
                pairs.append((expected, predicted, count))
        pairs.sort(key=lambda x: x[2], reverse=True)
        return pairs[:n]
