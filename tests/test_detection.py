"""Tests for skill reference detection in free-text responses."""

from dotnet_skills_evals.eval_activation.detection import detect_skill_references


SAMPLE_SKILLS = [
    "akka-net-best-practices",
    "akka-net-testing-patterns",
    "akka-hosting-actor-patterns",
    "akka-net-management",
    "akka-net-aspire-configuration",
    "modern-csharp-coding-standards",
    "efcore-patterns",
]


class TestDetectSkillReferences:
    def test_no_match(self):
        response = "You should use the actor model with supervision strategies."
        assert detect_skill_references(response, SAMPLE_SKILLS) == []

    def test_exact_match(self):
        response = "Based on the akka-net-best-practices guidance, you should..."
        assert detect_skill_references(response, SAMPLE_SKILLS) == [
            "akka-net-best-practices"
        ]

    def test_multiple_matches(self):
        response = (
            "You'll want to consult akka-net-best-practices for the actor design "
            "and akka-net-testing-patterns for testing it."
        )
        found = detect_skill_references(response, SAMPLE_SKILLS)
        assert "akka-net-best-practices" in found
        assert "akka-net-testing-patterns" in found
        assert len(found) == 2

    def test_case_insensitive(self):
        response = "See AKKA-NET-BEST-PRACTICES for details."
        assert detect_skill_references(response, SAMPLE_SKILLS) == [
            "akka-net-best-practices"
        ]

    def test_embedded_in_sentence(self):
        response = (
            "The efcore-patterns skill covers query optimization techniques "
            "that would help here."
        )
        assert detect_skill_references(response, SAMPLE_SKILLS) == [
            "efcore-patterns"
        ]

    def test_preserves_order(self):
        """Results come back in known_skills order, not response order."""
        response = "Use efcore-patterns and akka-net-best-practices."
        found = detect_skill_references(response, SAMPLE_SKILLS)
        assert found == ["akka-net-best-practices", "efcore-patterns"]

    def test_empty_response(self):
        assert detect_skill_references("", SAMPLE_SKILLS) == []

    def test_empty_skills(self):
        assert detect_skill_references("some text", []) == []

    def test_code_block_with_skill_name(self):
        response = '''Here's the fix:

```csharp
// Following akka-net-best-practices guidance
public class MyActor : ReceiveActor { }
```'''
        assert detect_skill_references(response, SAMPLE_SKILLS) == [
            "akka-net-best-practices"
        ]

    def test_no_false_positive_on_partial_match(self):
        """'akka-net' alone should NOT match 'akka-net-best-practices'."""
        response = "This is an akka-net project using the standard patterns."
        found = detect_skill_references(response, SAMPLE_SKILLS)
        # "akka-net" is a substring of several skills but not an exact match
        # However, detect_skill_references uses substring matching, so
        # skills whose full name appears as a substring WILL match
        # "akka-net" is not any of the skill names, so no match expected
        assert found == []
