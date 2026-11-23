#!/usr/bin/env python3
"""Optional Jira issue lookup using credentials supplied through environment variables."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from github_pr import load_config_env


KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9]{1,9}-\d+$")


def _text(value) -> str:
    """Flatten Jira Cloud's rich-text document into readable plain text."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(_text(item) for item in value)
    if isinstance(value, dict):
        own = value.get("text", "")
        children = _text(value.get("content", []))
        if own and children:
            return f"{own}{children}"
        if value.get("type") == "paragraph":
            return (own or children) + "\n"
        return own or children
    return ""


def fetch_issue(key: str, base_url: str, email: str, token: str, api_version: str = "3") -> dict:
    if not KEY_PATTERN.fullmatch(key):
        raise ValueError("Ticket key must look like ABC-123")
    base = base_url.rstrip("/")
    if not base.startswith("https://"):
        raise ValueError("JIRA_BASE_URL must use HTTPS")
    if api_version not in {"2", "3"}:
        raise ValueError("JIRA_API_VERSION must be 2 or 3")
    url = f"{base}/rest/api/{api_version}/issue/{quote(key, safe='')}?fields=summary,description,status,issuetype,priority"
    credential = base64.b64encode(f"{email}:{token}".encode("utf-8")).decode("ascii")
    request = Request(url, headers={"Authorization": f"Basic {credential}",
                                    "Accept": "application/json"})
    try:
        with urlopen(request, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        # Do not print the request headers or credential when surfacing errors.
        raise RuntimeError(f"Jira returned HTTP {exc.code}") from None
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"Could not reach Jira: {type(exc).__name__}") from None
    fields = result.get("fields") or {}
    return {
        "key": result.get("key", key),
        "summary": fields.get("summary", ""),
        "description": _text(fields.get("description"))[:20000],
        "status": ((fields.get("status") or {}).get("name", "")),
        "issue_type": ((fields.get("issuetype") or {}).get("name", "")),
        "priority": ((fields.get("priority") or {}).get("name", "")),
        "url": f"{base}/browse/{quote(key, safe='-')}",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    ticket = subparsers.add_parser("ticket", help="Fetch one Jira issue")
    ticket.add_argument("key")
    ticket.add_argument("--output", help="Optional JSON output path")
    args = parser.parse_args()
    try:
        load_config_env()
    except RuntimeError as exc:
        print(f"jira_fetcher: {exc}", file=sys.stderr)
        return 2
    base_url = os.environ.get("JIRA_BASE_URL", "").strip()
    email = os.environ.get("JIRA_EMAIL", "").strip()
    token = os.environ.get("JIRA_API_TOKEN", "")
    api_version = os.environ.get("JIRA_API_VERSION", "3").strip()
    if not (base_url and email and token):
        print("Jira is not configured; set JIRA_BASE_URL, JIRA_EMAIL, and JIRA_API_TOKEN to enable it.", file=sys.stderr)
        return 2
    try:
        issue = fetch_issue(args.key, base_url, email, token, api_version)
    except (ValueError, RuntimeError) as exc:
        print(f"jira_fetcher: {exc}", file=sys.stderr)
        return 2
    rendered = json.dumps(issue, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
        print(f"Wrote Jira context to {args.output}")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
