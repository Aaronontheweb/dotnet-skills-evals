"""Shared research tool definitions and execution for both experiment arms."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

from .retrieval import GitHubClient, HttpClient, RetrievalError, fetch_url
from .sources import SourceLinkClient


WEB_SEARCH_TOOL = {"type": "openrouter:web_search", "parameters": {
    "engine": "exa", "max_uses": 3, "max_results": 5, "max_characters": 2000}}


def function(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {"name": name, "description": description,
            "parameters": {"type": "object", "properties": properties,
                           "required": required, "additionalProperties": False}}}


RESEARCH_TOOLS = [
    function("fetch_url", "Read a public web page or source URL.", {"url": {"type": "string"}}, ["url"]),
    function("github_search", "Search public GitHub repositories, code, or issues and PRs. Code search covers the default branch.",
             {"query": {"type": "string"}, "kind": {"type": "string", "enum": ["code", "repositories", "issues"]}}, ["query"]),
    function("checkout_repository", "Download a public GitHub repository at a chosen tag, branch, or commit into the container for local inspection.",
             {"repository": {"type": "string", "description": "owner/name"}, "ref": {"type": "string"}}, ["repository", "ref"]),
    function("sourcelink_documents", "List source documents for a local assembly using embedded/adjacent symbols or public symbol servers. Returns SourceLink URLs when available.",
             {"assembly": {"type": "string"}, "offset": {"type": "integer", "minimum": 0}}, ["assembly"]),
    function("read_source", "Read an assembly's original source document using SourceLink or embedded source, validating its PDB checksum.",
             {"assembly": {"type": "string"}, "document": {"type": "string"}}, ["assembly", "document"]),
]
RESEARCH_NAMES = {tool["function"]["name"] for tool in RESEARCH_TOOLS}


def github_token() -> str:
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if token:
        return token
    # Reuse a local GitHub CLI login without putting its token in shell commands
    # or returning it to the model. CI needs no credential for deterministic tests.
    try:
        result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


@dataclass(frozen=True)
class ResearchConfig:
    github_token: str = ""

    def provenance(self) -> dict:
        return {"web_search": WEB_SEARCH_TOOL, "client_tools": sorted(RESEARCH_NAMES),
                "github_authenticated": bool(self.github_token),
                "network_execution": "runner; shell remains offline"}


class ResearchTools:
    def __init__(self, http: HttpClient, sandbox, config: ResearchConfig):
        self.http = http
        self.sandbox = sandbox
        self.github = GitHubClient(http, config.github_token)
        self.sources = SourceLinkClient(http, sandbox)
        self.events: list[dict] = []

    def invoke(self, name: str, args: dict) -> dict:
        started = time.monotonic()
        try:
            if name == "fetch_url":
                result = fetch_url(self.http, args["url"])
            elif name == "github_search":
                result = self.github.search(args["query"], args.get("kind", "code"))
            elif name == "checkout_repository":
                with tempfile.TemporaryDirectory() as directory:
                    result = self.github.checkout(args["repository"], args["ref"], Path(directory))
                    result["directory"] = self.sandbox.put_tree(Path(directory))
            elif name == "sourcelink_documents":
                result = self.sources.documents(args["assembly"], args.get("offset", 0))
            elif name == "read_source":
                result = self.sources.read(args["assembly"], args["document"])
            else:
                raise RetrievalError("Unknown research tool")
        except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as exc:
            result = {"error": str(exc)}
        self.events.append({"tool": name, "arguments": args, "result": result,
                            "elapsed_seconds": time.monotonic() - started})
        return result
