#!/usr/bin/env python3
"""Validate eval datasets and rubrics without calling any LLM.

Catches the failures that would otherwise only surface mid-eval-run (and
after spending API credits) or, worse, silently skew a score:

  * malformed or non-object JSONL rows
  * duplicate case ids (results overwrite each other in the report)
  * a case pointing at a skill that does not exist in dotnet-skills
    (the runner skips these, so typos quietly shrink the eval)
  * an effectiveness case naming a rubric file that is not on disk
  * a rubric whose weights do not sum to 1.0 (skewed scoring)
  * a rubric whose skill_name disagrees with the case that loads it
  * orphaned rubrics (nothing runs them)

Exit code 0 = OK, 1 = errors found. Warnings do not fail the build.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

from dotnet_skills_evals.config import (
    ACTIVATION_DATASET_DIR,
    EFFECTIVENESS_DATASET_DIR,
    RUBRICS_DIR,
    ensure_skills_repo,
)
from dotnet_skills_evals.skills.loader import load_all_skills
from dotnet_skills_evals.eval_ilspy.runner import DATASET as ILSPY_DATASET, read_dataset as read_ilspy_dataset

# Keys the runners index directly with case["..."] - a missing one is a hard error.
ACTIVATION_REQUIRED = ("id", "user_prompt", "expected_skills")
EFFECTIVENESS_REQUIRED = ("id", "skill_name", "task", "rubric_file")

WEIGHT_TOLERANCE = 1e-6


class Reporter:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)


def read_jsonl(path: Path, rep: Reporter) -> list[dict]:
    """Parse a JSONL file, reporting per-line problems instead of raising."""
    cases: list[dict] = []
    seen: dict[str, int] = {}

    for lineno, raw in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not raw.strip():
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as exc:
            rep.error(f"{path.name}:{lineno}: invalid JSON ({exc.msg})")
            continue
        if not isinstance(obj, dict):
            rep.error(f"{path.name}:{lineno}: expected an object, got {type(obj).__name__}")
            continue

        missing = [k for k in (
            ACTIVATION_REQUIRED if "activation" in path.parts else EFFECTIVENESS_REQUIRED
        ) if k not in obj]
        if missing:
            rep.error(f"{path.name}:{lineno}: missing required key(s): {', '.join(missing)}")

        case_id = obj.get("id")
        if isinstance(case_id, str):
            if case_id in seen:
                rep.error(
                    f"{path.name}:{lineno}: duplicate id '{case_id}' "
                    f"(first seen on line {seen[case_id]})"
                )
            else:
                seen[case_id] = lineno
        cases.append(obj)

    return cases


def validate_rubric(
    rubric_file: str, case_skill: str, source: str, rep: Reporter, loaded: set[str]
) -> None:
    """Check a rubric exists, is well-formed, and matches its case."""
    loaded.add(rubric_file)
    path = RUBRICS_DIR / rubric_file

    if not path.exists():
        rep.error(f"{source}: rubric file '{rubric_file}' not found in {RUBRICS_DIR}")
        return

    try:
        rubric = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        rep.error(f"{source}: {rubric_file} is not valid YAML ({exc})")
        return

    if not isinstance(rubric, dict):
        rep.error(f"{source}: {rubric_file} must contain a mapping")
        return

    for key in ("skill_name", "criteria"):
        if key not in rubric:
            rep.error(f"{source}: {rubric_file} missing required key '{key}'")

    rubric_skill = rubric.get("skill_name")
    if rubric_skill and rubric_skill != case_skill:
        rep.error(
            f"{source}: rubric '{rubric_file}' declares skill_name '{rubric_skill}' "
            f"but the case uses '{case_skill}'"
        )

    criteria = rubric.get("criteria")
    if not isinstance(criteria, list) or not criteria:
        rep.error(f"{source}: {rubric_file} needs a non-empty 'criteria' list")
        return

    total = 0.0
    for idx, crit in enumerate(criteria, start=1):
        if not isinstance(crit, dict):
            rep.error(f"{source}: {rubric_file} criteria[{idx}] is not a mapping")
            continue
        for key in ("name", "weight", "description"):
            if key not in crit:
                rep.error(
                    f"{source}: {rubric_file} criteria[{idx}] missing '{key}'"
                )
        weight = crit.get("weight")
        if isinstance(weight, (int, float)):
            total += float(weight)
        elif weight is not None:
            rep.error(
                f"{source}: {rubric_file} criteria[{idx}] weight is not numeric: {weight!r}"
            )

    if abs(total - 1.0) > WEIGHT_TOLERANCE:
        rep.error(
            f"{source}: {rubric_file} criteria weights sum to {total:.4f}, expected 1.0"
        )


def main() -> int:
    rep = Reporter()

    # --- Skill catalog from the repo under evaluation ---
    try:
        repo = ensure_skills_repo()
        skills = load_all_skills(repo / "skills")
        known = {s.metadata.name for s in skills}
        print(f"dotnet-skills: {len(known)} skills from {repo}")
    except Exception as exc:  # noqa: BLE001 - CI should report, not traceback
        print(f"ERROR: cannot load dotnet-skills catalog: {exc}", file=sys.stderr)
        return 1

    if not known:
        print("ERROR: dotnet-skills catalog is empty", file=sys.stderr)
        return 1

    # --- Activation datasets ---
    activation_files = sorted(ACTIVATION_DATASET_DIR.glob("*.jsonl"))
    if not activation_files:
        rep.error(f"No activation JSONL datasets found in {ACTIVATION_DATASET_DIR}")

    referenced: set[str] = set()
    for path in activation_files:
        cases = read_jsonl(path, rep)
        for case in cases:
            expected = case.get("expected_skills", [])
            acceptable = case.get("acceptable_skills", [])
            if not isinstance(expected, list) or not isinstance(acceptable, list):
                rep.error(f"{path.name}/{case.get('id')}: skill lists must be arrays")
                continue
            should_activate = case.get("should_activate", len(expected) > 0)
            if should_activate and not expected and not acceptable:
                rep.error(
                    f"{path.name}/{case.get('id')}: should_activate=true but no "
                    "expected_skills or acceptable_skills"
                )
            for name in list(expected) + list(acceptable):
                referenced.add(name)
                if name not in known:
                    rep.error(
                        f"{path.name}/{case.get('id')}: unknown skill '{name}' "
                        "(not in the dotnet-skills catalog)"
                    )
        print(f"activation/{path.name}: {len(cases)} cases")

    # --- Effectiveness datasets + rubrics ---
    effectiveness_files = sorted(EFFECTIVENESS_DATASET_DIR.glob("*.jsonl"))
    if not effectiveness_files:
        rep.error(
            f"No effectiveness JSONL datasets found in {EFFECTIVENESS_DATASET_DIR}"
        )

    loaded_rubrics: set[str] = set()
    for path in effectiveness_files:
        cases = read_jsonl(path, rep)
        for case in cases:
            skill = case.get("skill_name")
            source = f"{path.name}/{case.get('id')}"
            if skill and skill not in known:
                rep.error(
                    f"{source}: unknown skill '{skill}' (not in the dotnet-skills catalog)"
                )
            rubric_file = case.get("rubric_file")
            if rubric_file:
                validate_rubric(rubric_file, skill or "", source, rep, loaded_rubrics)
                referenced.add(skill or "")
        print(f"effectiveness/{path.name}: {len(cases)} cases")

    # Execution-based ILSpy cases have their own schema. No Docker/API calls.
    try:
        ilspy_cases = read_ilspy_dataset(ILSPY_DATASET)
        if "ilspy-decompile" not in known:
            rep.error("ILSpy eval requires ilspy-decompile in the skill catalog")
        referenced.add("ilspy-decompile")
        print(f"ilspy/{ILSPY_DATASET.name}: {len(ilspy_cases)} cases")
    except (ValueError, OSError) as exc:
        rep.error(f"ILSpy dataset: {exc}")

    # --- Orphaned rubrics: present but never exercised ---
    on_disk = {p.name for p in RUBRICS_DIR.glob("*.yaml")}
    for orphan in sorted(on_disk - loaded_rubrics):
        rep.warn(f"rubric '{orphan}' is not referenced by any effectiveness case")

    # --- Coverage signal (informational) ---
    uncovered = sorted(known - referenced)
    coverage = (len(referenced & known) / len(known)) * 100
    print(
        f"\nskill coverage: {len(referenced & known)}/{len(known)} skills exercised "
        f"({coverage:.1f}%)"
    )
    if uncovered:
        preview = ", ".join(uncovered[:8])
        more = f" (+{len(uncovered) - 8} more)" if len(uncovered) > 8 else ""
        print(f"  not covered: {preview}{more}")

    for warning in rep.warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    for error in rep.errors:
        print(f"ERROR: {error}", file=sys.stderr)

    if rep.errors:
        print(f"\n{len(rep.errors)} error(s), {len(rep.warnings)} warning(s)", file=sys.stderr)
        return 1

    print(f"\nOK - datasets valid ({len(rep.warnings)} warning(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
