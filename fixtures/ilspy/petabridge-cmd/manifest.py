"""Record public NuGet package and local fixture identities; hidden from models."""

import hashlib
import json
from pathlib import Path
import subprocess


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


root = Path("/opt/nuget")
package = root / "petabridge.cmd.common/1.5.2"
target = package / "lib/net6.0/Petabridge.Cmd.Common.dll"
print(json.dumps({
    "repository": "fixture:petabridge-cmd-support-console",
    "tag": "petabridge-cmd-common-1.5.2",
    "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
    "sdk": subprocess.check_output(["dotnet", "--version"], text=True).strip(),
    "ilspy_version": subprocess.check_output(["/opt/ilspy/ilspycmd", "--version"], text=True).strip(),
    "lock_sha256": sha256(Path("/workspace/repo/packages.lock.json")),
    "packages": {str(p.relative_to(root)): sha256(p) for p in sorted(root.rglob("*.nupkg"))},
    "assemblies": {str(p): sha256(p) for p in sorted(root.rglob("*.dll"))},
    "target_assemblies": {target.name: {
        "path": str(target), "sha256": sha256(target),
        "sha256_by_path": {str(p): sha256(p) for p in sorted((package / "lib").rglob(target.name))},
    }},
    "execution_control": {
        "assembly": target.name, "type": "Petabridge.Cmd.CommandParser",
        "marker": "class CommandParser",
        "runtime_command": "dotnet bin/Release/net10.0/SupportConsole.dll",
        "runtime_markers": ['Handler receives: "plain text"', 'Handler receives: "blue team"',
                            "Success: False", "Unknown argument"],
    },
}, indent=2))
