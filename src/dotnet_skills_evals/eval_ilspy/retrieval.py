"""Public HTTP retrieval and GitHub discovery, with auditable response caching."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import io
import ipaddress
import json
from pathlib import Path, PurePosixPath
import re
import socket
import tarfile
import urllib.error
import urllib.parse
import urllib.request


class RetrievalError(ValueError):
    """An unavailable or invalid research request the model can recover from."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True)
class Retrieved:
    url: str
    body: bytes
    content_type: str
    retrieved_at: str
    sha256: str


class HttpClient:
    def __init__(self, cache_dir: Path, *, allow_loopback: bool = False):
        self.cache_dir = cache_dir
        self.allow_loopback = allow_loopback
        self.cache: dict[str, Retrieved] = {}
        self.opener = urllib.request.build_opener(NoRedirect)

    def validate_url(self, url: str) -> None:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password:
            raise RetrievalError("Use an HTTP(S) URL without embedded credentials")
        try:
            addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
        except OSError as exc:
            raise RetrievalError(f"Cannot resolve {parsed.hostname}") from exc
        for address in addresses:
            ip = ipaddress.ip_address(address[4][0])
            if not ip.is_global and not (self.allow_loopback and ip.is_loopback):
                raise RetrievalError("Research tools only retrieve public internet addresses")

    def get(self, url: str, *, headers: dict | None = None, max_bytes: int = 8 * 1024 * 1024) -> Retrieved:
        headers = {"User-Agent": "dotnet-skills-evals/0.1", "Accept-Encoding": "identity", **(headers or {})}
        # Keep authenticated and anonymous cache entries distinct without saving credentials.
        key = hashlib.sha256(json.dumps([url, headers], sort_keys=True).encode()).hexdigest()
        if key in self.cache:
            cached = self.cache[key]
            if len(cached.body) > max_bytes:
                raise RetrievalError("Cached response exceeds this tool's size limit")
            return cached
        original_url = url
        for _ in range(6):
            self.validate_url(url)
            request = urllib.request.Request(url, headers=headers)
            try:
                response = self.opener.open(request, timeout=30)
            except urllib.error.HTTPError as exc:
                if exc.code in {301, 302, 303, 307, 308} and exc.headers.get("Location"):
                    next_url = urllib.parse.urljoin(url, exc.headers["Location"])
                    if urllib.parse.urlsplit(url).netloc != urllib.parse.urlsplit(next_url).netloc:
                        headers = {k: v for k, v in headers.items() if k.lower() not in {"authorization", "cookie"}}
                    url = next_url
                    exc.close()
                    continue
                exc.close()
                raise RetrievalError(f"HTTP {exc.code} retrieving {url}") from exc
            except (OSError, urllib.error.URLError) as exc:
                raise RetrievalError(f"Could not retrieve {url}: {exc.reason if isinstance(exc, urllib.error.URLError) else type(exc).__name__}") from exc
            with response:
                body = response.read(max_bytes + 1)
                if len(body) > max_bytes:
                    raise RetrievalError(f"Response exceeds {max_bytes} bytes")
                content_type = response.headers.get("Content-Type", "application/octet-stream")
            result = Retrieved(url, body, content_type, datetime.now(timezone.utc).isoformat(),
                               hashlib.sha256(body).hexdigest())
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            (self.cache_dir / f"{key}.bin").write_bytes(body)
            (self.cache_dir / f"{key}.json").write_text(json.dumps({
                "requested_url": original_url, "url": url, "content_type": content_type,
                "retrieved_at": result.retrieved_at, "sha256": result.sha256,
            }, indent=2), encoding="utf-8")
            self.cache[key] = result
            return result
        raise RetrievalError("Too many HTTP redirects")


class ReadableHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hidden = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript"}:
            self.hidden += 1
        elif tag in {"p", "div", "br", "pre", "li", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"}:
            self.hidden = max(0, self.hidden - 1)
        elif tag in {"p", "div", "pre", "li"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def fetch_url(client: HttpClient, url: str) -> dict:
    response = client.get(url)
    text = response.body.decode("utf-8", errors="replace")
    if "html" in response.content_type:
        parser = ReadableHTML()
        parser.feed(text)
        text = "".join(parser.parts)
    if not (response.content_type.startswith("text/") or any(
            t in response.content_type for t in ("html", "json", "xml", "javascript"))):
        raise RetrievalError("This URL is binary; use repository checkout or SourceLink for binary artifacts")
    return {"url": response.url, "content": text[:24000], "truncated": len(text) > 24000,
            "sha256": response.sha256, "retrieved_at": response.retrieved_at}


class GitHubClient:
    def __init__(self, http: HttpClient, token: str = "", api_base: str = "https://api.github.com"):
        self.http = http
        self.token = token
        self.api_base = api_base.rstrip("/")

    def get(self, path: str) -> Retrieved:
        headers = {"Accept": "application/vnd.github.text-match+json", "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return self.http.get(self.api_base + path, headers=headers, max_bytes=32 * 1024 * 1024)

    def search(self, query: str, kind: str = "code") -> dict:
        if kind not in {"code", "issues", "repositories"}:
            raise RetrievalError("kind must be code, issues, or repositories")
        if kind == "code" and not self.token:
            raise RetrievalError("GitHub code search requires GITHUB_TOKEN or GH_TOKEN")
        params = urllib.parse.urlencode({"q": query + " is:public", "per_page": 5})
        response = self.get(f"/search/{kind}?{params}")
        data = json.loads(response.body)
        items = []
        for item in data["items"]:
            repo = item.get("repository", item if kind == "repositories" else {})
            if repo.get("private"):
                raise RetrievalError("Only public repositories are available in this eval")
            items.append({"title": item.get("title", item.get("name")), "path": item.get("path"),
                          "repository": repo.get("full_name"), "url": item.get("html_url"),
                          "snippet": (item.get("body") or item.get("description") or "")[:2000],
                          "matches": [m.get("fragment", "")[:2000] for m in item.get("text_matches", [])]})
        return {"results": items, "total_count": data["total_count"],
                "incomplete_results": data.get("incomplete_results", False),
                "note": "GitHub code search indexes the default branch. Check out the matching revision to inspect older code.",
                "url": response.url, "sha256": response.sha256}

    def revision(self, repository: str, ref: str) -> str:
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository) or any(p in {".", ".."} for p in repository.split("/")):
            raise RetrievalError("repository must be owner/name")
        if not ref or len(ref) > 200:
            raise RetrievalError("A tag, branch, or commit ref is required")
        metadata = json.loads(self.get(f"/repos/{repository}").body)
        if metadata.get("private", True):
            raise RetrievalError("Only public repositories are available in this eval")
        data = json.loads(self.get(f"/repos/{repository}/commits/{urllib.parse.quote(ref, safe='')}").body)
        sha = data["sha"]
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise RetrievalError("GitHub returned an invalid commit identity")
        return sha

    def checkout(self, repository: str, ref: str, destination: Path) -> dict:
        sha = self.revision(repository, ref)
        response = self.get(f"/repos/{repository}/tarball/{sha}")
        files = extract_snapshot(response.body, destination)
        return {"repository": repository, "requested_ref": ref, "commit": sha,
                "url": response.url, "archive_sha256": response.sha256, "files": files}


def extract_snapshot(body: bytes, destination: Path) -> int:
    """Extract regular files from a GitHub archive, rejecting traversal and links."""
    total = count = 0
    with tarfile.open(fileobj=io.BytesIO(body), mode="r:gz") as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or "\\" in member.name:
                raise RetrievalError("Unsafe repository archive path")
            if member.issym() or member.islnk() or not (member.isfile() or member.isdir()):
                raise RetrievalError("Repository archive contains unsupported links or special files")
            if len(path.parts) < 2 or member.isdir():
                continue
            total += member.size
            count += 1
            if member.size > 8 * 1024 * 1024 or total > 128 * 1024 * 1024 or count > 20000:
                raise RetrievalError("Repository snapshot exceeds extraction limits")
            target = destination.joinpath(*path.parts[1:])
            target.parent.mkdir(parents=True, exist_ok=True)
            stream = archive.extractfile(member)
            if stream is None:
                raise RetrievalError("Archive file cannot be read")
            with stream:
                target.write_bytes(stream.read())
    return count
