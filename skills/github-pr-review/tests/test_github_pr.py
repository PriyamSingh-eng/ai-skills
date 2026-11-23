import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from github_pr import (
    extract_jira_key, load_config_env, load_pr_data, parse_pr_locator,
    parse_pr_url, run_github_json, _rest_api_base,
)


class GitHubPrTests(unittest.TestCase):
    def test_parse_public_pull_request_url(self):
        parsed = parse_pr_url("https://github.com/acme/payments/pull/123?tab=files")
        self.assertEqual((parsed["owner"], parsed["repo"], parsed["number"]), ("acme", "payments", 123))
        self.assertEqual(parsed["host"], "github.com")

    def test_parse_enterprise_locator(self):
        parsed = parse_pr_locator("https://git.example.org/team/payments/pull/9")
        self.assertEqual(parsed["host"], "git.example.org")
        self.assertEqual(parsed["number"], 9)

    def test_reject_non_pr_url(self):
        with self.assertRaises(ValueError):
            parse_pr_url("https://github.com/acme/payments/issues/3")

    @patch.dict("os.environ", {"GITHUB_API_URL": "https://api.github.com"}, clear=True)
    def test_direct_rest_accepts_public_github_api_url(self):
        locator = parse_pr_locator("acme/payments#1")
        self.assertEqual(_rest_api_base(locator), "https://api.github.com")

    def test_load_config_env_preserves_existing_environment(self):
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "review.env"
            config.write_text('GITHUB_TOKEN="file-token"\nJIRA_BASE_URL=https://jira.example\n', encoding="utf-8")
            with patch.dict(os.environ, {"GITHUB_PR_REVIEW_ENV_FILE": str(config), "GITHUB_TOKEN": "process-token"}, clear=True):
                load_config_env()
                self.assertEqual(os.environ["GITHUB_TOKEN"], "process-token")
                self.assertEqual(os.environ["JIRA_BASE_URL"], "https://jira.example")

    def test_extract_jira_key(self):
        self.assertEqual(extract_jira_key("Fix retry ABC-1234", ""), "ABC-1234")
        self.assertIsNone(extract_jira_key("No linked work item"))

    @patch.dict("os.environ", {"GITHUB_AUTH_MODE": "token", "GITHUB_TOKEN": "test-token"})
    @patch("github_pr.urlopen")
    def test_direct_rest_uses_bearer_token_without_gh(self, urlopen):
        class Response:
            headers = {}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b'{"title":"Example"}'

        urlopen.return_value = Response()
        result = run_github_json(parse_pr_locator("acme/payments#1"), "repos/acme/payments/pulls/1")
        request = urlopen.call_args.args[0]
        self.assertEqual(result["title"], "Example")
        self.assertEqual(request.unredirected_hdrs.get("Authorization"), "Bearer test-token")
        self.assertIn("api.github.com/repos/acme/payments/pulls/1", request.full_url)

    @patch.dict("os.environ", {"GITHUB_AUTH_MODE": "token", "GITHUB_TOKEN": "test-token"})
    def test_direct_rest_rejects_unconfigured_enterprise_host(self):
        with self.assertRaisesRegex(RuntimeError, "GITHUB_ENTERPRISE_HOSTS"):
            run_github_json(parse_pr_locator("https://git.example.org/team/payments/pull/1"), "repos/team/payments/pulls/1")

    @patch("github_pr.run_github_pages")
    @patch("github_pr.run_github_json")
    def test_load_pr_data_schema(self, get_json, get_pages):
        get_json.return_value = {
            "title": "Fix retry ABC-22", "body": "Description", "html_url": "https://github.com/a/b/pull/2",
            "user": {"login": "dev"}, "base": {"ref": "main", "sha": "base"},
            "head": {"ref": "topic", "sha": "head"}, "changed_files": 1,
        }
        get_pages.return_value = [{"filename": "src/a.py", "status": "modified",
                                  "additions": 1, "deletions": 1, "patch": "@@ -1 +1 @@\n-a\n+b"}]
        result = load_pr_data("https://github.com/a/b/pull/2")
        self.assertEqual(result["pr"]["jira_key"], "ABC-22")
        self.assertEqual(result["version"]["head_sha"], "head")
        self.assertTrue(result["coverage"]["complete"])
        self.assertEqual(result["diffs"][0]["new_path"], "src/a.py")


if __name__ == "__main__":
    unittest.main()
