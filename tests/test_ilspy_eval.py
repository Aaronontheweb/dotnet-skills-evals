"""Measurement contracts; provider responses are scripted, never paid calls."""

import json
import subprocess
import sys

import litellm
import pytest

from dotnet_skills_evals.eval_ilspy import runner
from dotnet_skills_evals.eval_ilspy.metrics import score_events, summarize
from dotnet_skills_evals.eval_ilspy.sandbox import capture_command


ASSEMBLY = "Serilog.Sinks.PeriodicBatching.dll"
FIXTURE = {"commit": "a" * 40, "target_assemblies": {
    ASSEMBLY: {"sha256": "netstandard-hash", "path": "/packages/target.dll",
               "sha256_by_path": {"/lib/netstandard2.0/target.dll": "netstandard-hash",
                                  "/lib/net6.0/target.dll": "net6-hash"}}}}
SNAPSHOT = {
    "other-skill": {"description": "Other guidance", "files": {"SKILL.md": "COMMON"}},
    "ilspy-decompile": {"description": "Inspect assembly implementations",
                        "files": {"SKILL.md": "TARGET GUIDANCE", "reference.md": "REFERENCE"}},
}


def case(case_id="dependency-case", category="dependency"):
    return {"id": case_id, "category": category, "user_prompt": "Investigate dependency behavior.",
            "fixture_commit": "a" * 40,
            "target_assemblies": [ASSEMBLY] if category == "dependency" else []}


def event(**overrides):
    return {"phase": "finished", "decompilation_requested": True, "returncode": 0,
            "assemblies": {"/lib/target.dll": "net6-hash"}, "stdout_is_code": True,
            "generated_files": [], **overrides}


@pytest.mark.parametrize("overrides", [
    {"phase": "started"}, {"returncode": 1}, {"decompilation_requested": False},
    {"assemblies": {}}, {"stdout_is_code": False},
])
def test_non_decompilations_are_not_activation(overrides):
    assert not score_events([event(**overrides)], {"net6-hash"})["activated"]


def test_unrelated_assembly_does_not_count_as_relevant_activation():
    score = score_events([event()], {"different-package"})
    assert score == {"attempted": True, "any_decompilation": True, "activated": False}


def test_project_output_counts_without_stdout():
    score = score_events([event(stdout_is_code=False, generated_files=[{"path": "/tmp/X.cs"}])], {"net6-hash"})
    assert score["activated"]


def row(pair, condition, activated=False, **overrides):
    return {"pair_id": pair, "model": "subject", "category": "dependency", "condition": condition,
            "status": "completed", "activated": activated, "any_decompilation": activated,
            "attempted": activated, "loaded_skills": [], **overrides}


def test_uplift_uses_matched_pairs_excludes_errors_and_separates_controls():
    trials = [row("p1", "baseline"), row("p1", "skill", True),
              row("p2", "baseline", True), row("p2", "skill", True),
              row("bad", "baseline", True), row("bad", "skill", status="error"),
              row("unfinished", "skill", True),
              row("control", "baseline", category="repository_only"),
              row("control", "skill", category="repository_only", any_decompilation=True)]
    result = summarize(trials)["subject"]
    assert result["dependency"]["valid_pairs"] == 2
    assert result["dependency"]["excluded_pairs"] == 2
    assert result["dependency"]["baseline_rate"] == 0.5
    assert result["dependency"]["skill_rate"] == 1.0
    assert result["dependency"]["uplift_percentage_points"] == 50
    assert result["repository_only"]["uplift_percentage_points"] == 100


def test_no_valid_pairs_is_missing_not_zero_and_models_are_separate():
    trials = [row("p1", "baseline", status="error"), row("p1", "skill"),
              row("p2", "baseline", model="second"), row("p2", "skill", True, model="second")]
    result = summarize(trials)
    assert result["subject"]["dependency"]["baseline_rate"] is None
    assert result["subject"]["dependency"]["uplift_percentage_points"] is None
    assert result["second"]["dependency"]["uplift_percentage_points"] == 100


def test_budget_exhaustion_is_a_valid_observation():
    trials = [row("p1", "baseline", status="step_limit"), row("p1", "skill", True, status="token_limit")]
    assert summarize(trials)["subject"]["dependency"]["valid_pairs"] == 1


@pytest.mark.parametrize("change", [
    {"category": "unknown"}, {"target_assemblies": []}, {"user_prompt": ""},
    {"id": "../../outside"}, {"fixture_commit": "tag"},
    {"category": "repository_only", "target_assemblies": [ASSEMBLY]},
])
def test_bad_datasets_rejected_before_spending(tmp_path, change):
    path = tmp_path / "bad.jsonl"
    path.write_text(json.dumps({**case(), **change}))
    with pytest.raises(ValueError):
        runner.read_dataset(path)


def test_duplicate_cases_rejected(tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_text((json.dumps(case()) + "\n") * 2)
    with pytest.raises(ValueError, match="duplicate"):
        runner.read_dataset(path)


def test_real_dataset_has_dependency_cases_and_controls_without_tool_hints():
    cases = runner.read_dataset(runner.DATASET)
    assert {c["category"] for c in cases} == {"dependency", "repository_only"}
    for c in cases:
        assert "ilspy" not in c["user_prompt"].lower()
        assert "decompil" not in c["user_prompt"].lower()


class FakeSandbox:
    instances = []

    def __init__(self, image, command_timeout):
        self.image = image
        self.command_timeout = command_timeout
        self.commands = []
        self.__class__.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def shell(self, command):
        self.commands.append(command)
        return {"exit_code": 0, "stdout": "namespace Example; public class Target {}"}

    def events(self):
        return [event()] if self.commands else []


def response(tool=None, args=None, text=None):
    message = {"role": "assistant", "content": text}
    if tool:
        message["tool_calls"] = [{"id": "call-1", "type": "function", "function": {
            "name": tool, "arguments": json.dumps(args)}}]
    return litellm.ModelResponse(model="served-model", usage={"prompt_tokens": 10, "completion_tokens": 5},
                                choices=[{"index": 0, "finish_reason": "tool_calls" if tool else "stop",
                                          "message": message}])


def trial(monkeypatch, tmp_path, condition, responses):
    monkeypatch.setattr(runner, "DockerSandbox", FakeSandbox)
    replies = iter(responses)
    calls = []

    def complete(**kwargs):
        calls.append(json.loads(json.dumps(kwargs)))
        reply = next(replies)
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(runner.litellm, "completion", complete)
    result = runner.run_trial("openrouter/example/model", case(), condition, SNAPSHOT,
                              "image-id", FIXTURE, runner.Budget(), "dummy-key",
                              tmp_path / f"{condition}.json")
    return result, calls


def test_only_target_skill_availability_differs_between_arms(monkeypatch, tmp_path):
    b, b_calls = trial(monkeypatch, tmp_path, "baseline", [response(text="Answer")])
    s, s_calls = trial(monkeypatch, tmp_path, "skill", [response(text="Answer")])
    b_request, s_request = b_calls[0], s_calls[0]
    assert b_request["messages"] == s_request["messages"]
    system = b_request["messages"][0]["content"]
    assert "Decide if any of the skills in your index might be helpful towards accomplishing your goals." in system
    assert '{"skill_name": "<skill name from the index>"}' in system
    assert "ilspy" not in system.lower()
    assert b_request["tools"][0] == s_request["tools"][0]
    assert b_request["tools"][2:] == s_request["tools"][2:]
    assert b_request["tools"][2] == runner.WEB_SEARCH_TOOL
    assert b_request["tools"][3:] == runner.RESEARCH_TOOLS
    assert "ilspy-decompile" not in b_request["tools"][1]["function"]["description"]
    assert "ilspy-decompile" in s_request["tools"][1]["function"]["description"]
    assert "TARGET GUIDANCE" not in json.dumps(b_request)
    assert "TARGET GUIDANCE" not in json.dumps(s_request)
    for key in ("model", "max_tokens", "temperature", "caching", "api_base"):
        assert b_request[key] == s_request[key]
    assert b["loaded_skills"] == s["loaded_skills"] == []


def test_skill_load_alone_is_not_ilspy_activation(monkeypatch, tmp_path):
    result, calls = trial(monkeypatch, tmp_path, "skill", [
        response("invoke_skill", {"skill_name": "ilspy-decompile"}), response(text="Answer")])
    assert result["loaded_skills"] == ["ilspy-decompile"]
    assert not result["activated"]
    assert "TARGET GUIDANCE" in calls[1]["messages"][-1]["content"]


@pytest.mark.parametrize("field", ["server_tool_use_details", "server_tool_use"])
def test_native_search_usage_is_recorded_without_ilspy_activation(monkeypatch, tmp_path, field):
    reply = response(text="Found source")
    reply.usage = litellm.Usage(prompt_tokens=10, completion_tokens=5, **{field: {"web_search_requests": 1}})
    result, _ = trial(monkeypatch, tmp_path, "baseline", [reply])
    assert result["web_search_requests"] == 1
    assert not result["activated"]


def test_baseline_cannot_load_target_skill_but_can_decompile(monkeypatch, tmp_path):
    result, calls = trial(monkeypatch, tmp_path, "baseline", [
        response("invoke_skill", {"skill_name": "ilspy-decompile"}),
        response("shell", {"command": "ilspycmd target.dll"}), response(text="Answer")])
    assert result["loaded_skills"] == []
    assert "Unknown skill" in calls[1]["messages"][-1]["content"]
    assert result["activated"]  # net6 assembly hash counts, not just netstandard.


def test_provider_failure_preserves_prior_execution_and_is_not_a_valid_zero(monkeypatch, tmp_path):
    result, calls = trial(monkeypatch, tmp_path, "skill", [
        response("shell", {"command": "ilspycmd target.dll"}),
        RuntimeError("provider failure dummy-key")])
    assert result["status"] == "error"
    assert result["activated"]
    artifact = json.loads((tmp_path / "skill.json").read_text())
    assert artifact["ilspy_events"]
    assert "dummy-key" not in artifact["error"]


def test_preflight_makes_no_model_requests_or_requires_credentials(monkeypatch, tmp_path):
    path = tmp_path / "cases.jsonl"
    path.write_text(json.dumps(case()))
    monkeypatch.setattr(runner, "ensure_skills_repo", lambda _: tmp_path)
    monkeypatch.setattr(runner, "snapshot_skills", lambda _: (SNAPSHOT, {"commit": "skills-sha"}))
    monkeypatch.setattr(runner, "check_fixture", lambda _: {"fixture": FIXTURE, "image": {"id": "image"}})
    monkeypatch.setattr(runner, "OPENROUTER_API_KEY", "")
    monkeypatch.setattr(runner, "github_token", lambda: "")

    def forbidden(**kwargs):
        pytest.fail("Preflight must not call a model")

    monkeypatch.setattr(runner.litellm, "completion", forbidden)
    result = runner.run_eval(("openrouter/example/model",), dataset=path,
                             repetitions=2, preflight_only=True)
    assert result["trials"] == 4
    assert result["api_calls"] == 0
    assert result["research"]["github_authenticated"] is False


def test_failed_pair_is_checkpointed_and_stops_further_requests(monkeypatch, tmp_path):
    path = tmp_path / "cases.jsonl"
    path.write_text(json.dumps(case()))
    output = tmp_path / "result.json"
    monkeypatch.setattr(runner, "ensure_skills_repo", lambda _: tmp_path)
    monkeypatch.setattr(runner, "snapshot_skills", lambda _: (SNAPSHOT, {}))
    monkeypatch.setattr(runner, "check_fixture", lambda _: {"fixture": FIXTURE, "image": {"id": "image"}})
    monkeypatch.setattr(runner, "OPENROUTER_API_KEY", "dummy-key")
    monkeypatch.setattr(runner, "github_token", lambda: "dummy-github-token")
    calls = []

    def failed(*args):
        calls.append(args)
        return row("ignored", "ignored", status="error", error="provider error")

    monkeypatch.setattr(runner, "run_trial", failed)
    with pytest.raises(RuntimeError, match="Trial failed"):
        runner.run_eval(("openrouter/example/model",), dataset=path, output=output, repetitions=3)
    report = json.loads(output.read_text())
    assert len(calls) == 1
    assert report["status"] == "interrupted"
    assert report["summary"]["subject"]["dependency"]["valid_pairs"] == 0


def test_noisy_tool_output_is_drained_without_unbounded_buffering():
    result = capture_command([sys.executable, "-c",
                              "import sys; sys.stdout.write('a'*1000000); sys.stderr.write('b'*1000000)"], 5)
    assert result["exit_code"] == 0
    assert len(result["stdout"]) == 32000
    assert len(result["stderr"]) == 8000
    assert result["output_truncated"]


def test_hung_command_is_terminated():
    with pytest.raises(subprocess.TimeoutExpired):
        capture_command([sys.executable, "-c", "import time; time.sleep(10)"], 1)
