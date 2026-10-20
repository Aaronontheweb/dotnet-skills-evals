#!/usr/bin/env python3
"""Audit the uv lock for vulnerabilities and enforce a documented-exception policy.

Why this exists instead of `pip-audit ... | tee report.txt` in the workflow:
a bare --ignore-vuln flag in YAML is how ignore lists silently grow. This script
makes every exception carry a reason and an expiry, and fails the build when:

  * a finding is NOT covered by a documented exception            (new vuln)
  * an exception's review_by date has passed                      (stale waiver)
  * an exception no longer matches any finding                    (dead waiver)
  * the advisory DB fetch fails while --strict is requested       (silent pass)

Findings are deduplicated by (package, version, id): pip-audit reports each
advisory once per requirements entry, which double-counts in a lock export.

Exit 0 = clean or all findings waived. Exit 1 = policy violation.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_EXCEPTIONS = REPO / ".pip-audit-exceptions.json"
PIP_AUDIT_VERSION = "2.10.1"  # newest release >= 7 days old; see CLAUDE.md policy


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True)


def export_requirements(extra_dev: bool) -> Path:
    """uv export the lock (with hashes) to a temp requirements file."""
    cmd = ["uv", "export", "--frozen", "--no-emit-project",
           "--format", "requirements-txt"]
    if extra_dev:
        cmd.insert(3, "--extra")
        cmd.insert(4, "dev")
    proc = run(cmd)
    if proc.returncode != 0:
        sys.exit(f"ERROR: uv export failed:\n{proc.stderr}")
    tmp = Path(tempfile.mkstemp(suffix=".txt", prefix="audit-reqs-")[1])
    tmp.write_text(proc.stdout, encoding="utf-8")
    return tmp


def load_exceptions(path: Path, today: dt.date) -> tuple[dict[str, dict], list[str]]:
    """Return {vuln_id: exception} plus any policy problems with the file itself."""
    problems: list[str] = []
    if not path.exists():
        # An absent file is a valid empty allowlist, not an error.
        return {}, problems

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        sys.exit(f"ERROR: {path.name} is not valid JSON: {exc}")

    entries = data.get("exceptions", [])
    out: dict[str, dict] = {}
    for entry in entries:
        vid = entry.get("id")
        if not vid:
            problems.append("exception entry missing 'id'")
            continue
        if not entry.get("reason"):
            problems.append(f"{vid}: missing 'reason' - every waiver must say why")
        review_by = entry.get("review_by")
        if not review_by:
            problems.append(f"{vid}: missing 'review_by' - waivers must expire")
            continue
        try:
            expiry = dt.date.fromisoformat(review_by)
        except ValueError:
            problems.append(f"{vid}: review_by '{review_by}' is not YYYY-MM-DD")
            continue
        if expiry < today:
            problems.append(
                f"{vid}: waiver EXPIRED {review_by} (today {today}) - "
                "re-check for an upstream fix or extend with justification"
            )
        out[vid] = entry
    return out, problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exceptions", type=Path, default=DEFAULT_EXCEPTIONS)
    parser.add_argument("--output", type=Path, default=None,
                        help="write the raw pip-audit report here")
    parser.add_argument("--no-dev", action="store_true",
                        help="exclude the dev extra from the scan")
    parser.add_argument("--today", default=None,
                        help="override today's date (YYYY-MM-DD, testing only)")
    args = parser.parse_args()

    today = (dt.date.fromisoformat(args.today) if args.today
             else dt.datetime.now(dt.timezone.utc).date())

    reqs = export_requirements(extra_dev=not args.no_dev)
    try:
        proc = run([
            "uvx", f"--from", f"pip-audit=={PIP_AUDIT_VERSION}", "pip-audit",
            "--require-hashes", "--disable-pip", "--strict",
            "--progress-spinner", "off",
            "--format", "json", "--output", "-",
            "-r", str(reqs),
        ])
    finally:
        reqs.unlink(missing_ok=True)

    # pip-audit exits 1 when it finds vulns; that is not an error here.
    raw = proc.stdout.strip()
    if not raw:
        # No JSON means a real failure (network, bad flag, resolver error).
        # Failing closed matters: a broken scan that exits clean is worse than
        # a red build - it looks like a pass.
        print("ERROR: pip-audit produced no JSON output.", file=sys.stderr)
        print(proc.stderr[-3000:], file=sys.stderr)
        return 1

    if args.output:
        args.output.write_text(proc.stdout, encoding="utf-8")

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"ERROR: could not parse pip-audit JSON: {exc}", file=sys.stderr)
        print(raw[:1000], file=sys.stderr)
        return 1

    # pip-audit 2.10.1 emits {"dependencies": [...], "fixes": {...}}. Reading the
    # wrong key here would silently yield zero findings and make the gate
    # vacuously green, so assert the shape instead of using .get() with a default.
    if not isinstance(payload, dict) or "dependencies" not in payload:
        print("ERROR: unexpected pip-audit JSON shape - top-level keys are "
              f"{sorted(payload) if isinstance(payload, dict) else type(payload).__name__}, "
              "expected 'dependencies'. The scanner's output format may have "
              "changed; do NOT let this pass.", file=sys.stderr)
        return 1

    source = payload["dependencies"]
    if not isinstance(source, list):
        print("ERROR: 'dependencies' is not a list in pip-audit output", file=sys.stderr)
        return 1

    findings: dict[tuple[str, str, str], set[str]] = {}
    for dep in source:
        name = dep.get("name", "?")
        version = dep.get("version", "?")
        for vuln in dep.get("vulns", []):
            vid = vuln.get("id", "?")
            fix = vuln.get("fix_versions") or []
            findings.setdefault((name, version, vid), set()).update(fix)

    exceptions, problems = load_exceptions(args.exceptions, today)

    if problems:
        for p in problems:
            print(f"POLICY ERROR: {p}", file=sys.stderr)

    waived: list[str] = []
    blocking: list[str] = []
    for (name, version, vid), fixes in sorted(findings.items()):
        exc = exceptions.get(vid)
        if exc is None:
            fix_note = f" - upgrade to {'/'.join(sorted(fixes))}" if fixes else \
                       " - NO FIX VERSION AVAILABLE"
            blocking.append(f"{name} {version} {vid}{fix_note}")
        elif exc.get("package") and exc["package"] != name:
            blocking.append(
                f"{name} {version} {vid} - waiver names package "
                f"'{exc['package']}' but the finding is '{name}'"
            )
        else:
            waived.append(f"{name} {version} {vid} (review by {exc['review_by']})")

    # Dead waivers: exception present, finding gone. Upstream fixed it, or the
    # dep was dropped. Remove the entry so the file stays honest.
    live_ids = {vid for _, _, vid in findings}
    dead = sorted(set(exceptions) - live_ids)

    print(f"pip-audit {PIP_AUDIT_VERSION} | {len(findings)} unique finding(s) | "
          f"{len(waived)} waived | {len(blocking)} blocking")
    for line in waived:
        print(f"  WAIVED    {line}")
    for line in blocking:
        print(f"  BLOCKING  {line}", file=sys.stderr)
    for vid in dead:
        print(f"  STALE     {vid} is waived but no longer found - "
              "remove it from the exceptions file", file=sys.stderr)

    if blocking or problems:
        print(f"\nFAIL: {len(blocking)} blocking finding(s), "
              f"{len(problems)} policy error(s)", file=sys.stderr)
        return 1
    if dead:
        print("\nFAIL: exceptions file has stale entries", file=sys.stderr)
        return 1

    print("PASS: no blocking vulnerabilities"
          + (f" ({len(waived)} documented waiver(s))" if waived else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
