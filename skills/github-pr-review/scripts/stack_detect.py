#!/usr/bin/env python3
"""Classify changed PR files into focused stack review passes."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path


STACK_ORDER = ("java-springboot", "react-ui", "python", "skill-authoring", "general")
JAVA_FILES = {"pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts"}
WEB_EXTENSIONS = {".js", ".jsx", ".ts", ".tsx", ".css", ".scss", ".sass", ".html", ".vue", ".svelte"}


def classify_file(path: str) -> str | None:
    """Return a review stack, or None for shared files to attach to the dominant stack."""
    normalized = path.replace("\\", "/").strip("/")
    parts = [part.lower() for part in normalized.split("/") if part]
    filename = parts[-1] if parts else ""
    if filename == "skill.md" and any(
        parts[i] == "skills" and (i == 0 or parts[i - 1] in {".agents", ".codex"})
        for i in range(len(parts))
    ):
        return "skill-authoring"
    if filename.endswith((".pyi",)) or filename in {"pyproject.toml", "requirements.txt"} or filename.startswith("requirements-"):
        return "python"
    if filename.endswith(".py"):
        return "general"
    if filename.endswith((".java", ".kt", ".kts", ".gradle")) or filename in JAVA_FILES or filename.endswith(".properties"):
        return "java-springboot"
    if filename.endswith(tuple(WEB_EXTENSIONS)) or filename == "package.json":
        # Avoid calling a backend JavaScript/TypeScript package a React UI pass.
        if any(part in {"backend", "server", "api", "scripts"} for part in parts[:-1]):
            return None
        return "react-ui"
    return None


def _skill_name(path: str) -> str | None:
    parts = path.replace("\\", "/").split("/")
    lowered = [part.lower() for part in parts]
    for index, part in enumerate(lowered[:-1]):
        if part == "skills" and index + 1 < len(parts) - 1 and lowered[-1] == "skill.md":
            return parts[index + 1]
    return None


def detect_stacks(diffs: list[dict]) -> dict:
    """Create deterministic stack file groups, folding shared files into the dominant stack."""
    entries = []
    counts = Counter()
    for diff in diffs:
        path = diff.get("new_path") or diff.get("old_path") or ""
        if not path:
            continue
        stack = classify_file(path)
        if stack:
            counts[stack] += 1
        entries.append((path, stack))

    known = [name for name in STACK_ORDER if counts[name]]
    if known:
        dominant = sorted(known, key=lambda name: (-counts[name], STACK_ORDER.index(name)))[0]
    else:
        dominant = "general"
    grouped = defaultdict(list)
    for path, stack in entries:
        grouped[stack or dominant].append(path)
    for paths in grouped.values():
        paths.sort(key=str.lower)
    matched = [name for name in STACK_ORDER if grouped.get(name)]
    skill_names = {path: name for path, _ in entries if (name := _skill_name(path))}
    unrecognized = [path for path, stack in entries if stack is None]
    return {
        "matched_stacks": matched or ["general"],
        "dominant_stack": dominant,
        "stack_files": {name: grouped[name] for name in matched or ["general"]},
        "inconclusive": not bool(known),
        "unrecognized_files": sorted(unrecognized, key=str.lower),
        "skill_names": skill_names,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pr_data", help="JSON produced by fetch_pr_data.py")
    parser.add_argument("--output", default="stacks.json")
    args = parser.parse_args()
    try:
        data = json.loads(Path(args.pr_data).read_text(encoding="utf-8"))
        diffs = data.get("diffs")
        if not isinstance(diffs, list):
            raise ValueError("PR data must contain a diffs array")
        result = detect_stacks(diffs)
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        parser.exit(2, f"stack_detect: {exc}\n")
    print(f"Wrote {output}: {', '.join(result['matched_stacks'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
