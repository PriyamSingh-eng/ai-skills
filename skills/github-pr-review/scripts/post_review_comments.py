#!/usr/bin/env python3
"""Post an explicitly approved GitHub PR review via GitHub CLI or REST token."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from github_pr import parse_pr_locator, pull_endpoint, run_github_json, run_github_post


HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
ALLOWED_EVENTS = {"COMMENT", "APPROVE", "REQUEST_CHANGES"}


def added_lines(patch: str) -> set[int]:
    """Return new-side line numbers represented by added diff lines."""
    result = set()
    new_line = None
    for item in patch.splitlines():
        match = HUNK_RE.match(item)
        if match:
            new_line = int(match.group(1))
        elif new_line is None:
            continue
        elif item.startswith(("+++", "---", "\\")):
            continue
        elif item.startswith("+"):
            result.add(new_line)
            new_line += 1
        elif item.startswith("-"):
            continue
        else:
            # Context lines advance the new-side line coordinate.
            new_line += 1
    return result


def _same_pr(first: dict, second: dict) -> bool:
    return all(first.get(key) == second.get(key) for key in ("host", "owner", "repo", "number"))


def validate_review(pr_data: dict, approved: dict) -> tuple[dict, dict, list[dict], str, str]:
    pr = pr_data.get("pr") or {}
    version = pr_data.get("version") or {}
    approval = approved.get("approval") or {}
    if not approval.get("approved"):
        raise ValueError("Approved review file must contain approval.approved=true")
    if not approval.get("pr_url") or not approval.get("head_sha"):
        raise ValueError("Approval must record the exact pr_url and head_sha shown to the user")
    approved_pr = parse_pr_locator(approval["pr_url"])
    stored_pr = {key: pr.get(key) for key in ("host", "owner", "repo", "number")}
    if not _same_pr(approved_pr, stored_pr):
        raise ValueError("Approval PR URL does not match the fetched PR data")
    head_sha = version.get("head_sha") or ""
    if not head_sha or approval["head_sha"] != head_sha:
        raise ValueError("Approval head_sha does not match the reviewed PR version")
    event = str(approval.get("event") or "COMMENT").upper()
    if event not in ALLOWED_EVENTS:
        raise ValueError(f"Unsupported approved review event: {event}")

    diffs = {item.get("new_path"): item for item in pr_data.get("diffs", []) if item.get("new_path")}
    findings = approved.get("findings") or []
    inline_comments = []
    general_bodies = []
    for index, finding in enumerate(findings, 1):
        if not isinstance(finding, dict) or not (finding.get("comment_body") or "").strip():
            raise ValueError(f"Approved finding {index} has no comment_body")
        kind = finding.get("type")
        if kind == "general":
            if finding.get("path") is not None or finding.get("line") is not None:
                raise ValueError(f"General finding {index} must have null path and line")
            general_bodies.append(finding["comment_body"].strip())
            continue
        if kind != "inline":
            raise ValueError(f"Approved finding {index} type must be inline or general")
        path = finding.get("path")
        line = finding.get("line")
        if not path or not isinstance(line, int) or line < 1:
            raise ValueError(f"Inline finding {index} needs a path and positive line")
        diff = diffs.get(path)
        if not diff or diff.get("patch_unavailable") or not diff.get("diff"):
            raise ValueError(f"No patch is available to validate inline anchor {path}:{line}; do not convert it automatically")
        if line not in added_lines(diff["diff"]):
            raise ValueError(f"Inline anchor {path}:{line} is not an added line in the fetched PR diff")
        inline_comments.append({"path": path, "line": line, "side": "RIGHT",
                                "body": finding["comment_body"].strip()})

    body_parts = []
    review_body = (approved.get("review_body") or "").strip()
    if review_body:
        body_parts.append(review_body)
    if general_bodies:
        body_parts.append("### General findings\n\n" + "\n\n".join(general_bodies))
    questions = (approved.get("questions_comment") or "").strip()
    if questions:
        body_parts.append(questions)
    body = "\n\n---\n\n".join(body_parts)
    if not body and not inline_comments:
        raise ValueError("There is no approved review body, general comment, question, or inline finding to post")
    if event == "COMMENT" and not body:
        body = "Approved review findings are included in the inline comments below."
    locator = {key: pr.get(key) for key in ("host", "owner", "repo", "number")}
    return locator, approval, inline_comments, body, event


def build_payload(approved: dict, inline_comments: list[dict], body: str,
                  event: str, head_sha: str) -> dict:
    return {"commit_id": head_sha, "body": body, "event": event,
            "comments": inline_comments}


def post_approved_review(pr_data: dict, approved: dict) -> dict:
    locator, approval, inline_comments, body, event = validate_review(pr_data, approved)
    endpoint = pull_endpoint(locator)
    latest = run_github_json(locator, endpoint)
    latest_sha = ((latest.get("head") or {}).get("sha"))
    if latest_sha != approval["head_sha"]:
        raise ValueError("PR head changed after approval. Refresh the PR data, re-review changed lines, and request approval again.")
    payload = build_payload(approved, inline_comments, body, event, latest_sha)
    return run_github_post(locator, f"{endpoint}/reviews", payload)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pr-data", required=True, help="JSON produced by fetch_pr_data.py")
    parser.add_argument("--comments", required=True, help="User-approved review JSON")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--approved", action="store_true", help="Confirm the user approved this exact PR, head SHA, content, and review event")
    mode.add_argument("--dry-run", action="store_true", help="Validate the approval record and report the payload counts without submitting")
    args = parser.parse_args()
    try:
        pr_data = json.loads(Path(args.pr_data).read_text(encoding="utf-8"))
        approved = json.loads(Path(args.comments).read_text(encoding="utf-8"))
        locator, approval, inline_comments, body, event = validate_review(pr_data, approved)
        if args.dry_run:
            print(f"Dry run: {event} review for {approval['pr_url']} at {approval['head_sha'][:12]}; "
                  f"{len(inline_comments)} inline comment(s); general/questions included: {bool(body)}")
            return 0
        result = post_approved_review(pr_data, approved)
    except (OSError, json.JSONDecodeError, ValueError, RuntimeError) as exc:
        print(f"post_review_comments: {exc}", file=sys.stderr)
        return 2
    print(f"GitHub accepted the {event} review: {result.get('html_url', '(URL unavailable)')}")
    print(f"Inline comments posted: {len(inline_comments)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
