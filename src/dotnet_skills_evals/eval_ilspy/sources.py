"""SourceLink and embedded-source retrieval with PDB and document validation."""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path
import tempfile
import urllib.parse

from .retrieval import HttpClient, RetrievalError


SYMBOL_SERVERS = ("https://symbols.nuget.org/download/symbols", "https://msdl.microsoft.com/download/symbols")
HASH_ALGORITHMS = {"ff1816ec-aa5e-4d10-87f7-6f4963833460": "sha1",
                   "8829d00f-11b8-4213-878b-770e8597ac16": "sha256"}


def mapped_url(name: str, mappings: dict[str, str]) -> str | None:
    name = name.replace("\\", "/")
    for pattern, url in sorted(mappings.items(), key=lambda item: -len(item[0])):
        pattern = pattern.replace("\\", "/")
        if pattern.count("*") > 1 or ("*" in pattern and not pattern.endswith("*")):
            raise RetrievalError("Unsupported SourceLink document mapping")
        if "*" in pattern:
            if url.count("*") != 1:
                raise RetrievalError("Invalid SourceLink wildcard URL")
            prefix = pattern[:-1]
            if name.casefold().startswith(prefix.casefold()):
                return url.replace("*", urllib.parse.quote(name[len(prefix):], safe="/"))
        elif name.casefold() == pattern.casefold():
            if "*" in url:
                raise RetrievalError("Invalid SourceLink URL")
            return url
    return None


class SourceLinkClient:
    def __init__(self, http: HttpClient, sandbox, symbol_servers: tuple[str, ...] = SYMBOL_SERVERS):
        self.http = http
        self.sandbox = sandbox
        self.symbol_servers = symbol_servers
        self.pdbs: dict[str, str] = {}

    def inspect(self, assembly: str, document: str | None = None, offset: int = 0) -> dict:
        result = self.sandbox.inspect_sources(assembly, self.pdbs.get(assembly), document, offset)
        failures = []
        if not result["pdbFound"]:
            headers = {"SymbolChecksumValidationSupported": "1"}
            checksums = result.get("pdbChecksums", {})
            if checksums:
                headers["SymbolChecksum"] = ";".join(f"{kind}:{value}" for kind, value in checksums.items())
            for key in result["symbolKeys"]:
                for server in self.symbol_servers:
                    url = server.rstrip("/") + "/" + urllib.parse.quote(key, safe="/")
                    try:
                        response = self.http.get(url, headers=headers, max_bytes=32 * 1024 * 1024)
                        with tempfile.TemporaryDirectory() as directory:
                            path = Path(directory) / "symbols.pdb"
                            path.write_bytes(response.body)
                            remote = self.sandbox.put_file(path)
                        result = self.sandbox.inspect_sources(assembly, remote, document, offset)
                        if not result["pdbFound"]:
                            raise RetrievalError("Downloaded PDB did not resolve")
                        self.pdbs[assembly] = remote
                        result["symbol_url"] = response.url
                        result["pdb_sha256"] = response.sha256
                        break
                    except (RetrievalError, ValueError) as exc:
                        failures.append({"url": url, "error": str(exc)})
                if result["pdbFound"]:
                    break
        result["symbol_lookup_failures"] = failures
        for doc in result["documents"]:
            doc["url"] = mapped_url(doc["name"], result["mappings"])
        return result

    def documents(self, assembly: str, offset: int = 0) -> dict:
        if not isinstance(offset, int) or offset < 0:
            raise RetrievalError("offset must be a non-negative integer")
        result = self.inspect(assembly, offset=offset)
        result.pop("embeddedSource", None)
        return result

    def read(self, assembly: str, document: str) -> dict:
        result = self.inspect(assembly, document)
        if not result["documents"]:
            raise RetrievalError("Document not found in matching debug symbols")
        doc = result["documents"][0]
        if result.get("embeddedSource") is not None:
            content = base64.b64decode(result["embeddedSource"], validate=True)
            origin = "embedded"
        elif doc["url"]:
            response = self.http.get(doc["url"], max_bytes=4 * 1024 * 1024)
            content = response.body
            origin = response.url
        else:
            raise RetrievalError("Document has neither embedded source nor a SourceLink mapping")
        algorithm = HASH_ALGORITHMS.get(doc["hashAlgorithm"])
        if not algorithm or not doc["checksum"]:
            raise RetrievalError("Cannot validate the source document checksum")
        if hashlib.new(algorithm, content).hexdigest() != doc["checksum"]:
            raise RetrievalError("Source content does not match the PDB document checksum")
        text = content.decode("utf-8-sig", errors="replace")
        return {"assembly": assembly, "document": document, "origin": origin,
                "checksum_verified": True, "sha256": hashlib.sha256(content).hexdigest(),
                "content": text[:24000], "truncated": len(text) > 24000}
