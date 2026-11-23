import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from post_review_comments import added_lines, build_payload, validate_review


class PostReviewTests(unittest.TestCase):
    def setUp(self):
        self.pr_data = {
            "pr": {"host": "github.com", "owner": "acme", "repo": "shop", "number": 12},
            "version": {"head_sha": "abc123"},
            "diffs": [{"new_path": "src/app.py", "diff": "@@ -2,2 +2,3 @@\n context\n-old\n+new\n+added", "patch_unavailable": False}],
        }
        self.approved = {
            "approval": {"approved": True, "pr_url": "https://github.com/acme/shop/pull/12",
                         "head_sha": "abc123", "event": "COMMENT"},
            "review_body": "Review summary.",
            "findings": [{"id": 1, "type": "inline", "path": "src/app.py", "line": 4,
                           "comment_body": "This breaks validation."}],
            "questions_comment": "",
        }

    def test_collects_added_new_side_lines(self):
        patch_text = "@@ -2,2 +2,3 @@\n context\n-old\n+new\n+added"
        self.assertEqual(added_lines(patch_text), {3, 4})

    def test_validates_approved_inline_payload(self):
        locator, approval, comments, body, event = validate_review(self.pr_data, self.approved)
        self.assertEqual(locator["number"], 12)
        self.assertEqual(comments[0]["side"], "RIGHT")
        payload = build_payload(self.approved, comments, body, event, approval["head_sha"])
        self.assertEqual(payload["commit_id"], "abc123")

    def test_rejects_line_not_in_diff(self):
        self.approved["findings"][0]["line"] = 2
        with self.assertRaises(ValueError):
            validate_review(self.pr_data, self.approved)

    def test_rejects_missing_user_approval(self):
        self.approved["approval"]["approved"] = False
        with self.assertRaises(ValueError):
            validate_review(self.pr_data, self.approved)

    def test_general_finding_has_no_inline_anchor(self):
        self.approved["findings"] = [{"id": 1, "type": "general", "path": None, "line": None,
                                      "comment_body": "Please add an integration test."}]
        _, _, comments, body, _ = validate_review(self.pr_data, self.approved)
        self.assertEqual(comments, [])
        self.assertIn("General findings", body)


if __name__ == "__main__":
    unittest.main()
