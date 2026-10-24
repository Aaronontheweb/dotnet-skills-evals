"""Observed skill exposure and reads, separate from execution and causal claims."""

from __future__ import annotations

import hashlib
import json

from .metrics import successful_decompilations


TARGET_SKILL = "ilspy-decompile"


def json_sha256(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def successful_skill_reads(messages: list[dict]) -> list[dict]:
    """A call is a read only when its matching tool result contains guidance."""
    pending = {}
    reads = []
    for index, message in enumerate(messages):
        if message.get("role") == "assistant":
            for call in message.get("tool_calls") or []:
                function = call.get("function", {})
                if function.get("name") != "invoke_skill":
                    continue
                try:
                    args = json.loads(function["arguments"])
                except (KeyError, TypeError, ValueError):
                    continue
                if isinstance(args, dict) and isinstance(args.get("skill_name"), str):
                    pending[call["id"]] = args
        elif message.get("role") == "tool" and message.get("tool_call_id") in pending:
            args = pending.pop(message["tool_call_id"])
            try:
                result = json.loads(message["content"])
            except (KeyError, TypeError, ValueError):
                continue
            if isinstance(result, dict) and isinstance(result.get("content"), str) and "error" not in result:
                reads.append({"skill_name": args["skill_name"],
                              "reference": args.get("reference", "SKILL.md"),
                              "tool_call_id": message["tool_call_id"], "message_index": index})
    return reads


def trial_diagnostics(trial: dict, artifact: dict, relevant_hashes: set[str],
                      *, reconstruct_index: bool = False) -> dict:
    context = artifact.get("request_context")
    if context is not None and artifact.get("requests"):
        descriptions = [tool.get("function", {}).get("description", "")
                        for tool in context["tools"]
                        if tool.get("function", {}).get("name") == "invoke_skill"]
        index_present = any(any(line.startswith(f"- {TARGET_SKILL}:")
                                for line in description.splitlines()) for description in descriptions)
        index_evidence = "captured_request"
    elif context is not None:
        index_present, index_evidence = None, "no_model_request"
    elif reconstruct_index and trial.get("condition") in {"baseline", "skill"}:
        index_present = trial["condition"] == "skill"
        index_evidence = "reconstructed_from_condition"
    else:
        index_present, index_evidence = None, "unavailable"

    reads = successful_skill_reads(artifact["messages"])
    # New artifacts add wall-clock timestamps at successful delivery. Historical
    # transcripts establish which files were read, but not their delivery times.
    timestamps = {r["tool_call_id"]: r["loaded_at"] for r in artifact.get("skill_reads", [])}
    for read in reads:
        if read["tool_call_id"] in timestamps:
            read["loaded_at"] = timestamps[read["tool_call_id"]]
    body_reads = [r for r in reads if r["skill_name"] == TARGET_SKILL and r["reference"] == "SKILL.md"]
    # Tool results from one response are only supplied to the model on a later
    # request. A sibling shell call in that same tool batch has not seen them.
    body_requests = [request for request in artifact.get("requests", [])
                     if any(r["message_index"] < request["message_count"] for r in body_reads)]
    body_in_request = bool(body_requests) if context is not None else (None if body_reads else False)
    target_events = [e for e in successful_decompilations(artifact["ilspy_events"])
                     if set(e["assemblies"].values()) & relevant_hashes]
    without_body = after_body = False
    if target_events:
        if not body_reads or body_in_request is False:
            without_body = True
        elif body_requests and all("started_at" in r for r in body_requests) and all("started_at" in e for e in target_events):
            first_request = min(r["started_at"] for r in body_requests)
            without_body = any(e["started_at"] < first_request for e in target_events)
            after_body = any(e["started_at"] >= first_request for e in target_events)
        else:
            without_body = after_body = None
    return {"target_index_present": index_present, "index_evidence": index_evidence,
            "request_captured": bool(context is not None and artifact.get("requests")),
            "skill_reads": reads, "target_body_loaded": bool(body_reads),
            "target_body_in_model_request": body_in_request,
            "target_reference_reads": [r["reference"] for r in reads
                                       if r["skill_name"] == TARGET_SKILL and r["reference"] != "SKILL.md"],
            "target_execution_without_body_load": without_body,
            "target_execution_after_body_load": after_body}
