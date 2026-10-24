"""Compile real Portable PDBs and exercise symbol/source retrieval over HTTP."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from dotnet_skills_evals.eval_ilspy.retrieval import HttpClient, RetrievalError
from dotnet_skills_evals.eval_ilspy.sources import SourceLinkClient


pytestmark = pytest.mark.source_inspector
ROOT = Path(__file__).resolve().parents[1]


def dotnet(*args):
    result = subprocess.run(["dotnet", *map(str, args)], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    return result


@pytest.fixture(scope="module")
def inspector(tmp_path_factory):
    if not shutil.which("dotnet"):
        pytest.skip("SourceInspector integration tests require the .NET 10 SDK")
    output = tmp_path_factory.mktemp("inspector")
    dotnet("publish", ROOT / "fixtures/ilspy/SourceInspector", "-c", "Release", "-o", output,
           "-p:NuGetAudit=false")
    return output / "SourceInspector.dll"


class LocalSandbox:
    """Run the real metadata helper locally; source and symbols still use HTTP."""

    def __init__(self, helper, scratch):
        self.helper, self.scratch = helper, scratch

    def inspect_sources(self, assembly, pdb=None, document=None, offset=0):
        args = ["dotnet", str(self.helper), str(assembly), "--offset", str(offset)]
        if pdb:
            args += ["--pdb", str(pdb)]
        if document:
            args += ["--document", document]
        result = subprocess.run(args, capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise RetrievalError(result.stderr)
        return json.loads(result.stdout)

    def put_file(self, path):
        self.scratch.mkdir(parents=True, exist_ok=True)
        target = self.scratch / path.name
        shutil.copyfile(path, target)
        return str(target)


@pytest.fixture
def sample(tmp_path, serve_http, inspector):
    routes = {}
    server = serve_http(routes)
    projects = []

    def build(*, embed=False, debug_type="portable", large=False):
        project = tmp_path / f"sample{len(projects)}"
        dotnet("new", "classlib", "--framework", "net10.0", "--name", project.name,
               "--output", project, "--no-restore")
        content = b"namespace Example; public class Behavior { public int Value() => 42; }\n"
        if large:
            content += b"// A repeated source comment for compressed embedded source.\n" * 300
        (project / "Class1.cs").write_bytes(content)
        mapping = project / "source-map.json"
        mapping.write_text(json.dumps({"documents": {str(project) + "/*": server.url + f"/{project.name}/*"}}))
        dotnet("build", project, "-c", "Release", "-p:NuGetAudit=false", f"-p:SourceLink={mapping}",
               f"-p:DebugType={debug_type}", f"-p:EmbedAllSources={str(embed).lower()}")
        output = project / "bin/Release/net10.0"
        routes[f"/{project.name}/Class1.cs"] = (200, {"Content-Type": "text/plain"}, content)
        result = {"assembly": output / f"{project.name}.dll", "pdb": output / f"{project.name}.pdb",
                  "document": str(project / "Class1.cs"), "content": content}
        projects.append(result)
        return result

    sandbox = LocalSandbox(inspector, tmp_path / "downloaded")
    http = HttpClient(tmp_path / "cache", allow_loopback=True)
    return build, sandbox, http, server, routes


def test_sourcelink_fetches_original_source_and_validates_checksum(sample):
    build, sandbox, http, server, _ = sample
    item = build()
    client = SourceLinkClient(http, sandbox)
    metadata = client.documents(str(item["assembly"]))
    document = next(d for d in metadata["documents"] if d["name"] == item["document"])
    assert metadata["pdbFound"] is True
    assert metadata["pdbChecksumVerified"] is True
    assert document["checksum"] == hashlib.sha256(item["content"]).hexdigest()
    assert document["url"].startswith(server.url)
    source = client.read(str(item["assembly"]), item["document"])
    assert source["checksum_verified"] is True
    assert source["content"].encode() == item["content"]
    assert len(server.requests) == 1


def test_changed_source_is_rejected(sample):
    build, sandbox, http, _, routes = sample
    item = build()
    routes["/sample0/Class1.cs"] = (200, {"Content-Type": "text/plain"}, "wrong version")
    with pytest.raises(RetrievalError, match="checksum"):
        SourceLinkClient(http, sandbox).read(str(item["assembly"]), item["document"])


@pytest.mark.parametrize("large,debug_type", [(False, "portable"), (True, "portable"), (True, "embedded")])
def test_embedded_source_needs_no_network_and_is_verified(sample, large, debug_type):
    build, sandbox, http, server, _ = sample
    item = build(embed=True, large=large, debug_type=debug_type)
    result = SourceLinkClient(http, sandbox).read(str(item["assembly"]), item["document"])
    assert result["origin"] == "embedded"
    assert result["checksum_verified"] is True
    assert result["content"].encode() == item["content"]
    assert not server.requests


def test_public_symbol_protocol_downloads_matching_pdb(sample):
    build, sandbox, http, server, routes = sample
    item = build()
    identity = sandbox.inspect_sources(item["assembly"])
    key = identity["symbolKeys"][0]
    assert key.split("/")[0] == item["pdb"].name.lower()
    routes["/symbols/" + key] = (200, {}, item["pdb"].read_bytes())
    item["pdb"].unlink()
    client = SourceLinkClient(http, sandbox, (server.url + "/symbols",))
    metadata = client.documents(str(item["assembly"]))
    assert metadata["pdbFound"] is True
    assert metadata["symbol_url"] == server.url + "/symbols/" + key
    assert metadata["symbol_lookup_failures"] == []
    source = client.read(str(item["assembly"]), item["document"])
    assert source["checksum_verified"] is True
    assert sum(r["path"].startswith("/symbols/") for r in server.requests) == 1
    headers = next(r["headers"] for r in server.requests if r["path"].startswith("/symbols/"))
    assert headers["Symbolchecksumvalidationsupported"] == "1"
    assert headers["Symbolchecksum"] == "SHA256:" + identity["pdbChecksums"]["SHA256"]


def test_wrong_pdb_is_rejected_and_reported(sample):
    build, sandbox, http, server, routes = sample
    item, other = build(), build()
    with pytest.raises(RetrievalError):
        sandbox.inspect_sources(item["assembly"], other["pdb"])
    key = sandbox.inspect_sources(item["assembly"])["symbolKeys"][0]
    routes["/symbols/" + key] = (200, {}, other["pdb"].read_bytes())
    item["pdb"].unlink()
    result = SourceLinkClient(http, sandbox, (server.url + "/symbols",)).documents(str(item["assembly"]))
    assert result["pdbFound"] is False
    assert result["symbol_lookup_failures"][0]["error"]


def test_pdb_with_matching_id_and_modified_contents_is_rejected(sample):
    build, sandbox, _, _, _ = sample
    item = build()
    item["pdb"].write_bytes(item["pdb"].read_bytes() + b"tampered")
    with pytest.raises(RetrievalError, match="PDB checksum"):
        sandbox.inspect_sources(item["assembly"])


def test_missing_symbols_report_failures_instead_of_source(sample):
    build, sandbox, http, server, _ = sample
    item = build()
    item["pdb"].unlink()
    client = SourceLinkClient(http, sandbox, (server.url + "/symbols",))
    metadata = client.documents(str(item["assembly"]))
    assert metadata["pdbFound"] is False
    assert "HTTP 404" in metadata["symbol_lookup_failures"][0]["error"]
    with pytest.raises(RetrievalError, match="Document not found"):
        client.read(str(item["assembly"]), item["document"])
