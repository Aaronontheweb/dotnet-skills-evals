"""Offline report regeneration and presentation; no models or Docker required."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from rich.console import Console
from rich.table import Table

from .diagnostics import TARGET_SKILL, json_sha256, trial_diagnostics
from .metrics import score_events, summarize


def reanalyze_report(source: Path, output: Path) -> dict:
    """Write a derived report, preserving raw reports and trial artifacts."""
    source, output = source.resolve(), output.resolve()
    if output.suffix != ".json":
        raise ValueError("--output must name a .json file")
    if output.exists():
        raise ValueError(f"Output already exists: {output}")
    original = source.read_bytes()
    report = json.loads(original)
    if not {"trials", "preflight", "skills"} <= report.keys():
        raise ValueError("Expected an ILSpy evaluation report, not a batch manifest or transcript")
    fixture = report["preflight"]["fixture"]
    cases = {case["id"]: case for case in report["cases"]}
    index_reconstructable = TARGET_SKILL in report["skills"].get("files_sha256", {})
    changes = []
    artifact_sources = []
    for trial in report["trials"]:
        # Prefer adjacent artifacts so a copied results bundle remains usable.
        candidates = [source.with_suffix("") / f"{trial['pair_id']}-{trial['condition']}.json"]
        if trial.get("artifact"):
            recorded = Path(trial["artifact"])
            candidates.append(recorded if recorded.is_absolute() else source.parent / recorded)
        artifact_path = next((p for p in candidates if p.is_file()), None)
        if artifact_path is None:
            raise ValueError(f"Missing transcript for {trial['pair_id']} {trial['condition']}")
        raw = artifact_path.read_bytes()
        artifact = json.loads(raw)
        for request in artifact.get("requests", []):
            prefix = artifact["messages"][:request["message_count"]]
            if json_sha256(prefix) != request["messages_sha256"]:
                raise ValueError(f"Request message hash mismatch: {artifact_path}")
            tools = artifact["request_context"]["tools"]
            if json_sha256(tools) != request["tools_sha256"]:
                raise ValueError(f"Request tool hash mismatch: {artifact_path}")
        case = cases[trial["case_id"]]
        relevant = {sha for name in case["target_assemblies"]
                    for sha in fixture["target_assemblies"][name]["sha256_by_path"].values()}
        score = score_events(artifact["ilspy_events"], relevant)
        if any(trial.get(key) != value for key, value in score.items()):
            changes.append({"pair_id": trial["pair_id"], "condition": trial["condition"],
                            "before": {key: trial.get(key) for key in score}, "after": score})
        trial.update(score)
        trial["skill_diagnostics"] = trial_diagnostics(
            trial, artifact, relevant, reconstruct_index=index_reconstructable)
        artifact_sources.append({"pair_id": trial["pair_id"], "condition": trial["condition"],
                                 "path": str(artifact_path), "sha256": hashlib.sha256(raw).hexdigest()})
        trial["artifact"] = str(artifact_path)
    report["summary"] = summarize(report["trials"])
    source_schema = report.get("schema_version")
    report["schema_version"] = 3
    report["reanalysis"] = {
        "created_at": datetime.now(timezone.utc).isoformat(), "source_report": str(source),
        "source_sha256": hashlib.sha256(original).hexdigest(), "source_schema_version": source_schema,
        "api_calls": 0, "score_changes": changes, "artifacts": artifact_sources,
        "diagnostics_files_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                     for p in sorted(Path(__file__).parent.glob("*.py"))},
        "notes": ["Original run status, schedule, prompts, budgets and harness provenance are preserved.",
                  "Historical index exposure is reconstructed from condition and skill-snapshot provenance; "
                  "missing outbound requests are not recreated.",
                  "Execution before/after a body load describes ordering, not causal attribution."],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation also prevents accidental replacement during a race.
    with output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    return report


def print_results(report: dict, console: Console) -> None:
    primary = Table(title="Successful ILSpy use: without vs with skill available")
    for title in ("Model", "Cases", "Valid pairs", "Excluded", "Without skill", "With skill", "Uplift (pp)"):
        primary.add_column(title)
    details = []
    stopping = Table(title="Stopping reasons (all saved trials, including excluded partners)")
    for title in ("Model", "Arm", "Saved", "Completed", "Budget limited", "Errors", "Statuses"):
        stopping.add_column(title)
    exposure_sources = set()
    for model, categories in report["summary"].items():
        for category, values in categories.items():
            if not values["started_pairs"]:
                continue
            n = values["valid_pairs"]
            label = model.rsplit("/", 1)[-1].removeprefix("claude-")
            primary.add_row(label, category, str(n), str(values["excluded_pairs"]),
                            f"{values['baseline_rate']:.1%}" if n else "—",
                            f"{values['skill_rate']:.1%}" if n else "—",
                            f"{values['uplift_percentage_points']:+.1f}" if n else "—")
            exposure = Table(title="Skill exposure and loading (valid pairs only)")
            for title in ("Arm", "Index entry", "Body read", "Body in request", "Ref reads", "Request captured"):
                exposure.add_column(title, overflow="fold")
            execution = Table(title="ILSpy execution (valid pairs only; counts are trials)")
            for title in ("Arm", "Attempt", "Any DLL", "Target DLL", "Without body", "After body", "Order unknown"):
                execution.add_column(title, overflow="fold")
            for condition, label in (("baseline", "Without"), ("skill", "With")):
                d = values["diagnostics"][condition]
                exposure_sources.update(d["index_evidence"])
                known = n - d["index_unknown"]
                body_known = n - d["body_load_unknown"]
                body_request_known = n - d["body_in_model_request_unknown"]
                exposure.add_row(label,
                                 f"{d['index_present']}/{known} known", f"{d['body_loaded']}/{body_known} known",
                                 f"{d['body_in_model_request']}/{body_request_known} known",
                                 str(d["reference_reads"]), str(d["index_evidence"].get("captured_request", 0)))
                execution.add_row(label,
                                  *(str(d[key]) for key in ("attempted", "any_decompilation", "target_decompilation",
                                                           "target_without_body_load", "target_after_body_load",
                                                           "target_load_order_unknown")))
            details.append((model, category, exposure, execution))
        for condition, label in (("baseline", "Without"), ("skill", "With")):
            saved = [t for t in report["trials"] if t["model"] == model and t["condition"] == condition]
            statuses = {}
            for values in categories.values():
                for status, count in values["saved_trials"][condition]["statuses"].items():
                    statuses[status] = statuses.get(status, 0) + count
            limited = sum(values["saved_trials"][condition]["budget_limited"] for values in categories.values())
            name = model.rsplit("/", 1)[-1].removeprefix("claude-")
            stopping.add_row(name, label, str(len(saved)), str(statuses.get("completed", 0)), str(limited),
                             str(statuses.get("error", 0)), ", ".join(f"{k}: {v}" for k, v in sorted(statuses.items())))
    console.print(f"Run status: {report['status']}", markup=False)
    if "schedule" in report:
        console.print(f"Saved trials: {len(report['trials'])}/{2 * len(report['schedule'])} planned", markup=False)
    console.print(primary)
    for model, category, exposure, execution in details:
        console.print(f"{model} / {category}", markup=False)
        console.print(exposure)
        console.print(execution)
    console.print(stopping)
    if "reconstructed_from_condition" in exposure_sources:
        console.print("Historical index exposure is reconstructed from condition and snapshot provenance; "
                      "the original request schemas were not captured.")
    console.print("Without/after body refer to the first model request containing the instructions, "
                  "not the cause of ILSpy use. "
                  "A trial can appear in both columns if it used ILSpy before and after loading the body.")
