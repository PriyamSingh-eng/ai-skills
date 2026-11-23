#!/usr/bin/env python3
"""Merge per-stack review JSON blocks into the shared review contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


SEVERITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
RISK_ORDER = {"Low": 0, "Medium": 1, "High": 2, "Critical": 3}
VERDICT_ORDER = {"APPROVE": 0, "NEEDS DISCUSSION": 1, "REQUEST CHANGES": 2}
CHANGE_TYPES = {"new feature", "refactor", "bug fix", "config", "mixed"}


def validate_result(value: dict, stack_name: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{stack_name}: review result must be a JSON object")
    required = {"summary", "risk_level", "requirements_coverage", "change_type",
                "verdict", "verdict_rationale", "findings"}
    missing = required - set(value)
    if missing:
        raise ValueError(f"{stack_name}: missing fields: {', '.join(sorted(missing))}")
    if value["risk_level"] not in RISK_ORDER:
        raise ValueError(f"{stack_name}: unsupported risk_level {value['risk_level']!r}")
    if value["verdict"] not in VERDICT_ORDER:
        raise ValueError(f"{stack_name}: unsupported verdict {value['verdict']!r}")
    if value["change_type"] not in CHANGE_TYPES:
        raise ValueError(f"{stack_name}: unsupported change_type {value['change_type']!r}")
    for field in ("summary", "requirements_coverage", "verdict_rationale"):
        if not isinstance(value[field], str):
            raise ValueError(f"{stack_name}: {field} must be a string")
    if not isinstance(value["findings"], list):
        raise ValueError(f"{stack_name}: findings must be an array")
    for index, finding in enumerate(value["findings"], 1):
        if not isinstance(finding, dict) or finding.get("severity") not in SEVERITY_ORDER:
            raise ValueError(f"{stack_name}: finding {index} has an unsupported severity")
        if finding.get("type") not in {"inline", "general"}:
            raise ValueError(f"{stack_name}: finding {index} type must be inline or general")
        if not isinstance(finding.get("comment_body"), str) or not finding["comment_body"].strip():
            raise ValueError(f"{stack_name}: finding {index} needs comment_body")
        if finding["type"] == "inline":
            if not finding.get("path") or not isinstance(finding.get("line"), int) or finding["line"] < 1:
                raise ValueError(f"{stack_name}: inline finding {index} needs a path and positive line")
            if finding.get("side", "RIGHT") != "RIGHT":
                raise ValueError(f"{stack_name}: inline finding {index} must use side RIGHT")
        elif finding.get("path") is not None or finding.get("line") is not None:
            raise ValueError(f"{stack_name}: general finding {index} must have null path and line")


def merge_results(named_paths: list[tuple[str, str]]) -> dict:
    if not named_paths:
        raise ValueError("Provide at least one --stack NAME=PATH")
    loaded = []
    for name, path_text in named_paths:
        try:
            result = json.loads(Path(path_text).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Could not load {name} review JSON: {exc}") from exc
        validate_result(result, name)
        loaded.append((name, result))

    findings = []
    questions = []
    for stack, result in loaded:
        for finding in result["findings"]:
            merged = dict(finding)
            merged["id"] = 0
            if merged["type"] == "inline":
                merged.setdefault("side", "RIGHT")
            else:
                merged["path"] = None
                merged["line"] = None
                merged["side"] = None
            findings.append(merged)
        question = (result.get("questions_comment") or "").strip()
        if question:
            questions.append(f"**{stack}:**\n{question}")
    findings.sort(key=lambda item: (
        SEVERITY_ORDER[item["severity"]],
        (item.get("path") or "").casefold(),
        item.get("line") or 0,
        item["comment_body"].casefold(),
    ))
    for index, finding in enumerate(findings, 1):
        finding["id"] = index

    risk = max((result["risk_level"] for _, result in loaded), key=RISK_ORDER.get)
    verdict = max((result["verdict"] for _, result in loaded), key=VERDICT_ORDER.get)
    change_types = {result["change_type"] for _, result in loaded}
    summaries = [f"**{name}:** {result['summary'].strip()}" for name, result in loaded if result["summary"].strip()]
    coverage = [f"**{name}:** {result['requirements_coverage'].strip()}"
                for name, result in loaded if result["requirements_coverage"].strip()]
    rationales = [f"{name}: {result['verdict_rationale'].strip()}"
                  for name, result in loaded if result["verdict_rationale"].strip()]
    return {
        "summary": "\n\n".join(summaries),
        "risk_level": risk,
        "requirements_coverage": "\n\n".join(coverage),
        "change_type": next(iter(change_types)) if len(change_types) == 1 else "mixed",
        "verdict": verdict,
        "verdict_rationale": " ".join(rationales),
        "findings": findings,
        "questions_comment": "\n\n".join(questions),
    }


def _stack_argument(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("Use NAME=PATH")
    name, path = value.split("=", 1)
    if not name.strip() or not path.strip():
        raise argparse.ArgumentTypeError("Both stack name and path are required")
    return name.strip(), path.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stack", action="append", type=_stack_argument, required=True,
                        metavar="NAME=PATH", help="Stack review JSON; repeat for each stack")
    parser.add_argument("--output", default="review_merged.json")
    args = parser.parse_args()
    try:
        result = merge_results(args.stack)
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except (OSError, ValueError) as exc:
        parser.exit(2, f"merge_review_results: {exc}\n")
    print(f"Wrote {output} ({len(result['findings'])} findings across {len(args.stack)} stack pass(es))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
