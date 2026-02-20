"""Metrics for skill effectiveness evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class EffectivenessResult:
    """Result of a single effectiveness comparison."""

    case_id: str
    skill_name: str
    task: str
    baseline_score: int
    enhanced_score: int
    winner: str  # "baseline", "enhanced", or "tie"
    reasoning: str
    baseline_response: str = ""
    enhanced_response: str = ""

    @property
    def improvement(self) -> int:
        """Score improvement from skill (positive = skill helped)."""
        return self.enhanced_score - self.baseline_score

    @property
    def skill_helped(self) -> bool:
        """Whether the skill improved the output."""
        return self.enhanced_score > self.baseline_score


@dataclass
class EffectivenessResults:
    """Aggregated results from an effectiveness evaluation run."""

    results: list[EffectivenessResult] = field(default_factory=list)

    def record(
        self,
        case_id: str,
        skill_name: str,
        task: str,
        baseline_score: int,
        enhanced_score: int,
        winner: str,
        reasoning: str,
        baseline_response: str = "",
        enhanced_response: str = "",
    ) -> None:
        """Record a single evaluation result."""
        self.results.append(
            EffectivenessResult(
                case_id=case_id,
                skill_name=skill_name,
                task=task,
                baseline_score=baseline_score,
                enhanced_score=enhanced_score,
                winner=winner,
                reasoning=reasoning,
                baseline_response=baseline_response,
                enhanced_response=enhanced_response,
            )
        )

    @property
    def total_cases(self) -> int:
        return len(self.results)

    @property
    def skill_wins(self) -> int:
        """How many times the skill-enhanced response was better."""
        return sum(1 for r in self.results if r.skill_helped)

    @property
    def baseline_wins(self) -> int:
        """How many times the baseline was better or equal."""
        return sum(1 for r in self.results if r.enhanced_score < r.baseline_score)

    @property
    def ties(self) -> int:
        return sum(1 for r in self.results if r.enhanced_score == r.baseline_score)

    @property
    def mean_baseline_score(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.baseline_score for r in self.results) / len(self.results)

    @property
    def mean_enhanced_score(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.enhanced_score for r in self.results) / len(self.results)

    @property
    def mean_improvement(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.improvement for r in self.results) / len(self.results)

    @property
    def win_rate(self) -> float:
        """Fraction of cases where the skill improved the output."""
        if not self.results:
            return 0.0
        return self.skill_wins / len(self.results)

    def results_by_skill(self) -> dict[str, list[EffectivenessResult]]:
        """Group results by skill name."""
        by_skill: dict[str, list[EffectivenessResult]] = {}
        for r in self.results:
            by_skill.setdefault(r.skill_name, []).append(r)
        return by_skill
