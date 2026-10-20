"""Explicitly opt-in service checks; no model eval is started by these tests."""

import os

import litellm
import pytest

from dotnet_skills_evals.config import OPENROUTER_API_KEY
from dotnet_skills_evals.eval_ilspy.research import ResearchConfig, ResearchTools, RESEARCH_TOOLS, WEB_SEARCH_TOOL, github_token
from dotnet_skills_evals.eval_ilspy.retrieval import HttpClient
from dotnet_skills_evals.eval_ilspy.sandbox import DEFAULT_IMAGE, DockerSandbox


@pytest.mark.openrouter
def test_live_openrouter_server_search():
    assert OPENROUTER_API_KEY, "Configure OPENROUTER_API_KEY for the explicit local API test"
    tool = {**WEB_SEARCH_TOOL, "parameters": {**WEB_SEARCH_TOOL["parameters"], "max_uses": 1, "max_results": 3}}
    try:
        response = litellm.completion(
            model=os.getenv("OPENROUTER_TEST_MODEL", "openrouter/anthropic/claude-haiku-5.5"),
            api_key=OPENROUTER_API_KEY, api_base="https://openrouter.ai/api/v1",
            messages=[{"role": "user", "content": "Use web search to find the official dotnet/sourcelink GitHub repository. Give its URL and cite the search result."}],
            tools=[tool, *RESEARCH_TOOLS], max_tokens=1024, temperature=0, timeout=90, num_retries=0, caching=False,
        )
    except Exception as error:
        pytest.fail(str(error).replace(OPENROUTER_API_KEY, "[REDACTED]"), pytrace=False)
    assert response.usage.model_dump().get("server_tool_use_details", {}).get("web_search_requests", 0) >= 1
    citations = response.choices[0].message.model_dump().get("annotations") or []
    assert any("github.com/dotnet/sourcelink" in c.get("url_citation", {}).get("url", "") for c in citations)


@pytest.mark.network
def test_live_github_search_and_versioned_checkout(tmp_path):
    token = github_token()
    assert token, "Configure a GitHub token or gh login for the explicit public integration test"
    with DockerSandbox(DEFAULT_IMAGE) as sandbox:
        tools = ResearchTools(HttpClient(tmp_path / "cache"), sandbox, ResearchConfig(token))
        search = tools.invoke("github_search", {"query": "repo:serilog/serilog-sinks-periodicbatching PeriodicBatchingSink", "kind": "code"})
        assert "error" not in search, search
        assert search["total_count"] > 0
        repositories = tools.invoke("github_search", {"query": "serilog-sinks-periodicbatching in:name", "kind": "repositories"})
        assert "error" not in repositories, repositories
        assert repositories["total_count"] > 0
        issues = tools.invoke("github_search", {"query": "repo:dotnet/sourcelink is:issue", "kind": "issues"})
        assert "error" not in issues, issues
        assert issues["total_count"] > 0
        checkout = tools.invoke("checkout_repository", {"repository": "serilog/serilog-sinks-periodicbatching", "ref": "v4.0.0"})
        assert "error" not in checkout, checkout
        assert checkout["commit"] == "b3821e5c875531ac2f9ec704d91d5f6bd5b27d12"
        assert sandbox.shell(f"find {checkout['directory']} -name '*.cs'")["stdout"]


@pytest.mark.network
def test_live_sourcelink_published_symbols_and_public_source(tmp_path):
    with DockerSandbox(DEFAULT_IMAGE) as sandbox:
        tools = ResearchTools(HttpClient(tmp_path / "cache"), sandbox, ResearchConfig())
        # Batching 4.0.0 has no published symbols. Serilog 3.1.1 is also restored
        # in the fixture and has a published Portable PDB and SourceLink mapping.
        assembly = "/opt/nuget/serilog/3.1.1/lib/netstandard2.0/Serilog.dll"
        metadata = tools.invoke("sourcelink_documents", {"assembly": assembly})
        assert "error" not in metadata, metadata
        assert metadata["pdbFound"], metadata
        assert metadata["pdbChecksumVerified"] is True
        assert metadata["symbol_url"]
        document = next(d for d in metadata["documents"] if d["name"].endswith("DepthLimiter.cs"))
        source = tools.invoke("read_source", {"assembly": assembly, "document": document["name"]})
        assert "error" not in source, source
        assert source["checksum_verified"] is True
        assert "class DepthLimiter" in source["content"]
        page = tools.invoke("fetch_url", {"url": source["origin"]})
        assert "error" not in page, page
        assert page["sha256"] == source["sha256"]
