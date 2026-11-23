#!/usr/bin/env python3
"""Fetch GitHub pull request metadata and changed-file patches via REST or `gh`."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from github_pr import load_pr_data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pr_url", help="GitHub PR URL or OWNER/REPO#NUMBER")
    parser.add_argument("--output", default="pr_data.json", help="Output JSON path (default: pr_data.json)")
    args = parser.parse_args()
    try:
        data = load_pr_data(args.pr_url)
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except (ValueError, RuntimeError, OSError) as exc:
        parser.exit(2, f"fetch_pr_data: {exc}\n")
    coverage = data["coverage"]
    print(f"Wrote {output} ({coverage['files_returned']} changed files; head {data['version']['head_sha'][:12]})")
    if not coverage["complete"]:
        print(f"Warning: GitHub reported {coverage['files_reported']} files but returned {coverage['files_returned']}; review coverage is incomplete.")
    if coverage["patches_unavailable"]:
        print(f"Notice: {len(coverage['patches_unavailable'])} file(s) have no patch text; do not invent inline anchors.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
