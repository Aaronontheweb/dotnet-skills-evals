"""Telemetry for ordinary ilspycmd and dnx ilspycmd invocations in the fixture.

This is measurement instrumentation for cooperative agents, not a tamper-proof
security boundary. No model text or shell-command substring is used for scoring.
"""

import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    args = sys.argv[1:]
    # Help, metadata/type listings, and version queries are not decompilation.
    informational = any(a in {"-h", "--help", "-v", "--version", "-l", "--list"}
                        or a.startswith(("--list=", "-l=")) for a in args)
    assemblies = {}
    for arg in args:
        path = Path(arg)
        if path.suffix.lower() in {".dll", ".exe"} and path.is_file():
            assemblies[str(path.resolve())] = digest(path)
    output_dir = None
    for i, arg in enumerate(args):
        if arg in {"-o", "--outputdir"} and i + 1 < len(args):
            output_dir = Path(args[i + 1])
        elif arg.startswith("--outputdir="):
            output_dir = Path(arg.split("=", 1)[1])
    before = {}
    if output_dir and output_dir.is_dir():
        before = {str(p): (p.stat().st_mtime_ns, p.stat().st_size)
                  for p in output_dir.rglob("*") if p.is_file()}
    started = time.time()
    event = {"argv": args, "assemblies": assemblies, "started_at": started,
             "decompilation_requested": not informational and bool(args)}
    # An unfinished event remains visible if a shell timeout kills the tool.
    with open("/tmp/ilspy-events.jsonl", "a") as f:
        f.write(json.dumps({**event, "phase": "started"}) + "\n")
    result = subprocess.run(["/opt/ilspy/ilspycmd-real", *args], capture_output=True)
    sys.stdout.buffer.write(result.stdout)
    sys.stderr.buffer.write(result.stderr)
    generated = []
    if output_dir and output_dir.is_dir():
        for p in output_dir.rglob("*"):
            if p.is_file() and p.suffix in {".cs", ".il"} and p.stat().st_size:
                if before.get(str(p)) != (p.stat().st_mtime_ns, p.stat().st_size):
                    generated.append({"path": str(p), "sha256": digest(p)})
    code_output = bool(re.search(
        r"(?m)^\s*(?:namespace\s|\.class\s|\.assembly\s|"
        r"(?:public|internal)\s+(?:(?:sealed|abstract|static|readonly|partial)\s+)*"
        r"(?:class|struct|interface|enum|delegate|record)\s)",
        result.stdout.decode("utf-8", errors="replace")))
    event.update(phase="finished", returncode=result.returncode, stdout_is_code=code_output,
                 stdout_bytes=len(result.stdout), stdout_sha256=hashlib.sha256(result.stdout).hexdigest(),
                 generated_files=generated, duration_seconds=time.time() - started)
    with open("/tmp/ilspy-events.jsonl", "a") as f:
        f.write(json.dumps(event) + "\n")
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
