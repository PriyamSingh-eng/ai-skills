"""Secret-safe GitHub REST and CLI helpers shared by the PR review scripts."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen


JIRA_KEY_RE = re.compile(r"\b[A-Z][A-Z0-9]{1,9}-\d+\b")
LINK_NEXT_RE = re.compile(r'<([^>]+)>\s*;\s*rel="next"')
ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
API_VERSION = "2022-11-28"


def load_config_env() -> None:
    """Load simple KEY=VALUE settings without overriding the process environment."""
    configured_path = os.environ.get("GITHUB_PR_REVIEW_ENV_FILE", "").strip()
    env_path = (Path(configured_path).expanduser() if configured_path else
                Path(__file__).resolve().parents[1] / ".env")
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise RuntimeError(f"Could not read review configuration file: {env_path}") from exc

    for line_number, raw_line in enumerate(lines, 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if "=" not in line:
            raise RuntimeError(f"Invalid config line {line_number} in {env_path}; expected KEY=VALUE")
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if not ENV_KEY_RE.fullmatch(key):
            raise RuntimeError(f"Invalid config key on line {line_number} in {env_path}")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def parse_pr_url(value: str) -> dict:
    """Parse a GitHub.com or GitHub Enterprise pull request URL."""
    parsed = urlsplit(value.strip())
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("Expected an https GitHub pull request URL without embedded credentials")
    parts = [part for part in parsed.path.split("/") if part]
    try:
        pull_index = parts.index("pull")
        owner, repo, number_text = parts[pull_index - 2 : pull_index + 1]
        number = int(number_text)
    except (ValueError, IndexError) as exc:
        raise ValueError("Expected a URL shaped like https://host/OWNER/REPO/pull/NUMBER") from exc
    if number <= 0 or not owner or not repo:
        raise ValueError("Pull request URL contains an invalid owner, repository, or number")
    return {"host": parsed.netloc, "owner": owner,
            "repo": repo.removesuffix(".git"), "number": number,
            "url": f"{parsed.scheme}://{parsed.netloc}/{'/'.join(parts[:pull_index + 1])}"}


def parse_pr_locator(value: str) -> dict:
    """Accept a PR URL or OWNER/REPO#NUMBER (using github.com for the latter)."""
    value = value.strip()
    if value.startswith(("https://", "http://")):
        return parse_pr_url(value)
    match = re.fullmatch(r"([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)#([1-9]\d*)", value)
    if not match:
        raise ValueError("Use a GitHub PR URL or OWNER/REPO#NUMBER")
    owner, repo, number = match.groups()
    return {"host": "github.com", "owner": owner, "repo": repo,
            "number": int(number),
            "url": f"https://github.com/{owner}/{repo}/pull/{number}"}


def _auth_mode() -> str:
    load_config_env()
    mode = os.environ.get("GITHUB_AUTH_MODE", "auto").strip().lower()
    if mode not in {"auto", "gh", "token"}:
        raise RuntimeError("GITHUB_AUTH_MODE must be auto, gh, or token")
    if mode == "auto":
        return "token" if (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")) else "gh"
    if mode == "token" and not (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")):
        raise RuntimeError("GITHUB_AUTH_MODE=token requires GITHUB_TOKEN (or GH_TOKEN) in the environment")
    return mode


def _rest_api_base(locator: dict) -> str:
    host = locator["host"]
    configured = os.environ.get("GITHUB_API_URL", "").strip().rstrip("/")
    if configured:
        parsed = urlsplit(configured)
        if parsed.scheme != "https" or not parsed.netloc:
            raise RuntimeError("GITHUB_API_URL must be an https URL")
        expected_api_hosts = {"api.github.com"} if host.lower() == "github.com" else {host.lower()}
        if parsed.netloc.lower() not in expected_api_hosts:
            raise RuntimeError("GITHUB_API_URL host must be api.github.com for github.com PRs, or match the pull request host for Enterprise")
        return configured
    if host.lower() == "github.com":
        return "https://api.github.com"
    enterprise_hosts = {
        value.strip().lower()
        for value in os.environ.get("GITHUB_ENTERPRISE_HOSTS", "").split(",")
        if value.strip()
    }
    if host.lower() not in enterprise_hosts:
        raise RuntimeError(
            "Direct token mode is restricted to github.com. For GitHub Enterprise, set "
            "GITHUB_ENTERPRISE_HOSTS to the trusted host and GITHUB_API_URL to its https://HOST/api/v3 endpoint."
        )
    return f"https://{host}/api/v3"


def _rest_request(locator: dict, endpoint: str, *, method: str = "GET", payload=None,
                  url: str | None = None):
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        raise RuntimeError("Direct token mode requires GITHUB_TOKEN (or GH_TOKEN) in the environment")
    base = _rest_api_base(locator)
    request_url = url or f"{base}/{endpoint.lstrip('/')}"
    parsed_url = urlsplit(request_url)
    base_parts = urlsplit(base)
    if parsed_url.scheme != "https" or parsed_url.netloc.lower() != base_parts.netloc.lower():
        raise RuntimeError("Refusing to send GitHub credentials to an untrusted API host")
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": API_VERSION,
        "User-Agent": "github-pr-review-skill",
    }
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(request_url, data=data, headers=headers, method=method)
    # Mark credentials as unredirected so urllib cannot forward them to a redirect host.
    request.add_unredirected_header("Authorization", f"Bearer {token}")
    try:
        with urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}
    except HTTPError as exc:
        raise RuntimeError(f"GitHub REST API returned HTTP {exc.code} ({exc.reason})") from None
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"Could not reach GitHub REST API: {type(exc).__name__}") from None
    except json.JSONDecodeError as exc:
        raise RuntimeError("GitHub REST API returned invalid JSON") from exc


def run_github_json(locator: dict, endpoint: str, *, paginate: bool = False):
    """Run an authenticated read request using direct REST or the GitHub CLI."""
    if _auth_mode() == "token":
        url = f"{_rest_api_base(locator)}/{endpoint.lstrip('/')}"
        if not paginate:
            return _rest_request(locator, endpoint)
        items = []
        while url:
            parsed = urlsplit(url)
            current = _rest_api_base(locator)
            current_parts = urlsplit(current)
            if parsed.scheme != "https" or parsed.netloc.lower() != current_parts.netloc.lower():
                raise RuntimeError("Refusing to send GitHub credentials to an untrusted pagination URL")
            token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
            headers = {"Accept": "application/vnd.github+json",
                       "X-GitHub-Api-Version": API_VERSION, "User-Agent": "github-pr-review-skill"}
            try:
                request = Request(url, headers=headers)
                request.add_unredirected_header("Authorization", f"Bearer {token}")
                with urlopen(request, timeout=30) as response:
                    page = json.loads(response.read().decode("utf-8"))
                    if not isinstance(page, list):
                        raise RuntimeError("Expected a JSON array from the paginated GitHub endpoint")
                    items.extend(page)
                    match = LINK_NEXT_RE.search(response.headers.get("Link", ""))
                    url = urljoin(url, match.group(1)) if match else ""
            except HTTPError as exc:
                raise RuntimeError(f"GitHub REST API returned HTTP {exc.code} ({exc.reason})") from None
            except (URLError, TimeoutError) as exc:
                raise RuntimeError(f"Could not reach GitHub REST API: {type(exc).__name__}") from None
            except json.JSONDecodeError as exc:
                raise RuntimeError("GitHub REST API returned invalid JSON") from exc
        return items

    command = ["gh", "api", "--hostname", locator["host"],
               "--header", "Accept: application/vnd.github+json"]
    if paginate:
        command.extend(["--paginate", "--slurp"])
    command.append(endpoint.lstrip("/"))
    try:
        result = subprocess.run(command, check=False, capture_output=True, text=True,
                                encoding="utf-8", errors="replace")
    except FileNotFoundError as exc:
        raise RuntimeError("GitHub CLI (`gh`) is required in CLI mode; install it and authenticate with `gh auth login`, or set GITHUB_AUTH_MODE=token and GITHUB_TOKEN.") from exc
    if result.returncode:
        detail = result.stderr.strip() or "GitHub CLI request failed"
        raise RuntimeError(detail[:1200])
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("GitHub CLI returned invalid JSON; verify `gh` authentication and host configuration.") from exc


def _flatten_pages(value):
    if not isinstance(value, list):
        return [value]
    flattened = []
    for item in value:
        if isinstance(item, list):
            flattened.extend(_flatten_pages(item))
        else:
            flattened.append(item)
    return flattened


def run_github_pages(locator: dict, endpoint: str) -> list:
    """Read every page from an array endpoint."""
    value = run_github_json(locator, endpoint, paginate=True)
    return _flatten_pages(value)


def run_github_post(locator: dict, endpoint: str, payload: dict):
    """Submit one JSON request through the selected GitHub transport."""
    if _auth_mode() == "token":
        return _rest_request(locator, endpoint, method="POST", payload=payload)

    command = ["gh", "api", "--hostname", locator["host"],
               "--method", "POST", "--header", "Accept: application/vnd.github+json"]
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as body_file:
        body_file.write(json.dumps(payload, ensure_ascii=False))
        body_path = Path(body_file.name)
    try:
        command.extend(["--input", str(body_path), endpoint.lstrip("/")])
        try:
            result = subprocess.run(command, check=False, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace")
        except FileNotFoundError as exc:
            raise RuntimeError("GitHub CLI (`gh`) is required in CLI mode; install it and authenticate with `gh auth login`, or set GITHUB_AUTH_MODE=token and GITHUB_TOKEN.") from exc
        if result.returncode:
            detail = result.stderr.strip() or "GitHub rejected the review request"
            raise RuntimeError(detail[:1200])
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("GitHub CLI returned invalid JSON after the review request") from exc
    finally:
        body_path.unlink(missing_ok=True)


def extract_jira_key(*values: str) -> str | None:
    for value in values:
        match = JIRA_KEY_RE.search(value or "")
        if match:
            return match.group(0)
    return None


def pull_endpoint(locator: dict) -> str:
    return f"repos/{locator['owner']}/{locator['repo']}/pulls/{locator['number']}"


def load_pr_data(pr_url: str) -> dict:
    """Fetch PR metadata and all API-exposed changed-file patches."""
    locator = parse_pr_locator(pr_url)
    endpoint = pull_endpoint(locator)
    metadata = run_github_json(locator, endpoint)
    files_endpoint = f"{endpoint}/files?per_page=100"
    files = run_github_pages(locator, files_endpoint)
    changed_files = int(metadata.get("changed_files") or 0)
    base = metadata.get("base") or {}
    head = metadata.get("head") or {}
    diffs = []
    for item in files:
        patch = item.get("patch") or ""
        status = item.get("status", "modified")
        path = item.get("filename", "")
        diffs.append({
            "old_path": item.get("previous_filename") or path,
            "new_path": path,
            "status": status,
            "new_file": status == "added",
            "deleted_file": status == "removed",
            "renamed_file": status == "renamed",
            "additions": int(item.get("additions") or 0),
            "deletions": int(item.get("deletions") or 0),
            "diff": patch,
            "patch_unavailable": not bool(patch),
        })
    description = metadata.get("body") or ""
    title = metadata.get("title") or ""
    return {
        "pr": {
            **locator,
            "title": title,
            "author": (metadata.get("user") or {}).get("login", ""),
            "source_branch": head.get("ref", ""),
            "target_branch": base.get("ref", ""),
            "description": description,
            "web_url": metadata.get("html_url", locator["url"]),
            "jira_key": extract_jira_key(title, description),
            "changed_files": changed_files,
        },
        "version": {"base_sha": base.get("sha", ""), "head_sha": head.get("sha", "")},
        "diffs": diffs,
        "coverage": {
            "files_returned": len(diffs),
            "files_reported": changed_files,
            "complete": len(diffs) >= changed_files,
            "patches_unavailable": [item["new_path"] for item in diffs if item["patch_unavailable"]],
            "note": ("GitHub's pull request files API returns at most 3,000 files."
                     if changed_files > 3000 else ""),
        },
    }
