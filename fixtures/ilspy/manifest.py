"""Write fixture identities during the Docker build; never shown to the model."""

import hashlib
import json
import subprocess
from pathlib import Path


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


root = Path("/opt/nuget")
target = root / "serilog.sinks.periodicbatching/4.0.0/lib/netstandard2.0/Serilog.Sinks.PeriodicBatching.dll"
print(json.dumps({
    "repository": "https://github.com/datalust/serilog-sinks-seq.git",
    "tag": "v7.0.0",
    "commit": subprocess.check_output(["git", "-C", "/workspace/repo", "rev-parse", "HEAD"], text=True).strip(),
    "sdk": subprocess.check_output(["dotnet", "--version"], text=True).strip(),
    "ilspy_version": subprocess.check_output(["/opt/ilspy/ilspycmd", "--version"], text=True).strip(),
    "lock_sha256": sha256(Path("/opt/fixture/packages.lock.json")),
    "packages": {str(p.relative_to(root)): sha256(p) for p in sorted(root.rglob("*.nupkg"))},
    "assemblies": {str(p): sha256(p) for p in sorted(root.rglob("*.dll"))},
    "target_assemblies": {target.name: {
        "path": str(target), "sha256": sha256(target),
        "sha256_by_path": {str(p): sha256(p) for p in sorted(
            (root / "serilog.sinks.periodicbatching/4.0.0/lib").rglob(target.name))},
    }},
}, indent=2))
