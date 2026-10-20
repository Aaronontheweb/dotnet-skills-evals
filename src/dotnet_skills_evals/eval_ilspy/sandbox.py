"""Disposable offline execution environment; model commands never run on the host."""

from __future__ import annotations

import json
import os
import selectors
import subprocess
import time
import uuid
from pathlib import Path


DEFAULT_IMAGE = "dotnet-evals-ilspy:seq-7.0.0"
FIXTURE_DIR = Path(__file__).resolve().parents[3] / "fixtures" / "ilspy"


def docker(*args: str, timeout: int = 120) -> str:
    result = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"docker {args[0]} failed: {result.stderr.strip()}")
    return result.stdout


def inspect_image(image: str) -> dict:
    info = json.loads(docker("image", "inspect", image))[0]
    return {"id": info["Id"], "repo_digests": info.get("RepoDigests", [])}


def capture_command(args: list[str], timeout: int) -> dict:
    """Drain both pipes while retaining bounded output, including on the host."""
    limits = {"stdout": 32000, "stderr": 8000}
    buffers = {name: bytearray() for name in limits}
    sizes = dict.fromkeys(limits, 0)
    deadline = time.monotonic() + timeout
    with subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ, "stdout")
            selector.register(process.stderr, selectors.EVENT_READ, "stderr")
            try:
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise subprocess.TimeoutExpired(args, timeout)
                    for key, _ in selector.select(min(1, remaining)):
                        chunk = os.read(key.fileobj.fileno(), 65536)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        name = key.data
                        sizes[name] += len(chunk)
                        buffers[name].extend(chunk[:max(0, limits[name] - len(buffers[name]))])
                process.wait(timeout=max(0.1, deadline - time.monotonic()))
            except BaseException:
                process.kill()
                process.wait()
                raise
    return {"exit_code": process.returncode,
            **{name: data.decode("utf-8", errors="replace") for name, data in buffers.items()},
            "output_truncated": any(sizes[name] > limits[name] for name in limits)}


class DockerSandbox:
    def __init__(self, image: str, command_timeout: int = 60):
        self.image = image
        self.command_timeout = command_timeout
        self.name = f"dotnet-ilspy-{uuid.uuid4().hex}"

    def __enter__(self) -> DockerSandbox:
        try:
            docker("run", "--detach", "--name", self.name, "--network", "none",
                   "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                   "--pids-limit", "128", "--memory", "2g", "--cpus", "2",
                   "--tmpfs", "/tmp:rw,size=512m,mode=1777",
                   "--tmpfs", "/home/eval:rw,size=64m,uid=10001,gid=10001,mode=700",
                   self.image)
        except BaseException:
            # docker run may create a container before failing to start it.
            subprocess.run(["docker", "rm", "--force", self.name], capture_output=True)
            raise
        return self

    def __exit__(self, *exc):
        docker("rm", "--force", self.name)

    def shell(self, command: str) -> dict:
        return capture_command(
            ["docker", "exec", self.name, "timeout", "--kill-after=2s",
             f"{self.command_timeout}s", "bash", "--noprofile", "--norc", "-c", command],
            timeout=self.command_timeout + 15,
        )

    def manifest(self) -> dict:
        return json.loads(docker("exec", "--user", "root", self.name,
                                 "cat", "/opt/fixture/manifest.json"))

    def events(self) -> list[dict]:
        raw = docker("exec", self.name, "sh", "-c",
                     "if [ -f /tmp/ilspy-events.jsonl ]; then cat /tmp/ilspy-events.jsonl; fi")
        return [json.loads(line) for line in raw.splitlines() if line.strip()]


def prepare_fixture(image: str = DEFAULT_IMAGE) -> dict:
    subprocess.run(["docker", "build", "--tag", image, str(FIXTURE_DIR)], check=True)
    # The real execution control catches an unusable tool or broken telemetry
    # before any API credits are spent.
    return check_fixture(image)


def check_fixture(image: str = DEFAULT_IMAGE) -> dict:
    from .metrics import score_events

    identity = inspect_image(image)
    with DockerSandbox(identity["id"]) as sandbox:
        manifest = sandbox.manifest()
        target = manifest["target_assemblies"]["Serilog.Sinks.PeriodicBatching.dll"]
        import shlex

        assembly = shlex.quote(target["path"])
        # Help/listing controls must not become successful activation evidence.
        sandbox.shell("ilspycmd --help")
        sandbox.shell(f"ilspycmd -l c {assembly}")
        if score_events(sandbox.events(), {target["sha256"]})["activated"]:
            raise RuntimeError("ILSpy help/type listing was incorrectly scored as activation")
        result = sandbox.shell(f"ilspycmd -t Serilog.Sinks.PeriodicBatching.PeriodicBatchingSink {assembly}")
        if result["exit_code"] or "PeriodicBatchingSink" not in result["stdout"]:
            raise RuntimeError(f"ILSpy fixture decompilation failed: {result}")
        if not score_events(sandbox.events(), {target["sha256"]})["activated"]:
            raise RuntimeError("Real dependency decompilation produced no activation evidence")
        return {"image": identity, "fixture": manifest, "execution_control": "passed"}
