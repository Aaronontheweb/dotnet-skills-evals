"""Paired baseline/skill trials with a small provider-neutral tool loop."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from collections import Counter
from pathlib import Path
import random
import re
import subprocess
import time

import litellm

from ..config import OPENROUTER_API_KEY, ensure_skills_repo, get_model_id
from ..skills.loader import load_skills_from_plugin_json
from .metrics import score_events, summarize
from .sandbox import DEFAULT_IMAGE, DockerSandbox, check_fixture
from .research import ResearchConfig, ResearchTools, RESEARCH_NAMES, RESEARCH_TOOLS, WEB_SEARCH_TOOL, github_token
from .retrieval import HttpClient


DATASET = Path(__file__).resolve().parents[3] / "datasets" / "ilspy" / "seq.jsonl"
SYSTEM = """You are a .NET development assistant investigating an existing project.
The repository is at /workspace/repo. The .NET SDK and restored NuGet packages
are available; NUGET_PACKAGES points to the package cache. Use /tmp for scratch
files. The checkout and package cache are read-only. Network retrieval is available
through the provided research tools; downloaded repositories can be searched with
the shell. Investigate the requested behavior and provide evidence.
You may load available skills with invoke_skill when useful.
"""
SHELL_TOOL = {"type": "function", "function": {
    "name": "shell", "description": "Run a Bash command in the project investigation container.",
    "parameters": {"type": "object", "properties": {"command": {"type": "string"}},
                   "required": ["command"], "additionalProperties": False}}}


@dataclass(frozen=True)
class Budget:
    max_steps: int = 30
    max_completion_tokens: int = 8192
    max_total_tokens: int = 100000
    trial_seconds: int = 900
    command_seconds: int = 60
    temperature: float = 0.0
    request_seconds: int = 180


def read_dataset(path: Path) -> list[dict]:
    cases = []
    seen = set()
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        case = json.loads(line)
        if not isinstance(case, dict):
            raise ValueError(f"{path}:{lineno}: expected an object")
        for key in ("id", "user_prompt", "category", "fixture_commit", "target_assemblies"):
            if key not in case:
                raise ValueError(f"{path}:{lineno}: missing {key}")
        if not isinstance(case["id"], str) or not re.fullmatch(r"[a-zA-Z0-9_-]+", case["id"]):
            raise ValueError(f"{path}:{lineno}: invalid case id")
        if case["id"] in seen:
            raise ValueError(f"{path}:{lineno}: duplicate case id {case['id']}")
        if case["category"] not in {"dependency", "repository_only"}:
            raise ValueError(f"{path}:{lineno}: invalid category")
        targets = case["target_assemblies"]
        if not isinstance(targets, list) or not all(isinstance(t, str) and t for t in targets):
            raise ValueError(f"{path}:{lineno}: target_assemblies must be a string array")
        if (case["category"] == "dependency") != bool(targets):
            raise ValueError(f"{path}:{lineno}: only dependency cases must have target assemblies")
        if not isinstance(case["user_prompt"], str) or not case["user_prompt"].strip():
            raise ValueError(f"{path}:{lineno}: empty prompt")
        if not isinstance(case["fixture_commit"], str) or not re.fullmatch(r"[0-9a-f]{40}", case["fixture_commit"]):
            raise ValueError(f"{path}:{lineno}: fixture_commit must be a full SHA")
        seen.add(case["id"])
        cases.append(case)
    if not cases:
        raise ValueError(f"{path}: empty dataset")
    return cases


def snapshot_skills(repo: Path) -> tuple[dict, dict]:
    """Freeze catalog, bodies and references once so both arms share a snapshot."""
    skills = load_skills_from_plugin_json(repo / ".claude-plugin" / "plugin.json")
    snapshot = {}
    for skill in skills:
        root = skill.metadata.file_path.parent.resolve()
        files = {}
        for path in sorted(root.rglob("*.md")):
            if not path.resolve().is_relative_to(root):
                raise ValueError(f"Skill reference escapes its directory: {path}")
            files[str(path.relative_to(root))] = path.read_text(encoding="utf-8")
        snapshot[skill.metadata.name] = {"description": skill.metadata.description, "files": files}
    if "ilspy-decompile" not in snapshot:
        raise ValueError("Skill catalog does not contain ilspy-decompile")
    revision = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                              capture_output=True, text=True)
    provenance = {"repo": str(repo), "commit": revision.stdout.strip() or None,
                  "files_sha256": {name: {f: hashlib.sha256(c.encode()).hexdigest()
                                          for f, c in data["files"].items()}
                                   for name, data in snapshot.items()}}
    return snapshot, provenance


def available_skills(snapshot: dict, condition: str) -> dict:
    return {name: skill for name, skill in snapshot.items()
            if condition == "skill" or name != "ilspy-decompile"}


def skill_tool(skills: dict) -> dict:
    catalog = "\n".join(f"- {name}: {s['description']}" for name, s in skills.items())
    return {"type": "function", "function": {
        "name": "invoke_skill",
        "description": "Load guidance from an available development skill.\n" + catalog,
        "parameters": {"type": "object", "properties": {
            "skill_name": {"type": "string"},
            "reference": {"type": "string", "description": "Relative markdown path; defaults to SKILL.md."}},
            "required": ["skill_name"], "additionalProperties": False}}}


def run_trial(model: str, case: dict, condition: str, snapshot: dict, image: str,
              fixture: dict, budget: Budget, api_key: str, artifact: Path,
              research_config: ResearchConfig = ResearchConfig(), http: HttpClient | None = None) -> dict:
    skills = available_skills(snapshot, condition)
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": case["user_prompt"]}]
    loaded = []
    records = []
    events = []
    prompt_tokens = completion_tokens = 0
    served_models = set()
    status = "step_limit"
    error = None
    started = time.monotonic()
    sandbox = None
    research = None
    searches = 0
    try:
        with DockerSandbox(image, budget.command_seconds) as sandbox:
            research = ResearchTools(http or HttpClient(artifact.parent / "retrieval-cache"), sandbox, research_config)
            try:
                for _ in range(budget.max_steps):
                    remaining = budget.trial_seconds - (time.monotonic() - started)
                    if remaining <= 0:
                        status = "time_limit"
                        break
                    if prompt_tokens + completion_tokens >= budget.max_total_tokens:
                        status = "token_limit"
                        break
                    response = litellm.completion(
                        model=model, messages=messages,
                        tools=[SHELL_TOOL, skill_tool(skills), WEB_SEARCH_TOOL, *RESEARCH_TOOLS],
                        api_key=api_key, api_base="https://openrouter.ai/api/v1",
                        temperature=budget.temperature,
                        max_tokens=min(budget.max_completion_tokens, budget.max_total_tokens
                                       - prompt_tokens - completion_tokens),
                        timeout=min(budget.request_seconds, remaining), num_retries=0, caching=False,
                    )
                    prompt_tokens += response.usage.prompt_tokens
                    completion_tokens += response.usage.completion_tokens
                    usage = response.usage.model_dump()
                    searches += (usage.get("server_tool_use") or {}).get("web_search_requests", 0)
                    served_models.add(response.model)
                    choice = response.choices[0]
                    message = choice.message.model_dump(exclude_none=True)
                    messages.append(message)
                    records.append({"model": response.model, "request_id": response.id,
                                    "usage": usage,
                                    "server_tool_calls": getattr(response, "server_tool_calls", None),
                                    "annotations": message.get("annotations", []),
                                    "finish_reason": choice.finish_reason})
                    if not choice.message.tool_calls:
                        status = "output_limit" if choice.finish_reason == "length" else "completed"
                        break
                    for call in choice.message.tool_calls:
                        if time.monotonic() - started >= budget.trial_seconds:
                            status = "time_limit"
                            break
                        try:
                            args = json.loads(call.function.arguments)
                            if not isinstance(args, dict):
                                raise ValueError("Tool arguments must be an object")
                            if call.function.name == "shell":
                                if not isinstance(args.get("command"), str):
                                    raise ValueError("command must be a string")
                                sandbox.command_timeout = min(budget.command_seconds, max(1, int(
                                    budget.trial_seconds - (time.monotonic() - started))))
                                result = sandbox.shell(args["command"])
                            elif call.function.name in RESEARCH_NAMES:
                                result = research.invoke(call.function.name, args)
                            elif call.function.name == "invoke_skill":
                                name = args.get("skill_name", "")
                                reference = args.get("reference", "SKILL.md")
                                if name not in skills or reference not in skills[name]["files"]:
                                    result = {"error": "Unknown skill or reference"}
                                else:
                                    loaded.append(name)
                                    result = {"content": skills[name]["files"][reference],
                                              "references": list(skills[name]["files"])}
                            else:
                                result = {"error": "Unknown tool"}
                        except (ValueError, TypeError) as exc:
                            result = {"error": str(exc)}
                        messages.append({"role": "tool", "tool_call_id": call.id,
                                         "content": json.dumps(result)})
                    if status == "time_limit":
                        break
            finally:
                events = sandbox.events()
    except Exception as exc:
        # Provider and infrastructure errors are missing evidence, not zeros.
        status = "error"
        error = str(exc).replace(api_key, "[REDACTED]") if api_key else str(exc)
    relevant = {sha for name in case["target_assemblies"]
                for sha in fixture["target_assemblies"][name]["sha256_by_path"].values()}
    artifact.write_text(json.dumps({"messages": messages, "responses": records,
                                    "research_events": research.events if research else [],
                                    "ilspy_events": events, "error": error}, indent=2), encoding="utf-8")
    return {"model": model, "case_id": case["id"], "category": case["category"],
            "condition": condition, "status": status, "error": error,
            "loaded_skills": sorted(set(loaded)), "served_models": sorted(served_models),
            "research_tool_calls": dict(Counter(e["tool"] for e in research.events)) if research else {},
            "web_search_requests": searches,
            "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
            "elapsed_seconds": time.monotonic() - started, "artifact": str(artifact),
            **score_events(events, relevant)}


def write_report(path: Path, report: dict) -> None:
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(report, indent=2), encoding="utf-8")
    temp.replace(path)


def run_eval(models: tuple[str, ...], dataset: Path = DATASET, repetitions: int = 5,
             skills_repo: Path | None = None, image: str = DEFAULT_IMAGE,
             output: Path | None = None, seed: int = 42, case_ids: tuple[str, ...] = (),
             budget: Budget = Budget(), preflight_only: bool = False) -> dict:
    from rich.console import Console

    console = Console()
    cases = read_dataset(dataset)
    unknown = set(case_ids) - {c["id"] for c in cases}
    if unknown:
        raise ValueError(f"Unknown case id(s): {sorted(unknown)}")
    cases = [c for c in cases if not case_ids or c["id"] in case_ids]
    if repetitions < 1 or not models:
        raise ValueError("At least one model and repetition are required")
    resolved = list(dict.fromkeys(get_model_id(m) for m in models))
    if any(not m.startswith("openrouter/") for m in resolved):
        raise ValueError("Use OpenRouter model IDs: openrouter/<provider>/<versioned-model>")
    if any(v <= 0 for k, v in asdict(budget).items() if k != "temperature"):
        raise ValueError("All budget limits must be positive")
    snapshot, provenance = snapshot_skills(ensure_skills_repo(skills_repo))
    research_config = ResearchConfig(github_token())
    preflight = check_fixture(image)
    fixture = preflight["fixture"]
    for case in cases:
        if case["fixture_commit"] != fixture["commit"]:
            raise ValueError(f"{case['id']}: fixture commit does not match dataset")
        if set(case["target_assemblies"]) - fixture["target_assemblies"].keys():
            raise ValueError(f"{case['id']}: unknown target assembly")
    if preflight_only:
        return {"preflight": preflight, "models": resolved, "cases": len(cases),
                "trials": len(resolved) * len(cases) * repetitions * 2,
                "skills": provenance, "api_calls": 0}
    if not OPENROUTER_API_KEY or OPENROUTER_API_KEY == "sk-or-...":
        raise ValueError("Set OPENROUTER_API_KEY in the environment or worktree .env")
    if not research_config.github_token:
        raise ValueError("Configure GITHUB_TOKEN, GH_TOKEN, or a local gh login so GitHub code search works in both arms")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    output = (output or Path("results/ilspy") / f"{timestamp}.json").resolve()
    if output.suffix != ".json":
        raise ValueError("--output must name a .json file")
    if output.exists() or output.with_suffix("").exists():
        raise ValueError(f"Output already exists: {output}")
    artifacts = output.with_suffix("")
    artifacts.mkdir(parents=True)
    rng = random.Random(seed)
    schedule = [(m, c, r) for m in resolved for c in cases for r in range(1, repetitions + 1)]
    rng.shuffle(schedule)
    ordered_pairs = []
    for i, (model, case, repeat) in enumerate(schedule):
        conditions = ["baseline", "skill"]
        rng.shuffle(conditions)
        ordered_pairs.append({"pair_id": f"pair-{i + 1:04d}", "model": model,
                              "case_id": case["id"], "repetition": repeat,
                              "conditions": conditions})
    harness_root = Path(__file__).resolve().parents[3]
    harness_git = subprocess.run(["git", "-C", str(harness_root), "rev-parse", "HEAD"],
                                 capture_output=True, text=True)
    harness_files = [Path(__file__).parent.parent / "cli.py", *sorted(Path(__file__).parent.glob("*.py"))]
    http = HttpClient(artifacts / "retrieval-cache")
    report = {"schema_version": 2, "created_at": timestamp,
              "experiment": "ilspy-skill-availability-with-research", "preflight": preflight,
              "research": research_config.provenance(),
              "harness_commit": harness_git.stdout.strip() or None,
              "harness_files_sha256": {str(p.relative_to(harness_root)): hashlib.sha256(p.read_bytes()).hexdigest()
                                       for p in harness_files},
              "skills": provenance, "budget": asdict(budget), "seed": seed,
              "total_token_limit": "soft stop after response; includes prompt and completion usage",
              "repetitions": repetitions, "models": resolved, "cases": cases,
              "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
              "schedule": ordered_pairs, "trials": [], "summary": {}, "status": "running"}
    write_report(output, report)
    try:
        for pair, (model, case, repeat) in zip(ordered_pairs, schedule):
            conditions = pair["conditions"]
            pair_id = pair["pair_id"]
            for condition in conditions:
                console.print(f"{pair_id} {model} {case['id']} repeat={repeat} {condition}", markup=False)
                trial = run_trial(model, case, condition, snapshot, preflight["image"]["id"],
                                  fixture, budget, OPENROUTER_API_KEY,
                                  artifacts / f"{pair_id}-{condition}.json", research_config, http)
                trial.update(pair_id=pair_id, repetition=repeat, order=conditions.index(condition))
                report["trials"].append(trial)
                report["summary"] = summarize(report["trials"])
                write_report(output, report)
                console.print(f"  status={trial['status']} activated={trial['activated']} "
                              f"skill_loaded={'ilspy-decompile' in trial['loaded_skills']}", markup=False)
                # A broken provider credential/route should not consume the full
                # matrix. Preserve partial evidence and stop on the first error.
                if trial["status"] == "error":
                    raise RuntimeError(f"Trial failed; evidence saved to {output}: {trial['error']}")
        report["status"] = "completed"
    except BaseException:
        report["status"] = "interrupted"
        raise
    finally:
        report["summary"] = summarize(report["trials"])
        write_report(output, report)
    console.print(f"Results: {output}", markup=False)
    return report
