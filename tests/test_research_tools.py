import hashlib
import io
import json
import socket
from types import SimpleNamespace
from pathlib import Path
import tarfile
import urllib.parse

import litellm
import pytest

from dotnet_skills_evals.eval_ilspy.research import ResearchConfig, ResearchTools, WEB_SEARCH_TOOL
from dotnet_skills_evals.eval_ilspy.retrieval import GitHubClient, HttpClient, RetrievalError, extract_snapshot, fetch_url
from dotnet_skills_evals.eval_ilspy.sources import mapped_url
from dotnet_skills_evals.eval_ilspy import sandbox as sandbox_module


def archive_bytes(name="root/src/Example.cs", content=b"public class Example {}", kind=None):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as archive:
        info = tarfile.TarInfo(name)
        if kind:
            info.type = kind
            info.linkname = "/etc/passwd"
        else:
            info.size = len(content)
        archive.addfile(info, None if kind else io.BytesIO(content))
    return stream.getvalue()


def test_fetch_reads_real_http_and_caches_exact_response(tmp_path, serve_http):
    server = serve_http({"/page": (200, {"Content-Type": "text/html"},
                                   "<p>API behavior</p><script>hidden()</script><pre>return value;</pre>")})
    http = HttpClient(tmp_path, allow_loopback=True)
    first = fetch_url(http, server.url + "/page")
    second = fetch_url(http, server.url + "/page")
    assert "API behavior" in first["content"]
    assert "return value;" in first["content"]
    assert "hidden" not in first["content"]
    assert first == second
    assert len(server.requests) == 1
    assert len(list(tmp_path.glob("*.bin"))) == 1


def test_fetch_failure_is_reported_not_empty_results(tmp_path, serve_http):
    server = serve_http({})
    with pytest.raises(RetrievalError, match="HTTP 404"):
        fetch_url(HttpClient(tmp_path, allow_loopback=True), server.url + "/missing")


def test_size_limits_and_binary_pages(tmp_path, serve_http):
    server = serve_http({"/large": (200, {}, b"x" * 100), "/dll": (200, {}, b"binary")})
    http = HttpClient(tmp_path, allow_loopback=True)
    with pytest.raises(RetrievalError, match="exceeds"):
        http.get(server.url + "/large", max_bytes=10)
    with pytest.raises(RetrievalError, match="binary"):
        fetch_url(http, server.url + "/dll")


@pytest.mark.parametrize("url", ["file:///etc/passwd", "http://127.0.0.1/", "http://169.254.169.254/", "https://user:secret@example.com/"])
def test_model_cannot_fetch_host_files_or_private_addresses(tmp_path, url):
    with pytest.raises(RetrievalError):
        HttpClient(tmp_path).get(url)


def test_dns_rebinding_cannot_reach_a_local_http_service(tmp_path, serve_http, monkeypatch):
    server = serve_http({"/private": (200, {"Content-Type": "text/plain"}, "host secret")})
    port = urllib.parse.urlsplit(server.url).port
    lookups = []

    def alternating_dns(host, requested_port, **kwargs):
        lookups.append(host)
        address = "8.8.8.8" if len(lookups) == 1 else "127.0.0.1"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, requested_port))]

    monkeypatch.setattr(socket, "getaddrinfo", alternating_dns)
    with pytest.raises(RetrievalError, match="public internet addresses"):
        HttpClient(tmp_path).get(f"http://rebind.example:{port}/private")
    assert len(lookups) == 2
    assert not server.requests


def test_research_config_never_formats_token():
    assert "private-token" not in repr(ResearchConfig("private-token"))
    assert "private-token" not in json.dumps(ResearchConfig("private-token").provenance())


@pytest.mark.parametrize("tree", [False, True])
def test_upload_streams_archive_to_unprivileged_tmpfs_process(tmp_path, monkeypatch, tree):
    source = tmp_path / "source.cs"
    source.write_text("class Source {}")
    (tmp_path / "other.txt").write_text("other")
    commands, members = [], {}
    monkeypatch.setattr(sandbox_module, "docker", lambda *args: commands.append(list(args)))

    def transfer(args, **kwargs):
        commands.append(args)
        with tarfile.open(fileobj=kwargs["stdin"], mode="r:") as archive:
            for member in archive:
                if member.isfile():
                    members[member.name.removeprefix("./")] = archive.extractfile(member).read()
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(sandbox_module.subprocess, "run", transfer)
    sandbox = sandbox_module.DockerSandbox("image")
    destination = sandbox.put_tree(tmp_path) if tree else sandbox.put_file(source)
    assert destination.startswith("/tmp/research-")
    assert members["source.cs"] == b"class Source {}"
    assert ("other.txt" in members) is tree
    assert commands[1][:4] == ["docker", "exec", "-i", sandbox.name]
    assert "tar" in commands[1]
    assert "--no-same-owner" in commands[1]
    assert "cp" not in commands[1]


def test_redirect_does_not_forward_github_token(tmp_path, serve_http):
    target = serve_http({"/download": (200, {}, b"archive")})
    origin = serve_http({"/start": (302, {"Location": target.url + "/download"}, b"")})
    http = HttpClient(tmp_path, allow_loopback=True)
    http.get(origin.url + "/start", headers={"Authorization": "Bearer test-secret"})
    assert origin.requests[0]["headers"]["Authorization"] == "Bearer test-secret"
    assert "Authorization" not in target.requests[0]["headers"]
    assert all("test-secret" not in p.read_text() for p in tmp_path.glob("*.json"))


def test_github_code_search_executes_query_and_retains_matches(tmp_path, serve_http):
    query = urllib.parse.urlencode({"q": "PeriodicBatchingSink repo:owner/repo", "per_page": 5})
    server = serve_http({"/repos/owner/repo": (200, {}, {"private": False}),
        "/search/code?" + query: (200, {}, {"total_count": 1, "items": [{
        "path": "src/Sink.cs", "repository": {"full_name": "owner/repo", "private": False},
        "html_url": "https://github.com/owner/repo/blob/main/src/Sink.cs",
        "text_matches": [{"fragment": "class PeriodicBatchingSink"}]}]})})
    github = GitHubClient(HttpClient(tmp_path, allow_loopback=True), "test-token", server.url)
    result = github.search("PeriodicBatchingSink repo:owner/repo")
    assert result["results"][0]["matches"] == ["class PeriodicBatchingSink"]
    assert server.requests[0]["headers"]["Authorization"] == "Bearer test-token"
    assert "default branch" in result["note"]


def test_code_search_requires_auth_and_private_results_are_rejected(tmp_path, serve_http):
    http = HttpClient(tmp_path, allow_loopback=True)
    with pytest.raises(RetrievalError, match="requires"):
        GitHubClient(http).search("query")
    server = serve_http({"/repos/owner/private": (200, {}, {"private": True})})
    with pytest.raises(RetrievalError, match="public"):
        GitHubClient(http, "test", server.url).revision("owner/private", "main")
    with pytest.raises(RetrievalError, match="public"):
        GitHubClient(http, "test", server.url).search("repo:owner/private secret")
    assert not any(r["path"].startswith("/search/") for r in server.requests)


@pytest.mark.parametrize("query", ["PeriodicBatchingSink", "-repo:owner/public secret",
    '"repo:owner/public" secret', '"literal repo:owner/public text" secret',
    "repo:owner/public safe OR secret", "org:owner secret repo:owner/public"])
def test_code_search_explains_required_public_repository_scope(tmp_path, query):
    with pytest.raises(RetrievalError, match="kind=repositories"):
        GitHubClient(HttpClient(tmp_path), "test").search(query)


def test_code_search_rejects_unclosed_quotes_before_any_request(tmp_path):
    with pytest.raises(ValueError, match="quotation"):
        GitHubClient(HttpClient(tmp_path), "test").search('literal" repo:owner/public secret')


def test_checkout_resolves_tag_to_commit_and_extracts_source(tmp_path, serve_http):
    sha = "a" * 40
    server = serve_http({
        "/repos/owner/repo": (200, {}, {"private": False}),
        "/repos/owner/repo/commits/v1.0": (200, {}, {"sha": sha}),
        f"/repos/owner/repo/tarball/{sha}": (200, {}, archive_bytes()),
    })
    client = GitHubClient(HttpClient(tmp_path / "cache", allow_loopback=True), api_base=server.url)
    result = client.checkout("owner/repo", "v1.0", tmp_path / "checkout")
    assert result["commit"] == sha
    assert result["files"] == 1
    assert (tmp_path / "checkout/src/Example.cs").read_text() == "public class Example {}"


@pytest.mark.parametrize("name,kind", [("root/../../escape", None), ("/absolute", None),
                                       ("root/link", tarfile.SYMTYPE), ("root/link", tarfile.LNKTYPE)])
def test_snapshot_cannot_escape_or_create_links(tmp_path, name, kind):
    with pytest.raises(RetrievalError):
        extract_snapshot(archive_bytes(name, kind=kind), tmp_path / "checkout")


def test_source_mapping_supports_windows_paths_longest_prefix_and_encoding():
    mappings = {"C:\\src\\*": "https://example.com/general/*",
                "C:\\src\\lib\\*": "https://example.com/commit/*"}
    assert mapped_url("c:/SRC/lib/A B.cs", mappings) == "https://example.com/commit/A%20B.cs"
    assert mapped_url("elsewhere.cs", mappings) is None


def test_tool_failures_are_recorded_as_failures(tmp_path, serve_http):
    server = serve_http({})
    tools = ResearchTools(HttpClient(tmp_path, allow_loopback=True), object(), ResearchConfig())
    result = tools.invoke("fetch_url", {"url": server.url + "/missing"})
    assert "HTTP 404" in result["error"]
    assert tools.events[0]["result"] == result


@pytest.mark.parametrize("usage_field", ["server_tool_use_details", "server_tool_use"])
def test_openrouter_server_search_survives_litellm_wire_translation(serve_http, usage_field):
    captured = []

    def complete(request):
        captured.append(json.loads(request["body"]))
        return 200, {}, {"id": "mock-response", "object": "chat.completion", "created": 1,
            "model": "anthropic/claude-haiku-5.5", "choices": [{"index": 0, "finish_reason": "stop",
            "message": {"role": "assistant", "content": "Found source", "annotations": [{"type": "url_citation",
            "url_citation": {"url": "https://github.com/example/repo", "title": "Source", "start_index": 0, "end_index": 5}}]}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15,
                      usage_field: {"web_search_requests": 1}}}

    server = serve_http({"/chat/completions": complete})
    result = litellm.completion(model="openrouter/anthropic/claude-haiku-5.5",
        messages=[{"role": "user", "content": "Find source"}], tools=[WEB_SEARCH_TOOL],
        api_key="dummy-local-test-key", api_base=server.url, num_retries=0, caching=False)
    assert captured[0]["tools"] == [WEB_SEARCH_TOOL]
    assert result.usage.model_dump()[usage_field]["web_search_requests"] == 1
    assert result.choices[0].message.model_dump()["annotations"][0]["url_citation"]["url"].startswith("https://github.com/")
