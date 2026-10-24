"""Execution-based scoring and paired activation uplift, split from controls."""

from __future__ import annotations

from collections import Counter
import math


VALID_STATUSES = {"completed", "step_limit", "token_limit", "time_limit", "output_limit"}
BUDGET_STATUSES = {"step_limit", "token_limit", "time_limit", "output_limit"}


def successful_decompilations(events: list[dict]) -> list[dict]:
    return [e for e in events if e.get("phase") == "finished"
            and e.get("decompilation_requested") and e.get("returncode") == 0
            and e.get("assemblies") and (e.get("stdout_is_code") or e.get("generated_files"))]


def score_events(events: list[dict], relevant_hashes: set[str]) -> dict:
    attempted = any(e.get("decompilation_requested") for e in events)
    successful = successful_decompilations(events)
    relevant = any(set(e["assemblies"].values()) & relevant_hashes for e in successful)
    return {"attempted": attempted, "any_decompilation": bool(successful), "activated": relevant}


def summarize_diagnostics(rows: list[dict]) -> dict:
    """Counts use the same valid matched trials as the primary endpoint."""
    diagnostics = [r.get("skill_diagnostics", {}) for r in rows]
    return {"trials": len(rows),
            "index_present": sum(d.get("target_index_present") is True for d in diagnostics),
            "index_unknown": sum(d.get("target_index_present") is None for d in diagnostics),
            "index_evidence": {source: sum(d.get("index_evidence", "unavailable") == source for d in diagnostics)
                               for source in sorted({d.get("index_evidence", "unavailable") for d in diagnostics})},
            "body_loaded": sum(d.get("target_body_loaded") is True for d in diagnostics),
            "body_load_unknown": sum("target_body_loaded" not in d for d in diagnostics),
            "body_in_model_request": sum(d.get("target_body_in_model_request") is True for d in diagnostics),
            "body_in_model_request_unknown": sum(d.get("target_body_in_model_request") is None for d in diagnostics),
            "reference_reads": sum(len(d.get("target_reference_reads", [])) for d in diagnostics),
            "attempted": sum(r["attempted"] for r in rows),
            "any_decompilation": sum(r["any_decompilation"] for r in rows),
            "target_decompilation": sum(r["activated"] for r in rows),
            "target_without_body_load": sum(d.get("target_execution_without_body_load") is True for d in diagnostics),
            "target_after_body_load": sum(d.get("target_execution_after_body_load") is True for d in diagnostics),
            "target_load_order_unknown": sum(r["activated"] and d.get("target_execution_without_body_load") is None
                                             for r, d in zip(rows, diagnostics))}


def summarize(trials: list[dict]) -> dict:
    """Only matched pairs without provider/infrastructure errors enter rates.

    Budget exhaustion is an observed outcome within the assigned budget. An API
    failure is missing evidence and excludes both arms of that pair.
    """
    groups = {}
    for model in sorted({t["model"] for t in trials}):
        groups[model] = {}
        for category in ("dependency", "repository_only"):
            rows = [t for t in trials if t["model"] == model and t["category"] == category]
            pairs = {}
            for row in rows:
                pairs.setdefault(row["pair_id"], {})[row["condition"]] = row
            valid = [p for p in pairs.values() if set(p) == {"baseline", "skill"}
                     and all(t["status"] in VALID_STATUSES for t in p.values())]
            endpoint = "activated" if category == "dependency" else "any_decompilation"
            n = len(valid)
            b = sum(p["baseline"][endpoint] for p in valid)
            s = sum(p["skill"][endpoint] for p in valid)
            differences = [int(p["skill"][endpoint]) - int(p["baseline"][endpoint]) for p in valid]
            delta = sum(differences) / n if n else None
            # Paired standard error: descriptive only, repeated cases are not
            # independent projects. Do not present a CI for a one-pair smoke run.
            se = (math.sqrt(sum((d - delta) ** 2 for d in differences) / (n * (n - 1)))
                  if n > 1 else None)
            groups[model][category] = {
                "endpoint": endpoint, "started_pairs": len(pairs), "valid_pairs": n,
                "excluded_pairs": len(pairs) - n,
                "baseline_activations": b, "skill_activations": s,
                "baseline_rate": b / n if n else None, "skill_rate": s / n if n else None,
                "uplift_percentage_points": delta * 100 if n else None,
                "paired_standard_error_pp": se * 100 if se is not None else None,
                "skill_only_pairs": sum(d == 1 for d in differences),
                "baseline_only_pairs": sum(d == -1 for d in differences),
                "statuses": dict(Counter(t["status"] for t in rows)),
                "skill_loaded": sum("ilspy-decompile" in p["skill"]["loaded_skills"] for p in valid),
                "baseline_attempts": sum(p["baseline"]["attempted"] for p in valid),
                "skill_attempts": sum(p["skill"]["attempted"] for p in valid),
                "diagnostics": {condition: summarize_diagnostics([p[condition] for p in valid])
                                for condition in ("baseline", "skill")},
                "saved_trials": {condition: {
                    "trials": sum(t["condition"] == condition for t in rows),
                    "statuses": dict(Counter(t["status"] for t in rows if t["condition"] == condition)),
                    "budget_limited": sum(t["status"] in BUDGET_STATUSES for t in rows
                                          if t["condition"] == condition),
                } for condition in ("baseline", "skill")},
            }
    return groups
