"""Tests for realistic activation eval metrics."""

import pytest

from dotnet_skills_evals.eval_activation.metrics import (
    ActivationResult,
    ActivationResults,
    compute_accuracy,
)


class TestComputeAccuracy:
    def test_exact_match(self):
        assert compute_accuracy(
            activated_skills=["akka-net-best-practices"],
            expected_skills=["akka-net-best-practices"],
            acceptable_skills=[],
        ) == 1.0

    def test_acceptable_match(self):
        assert compute_accuracy(
            activated_skills=["akka-hosting-actor-patterns"],
            expected_skills=["akka-net-best-practices"],
            acceptable_skills=["akka-hosting-actor-patterns"],
        ) == 0.5

    def test_wrong_skill(self):
        assert compute_accuracy(
            activated_skills=["efcore-patterns"],
            expected_skills=["akka-net-best-practices"],
            acceptable_skills=[],
        ) == 0.0

    def test_no_activation(self):
        assert compute_accuracy(
            activated_skills=[],
            expected_skills=["akka-net-best-practices"],
            acceptable_skills=[],
        ) == 0.0

    def test_exact_takes_priority_over_acceptable(self):
        assert compute_accuracy(
            activated_skills=["akka-net-best-practices", "akka-hosting-actor-patterns"],
            expected_skills=["akka-net-best-practices"],
            acceptable_skills=["akka-hosting-actor-patterns"],
        ) == 1.0

    def test_case_insensitive(self):
        assert compute_accuracy(
            activated_skills=["Akka-Net-Best-Practices"],
            expected_skills=["akka-net-best-practices"],
            acceptable_skills=[],
        ) == 1.0


class TestActivationResult:
    def _make_result(self, should_activate: bool, activated: bool, **kwargs):
        return ActivationResult(
            case_id="test",
            mechanism="tool",
            should_activate=should_activate,
            activated=activated,
            activated_skills=kwargs.get("activated_skills", []),
            expected_skills=kwargs.get("expected_skills", []),
            acceptable_skills=[],
            accuracy=kwargs.get("accuracy", 0.0),
            response_text="",
            prompt_tokens=100,
            completion_tokens=50,
        )

    def test_true_positive(self):
        r = self._make_result(should_activate=True, activated=True)
        assert r.true_positive is True
        assert r.false_positive is False
        assert r.false_negative is False
        assert r.true_negative is False

    def test_false_positive(self):
        r = self._make_result(should_activate=False, activated=True)
        assert r.false_positive is True
        assert r.true_positive is False

    def test_true_negative(self):
        r = self._make_result(should_activate=False, activated=False)
        assert r.true_negative is True
        assert r.false_positive is False

    def test_false_negative(self):
        r = self._make_result(should_activate=True, activated=False)
        assert r.false_negative is True
        assert r.true_positive is False

    def test_total_tokens(self):
        r = self._make_result(should_activate=True, activated=True)
        assert r.total_tokens == 150


class TestActivationResults:
    def _make_result(
        self, case_id, should_activate, activated, accuracy=0.0,
        prompt_tokens=100, completion_tokens=50,
    ):
        return ActivationResult(
            case_id=case_id,
            mechanism="tool",
            should_activate=should_activate,
            activated=activated,
            activated_skills=["skill"] if activated else [],
            expected_skills=["skill"] if should_activate else [],
            acceptable_skills=[],
            accuracy=accuracy,
            response_text="",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    def test_activation_rate(self):
        results = ActivationResults(mechanism="tool")
        results.record(self._make_result("t1", True, True, 1.0))
        results.record(self._make_result("t2", True, False, 0.0))
        results.record(self._make_result("t3", False, False, 0.0))
        results.record(self._make_result("t4", False, True, 0.0))

        assert results.total_cases == 4
        assert results.activation_rate == pytest.approx(0.5)  # 2/4

    def test_true_positive_rate(self):
        results = ActivationResults(mechanism="tool")
        results.record(self._make_result("t1", True, True, 1.0))
        results.record(self._make_result("t2", True, True, 1.0))
        results.record(self._make_result("t3", True, False, 0.0))

        assert results.positive_cases == 3
        assert results.true_positive_rate == pytest.approx(2 / 3)

    def test_false_positive_rate(self):
        results = ActivationResults(mechanism="tool")
        results.record(self._make_result("t1", False, False, 0.0))
        results.record(self._make_result("t2", False, True, 0.0))

        assert results.negative_cases == 2
        assert results.false_positive_rate == pytest.approx(0.5)

    def test_accuracy_when_activated(self):
        results = ActivationResults(mechanism="tool")
        results.record(self._make_result("t1", True, True, 1.0))
        results.record(self._make_result("t2", True, True, 0.5))
        results.record(self._make_result("t3", True, False, 0.0))  # not activated, excluded

        assert results.accuracy_when_activated == pytest.approx(0.75)

    def test_token_tracking(self):
        results = ActivationResults(mechanism="tool")
        results.record(self._make_result("t1", True, True, 1.0, 200, 80))
        results.record(self._make_result("t2", True, True, 1.0, 300, 120))

        assert results.total_prompt_tokens == 500
        assert results.total_completion_tokens == 200
        assert results.mean_prompt_tokens == pytest.approx(250.0)
        assert results.mean_completion_tokens == pytest.approx(100.0)
        assert results.mean_total_tokens == pytest.approx(350.0)

    def test_empty_results(self):
        results = ActivationResults(mechanism="tool")
        assert results.activation_rate == 0.0
        assert results.true_positive_rate == 0.0
        assert results.false_positive_rate == 0.0
        assert results.accuracy_when_activated == 0.0
        assert results.mean_prompt_tokens == 0.0

    def test_no_negatives(self):
        """false_positive_rate is 0 when there are no negative cases."""
        results = ActivationResults(mechanism="tool")
        results.record(self._make_result("t1", True, True, 1.0))
        assert results.false_positive_rate == 0.0
