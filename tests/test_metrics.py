"""Tests for evaluation metrics."""

import pytest

from dotnet_skills_evals.eval_activation.metrics import (
    activation_accuracy,
    precision_at_k,
    recall,
    ActivationResults,
)
from dotnet_skills_evals.eval_effectiveness.metrics import (
    EffectivenessResult,
    EffectivenessResults,
)


class TestActivationMetrics:
    def test_exact_match(self):
        assert activation_accuracy(
            expected_skills=["akka-net-best-practices"],
            acceptable_skills=[],
            predicted_skills=["akka-net-best-practices"],
        ) == 1.0

    def test_acceptable_match(self):
        assert activation_accuracy(
            expected_skills=["akka-net-best-practices"],
            acceptable_skills=["akka-hosting-actor-patterns"],
            predicted_skills=["akka-hosting-actor-patterns"],
        ) == 0.5

    def test_miss(self):
        assert activation_accuracy(
            expected_skills=["akka-net-best-practices"],
            acceptable_skills=[],
            predicted_skills=["efcore-patterns"],
        ) == 0.0

    def test_empty_prediction(self):
        assert activation_accuracy(
            expected_skills=["akka-net-best-practices"],
            acceptable_skills=[],
            predicted_skills=[],
        ) == 0.0

    def test_exact_match_among_multiple(self):
        """Exact match found even with extra predictions."""
        assert activation_accuracy(
            expected_skills=["akka-net-best-practices"],
            acceptable_skills=[],
            predicted_skills=["efcore-patterns", "akka-net-best-practices"],
        ) == 1.0

    def test_precision_at_1_correct(self):
        assert precision_at_k(
            expected_skills=["akka-net-best-practices"],
            predicted_skills=["akka-net-best-practices", "other"],
        ) == 1.0

    def test_precision_at_1_wrong(self):
        assert precision_at_k(
            expected_skills=["akka-net-best-practices"],
            predicted_skills=["other", "akka-net-best-practices"],
        ) == 0.0

    def test_precision_at_1_empty(self):
        assert precision_at_k(
            expected_skills=["akka-net-best-practices"],
            predicted_skills=[],
        ) == 0.0

    def test_recall_full(self):
        assert recall(
            expected_skills=["a", "b"],
            predicted_skills=["a", "b", "c"],
        ) == 1.0

    def test_recall_partial(self):
        assert recall(
            expected_skills=["a", "b"],
            predicted_skills=["a"],
        ) == 0.5

    def test_recall_none(self):
        assert recall(
            expected_skills=["a", "b"],
            predicted_skills=["c"],
        ) == 0.0

    def test_recall_empty_expected(self):
        """Empty expected = vacuously true."""
        assert recall(
            expected_skills=[],
            predicted_skills=["a"],
        ) == 1.0


class TestActivationResults:
    def test_aggregation(self):
        results = ActivationResults()
        results.record("t1", ["a"], [], ["a"], "ok")
        results.record("t2", ["b"], ["c"], ["c"], "ok")
        results.record("t3", ["d"], [], ["e"], "miss")

        assert results.total_cases == 3
        assert results.exact_matches == 1
        assert results.acceptable_matches == 1
        assert results.misses == 1
        assert results.accuracy == pytest.approx((1.0 + 0.5) / 3)

    def test_confusion_tracking(self):
        results = ActivationResults()
        results.record("t1", ["a"], [], ["b"], "confused")
        results.record("t2", ["a"], [], ["b"], "confused again")

        confusions = results.top_confusions()
        assert len(confusions) == 1
        assert confusions[0] == ("a", "b", 2)


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
