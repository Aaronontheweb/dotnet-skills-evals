"""Tests for evaluation metrics."""

import pytest

from dotnet_skills_evals.eval_effectiveness.metrics import (
    EffectivenessResult,
    EffectivenessResults,
)


class TestEffectivenessMetrics:
    def test_improvement_positive(self):
        r = EffectivenessResult(
            case_id="t1", skill_name="s", task="t",
            baseline_score=2, enhanced_score=4,
            winner="enhanced", reasoning="better"
        )
        assert r.improvement == 2
        assert r.skill_helped is True

    def test_improvement_negative(self):
        r = EffectivenessResult(
            case_id="t1", skill_name="s", task="t",
            baseline_score=4, enhanced_score=2,
            winner="baseline", reasoning="worse"
        )
        assert r.improvement == -2
        assert r.skill_helped is False

    def test_aggregated_results(self):
        results = EffectivenessResults()
        results.record("t1", "s1", "task1", 2, 4, "enhanced", "better")
        results.record("t2", "s1", "task2", 3, 3, "tie", "same")
        results.record("t3", "s2", "task3", 4, 2, "baseline", "worse")

        assert results.total_cases == 3
        assert results.skill_wins == 1
        assert results.baseline_wins == 1
        assert results.ties == 1
        assert results.win_rate == pytest.approx(1 / 3)
        assert results.mean_baseline_score == pytest.approx(3.0)
        assert results.mean_enhanced_score == pytest.approx(3.0)

    def test_results_by_skill(self):
        results = EffectivenessResults()
        results.record("t1", "s1", "task1", 2, 4, "enhanced", "better")
        results.record("t2", "s2", "task2", 3, 3, "tie", "same")

        by_skill = results.results_by_skill()
        assert "s1" in by_skill
        assert "s2" in by_skill
        assert len(by_skill["s1"]) == 1
