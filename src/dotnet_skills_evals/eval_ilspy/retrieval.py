"""Public HTTP retrieval and GitHub discovery, with auditable response caching."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import http.client
from html.parser import HTMLParser
import io
import ipaddress
import json
from pathlib import Path, PurePosixPath
import re
import shlex
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


def public_addresses(host: str, port: int, allow_loopback: bool) -> list:
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise RetrievalError(f"Cannot resolve {host}") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global and not (allow_loopback and ip.is_loopback):
            raise RetrievalError("Research tools only retrieve public internet addresses")
    return addresses


def connect_public(host: str, port: int, timeout: float, allow_loopback: bool) -> socket.socket:
    # Connect to the checked numeric sockaddr. A second hostname resolution at
    # connect time would allow DNS rebinding to host-local services.
    addresses = public_addresses(host, port, allow_loopback)
    last_error = None
    for family, kind, protocol, _, address in addresses:
        connection = socket.socket(family, kind, protocol)
        try:
            connection.settimeout(timeout)
            connection.connect(address)
            return connection
        except OSError as error:
            connection.close()
            last_error = error
    raise OSError("Cannot connect to a validated public address") from last_error


class PublicHTTPConnection(http.client.HTTPConnection):
    def __init__(self, *args, allow_loopback=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.allow_loopback = allow_loopback

    def connect(self):
        self.sock = connect_public(self.host, self.port, self.timeout, self.allow_loopback)


class PublicHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args, allow_loopback=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.allow_loopback = allow_loopback

    def connect(self):
        connection = connect_public(self.host, self.port, self.timeout, self.allow_loopback)
        try:
            # Retain hostname verification and SNI while connecting to a checked IP.
            self.sock = self._context.wrap_socket(connection, server_hostname=self.host)
        except Exception:
            connection.close()
            raise


class PublicHTTPHandler(urllib.request.HTTPHandler):
    def __init__(self, allow_loopback):
        super().__init__()
        self.allow_loopback = allow_loopback

    def http_open(self, request):
        return self.do_open(lambda host, **kw: PublicHTTPConnection(
            host, allow_loopback=self.allow_loopback, **kw), request)


class PublicHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, allow_loopback):
        super().__init__()
        self.allow_loopback = allow_loopback

    def https_open(self, request):
        return self.do_open(lambda host, **kw: PublicHTTPSConnection(
            host, allow_loopback=self.allow_loopback, **kw), request, context=self._context)


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
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), NoRedirect,
            PublicHTTPHandler(allow_loopback), PublicHTTPSHandler(allow_loopback))

    def validate_url(self, url: str) -> None:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password:
            raise RetrievalError("Use an HTTP(S) URL without embedded credentials")
        public_addresses(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80), self.allow_loopback)

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
                    origin = urllib.parse.urlsplit(url)
                    target = urllib.parse.urlsplit(next_url)
                    if (origin.scheme, origin.netloc) != (target.scheme, target.netloc):
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
        if kind == "code":
            # REST code search treats is:public as text rather than a visibility
            # qualifier. Validate explicit repo scopes before issuing the search.
            shlex.split(query)  # Reject unmatched quotes, including inside bare terms.
            tokens = shlex.split(query, posix=False)
            repositories = [token[5:] for token in tokens if token.lower().startswith("repo:")]
            if not repositories or re.search(r"\b(?:org|user):|\bOR\b", query, flags=re.IGNORECASE):
                raise RetrievalError("Code search requires repo:owner/name public scopes; use kind=repositories to discover repositories first")
            for repository in set(repositories):
                self.public_repository(repository)
            terms = [token for token in tokens if not token.lower().startswith("repo:")]
            scoped_query = " ".join([*terms, *(f"repo:{repo}" for repo in sorted(set(repositories)))])
        else:
            scoped_query = query + " is:public"
        params = urllib.parse.urlencode({"q": scoped_query, "per_page": 5})
        response = self.get(f"/search/{kind}?{params}")
        data = json.loads(response.body)
        items = []
        for item in data["items"]:
            repo = item.get("repository", item if kind == "repositories" else {})
            if repo.get("private") or (kind == "code" and repo.get("private") is not False):
                raise RetrievalError("Only public repositories are available in this eval")
            items.append({"title": item.get("title", item.get("name")), "path": item.get("path"),
                          "repository": repo.get("full_name"), "url": item.get("html_url"),
                          "snippet": (item.get("body") or item.get("description") or "")[:2000],
                          "matches": [m.get("fragment", "")[:2000] for m in item.get("text_matches", [])]})
        return {"results": items, "total_count": data["total_count"],
                "incomplete_results": data.get("incomplete_results", False),
                "note": "GitHub code search indexes the default branch. Check out the matching revision to inspect older code.",
                "url": response.url, "sha256": response.sha256}

    def public_repository(self, repository: str) -> None:
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository) or any(p in {".", ".."} for p in repository.split("/")):
            raise RetrievalError("repository must be owner/name")
        metadata = json.loads(self.get(f"/repos/{repository}").body)
        if metadata.get("private", True):
            raise RetrievalError("Only public repositories are available in this eval")

    def revision(self, repository: str, ref: str) -> str:
        if not ref or len(ref) > 200:
            raise RetrievalError("A tag, branch, or commit ref is required")
        self.public_repository(repository)
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
            if member.size < 0 or member.size > 8 * 1024 * 1024 or total > 128 * 1024 * 1024 or count > 20000:
                raise RetrievalError("Repository snapshot exceeds extraction limits")
            target = destination.joinpath(*path.parts[1:])
            target.parent.mkdir(parents=True, exist_ok=True)
            stream = archive.extractfile(member)
            if stream is None:
                raise RetrievalError("Archive file cannot be read")
            with stream:
                target.write_bytes(stream.read())
    return count
