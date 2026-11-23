import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from merge_review_results import merge_results


class MergeReviewTests(unittest.TestCase):
    def test_merge_orders_findings_and_uses_conservative_summary(self):
        py = {
            "summary": "Python change", "risk_level": "High", "requirements_coverage": "Partial",
            "change_type": "bug fix", "verdict": "REQUEST CHANGES", "verdict_rationale": "Incorrect retry.",
            "findings": [{"id": 9, "severity": "P2", "type": "inline", "path": "a.py", "line": 8,
                          "side": "RIGHT", "comment_body": "Missing timeout."}],
            "questions_comment": "Is retry count intentional?",
        }
        java = {
            "summary": "Java change", "risk_level": "Critical", "requirements_coverage": "Covered",
            "change_type": "new feature", "verdict": "NEEDS DISCUSSION", "verdict_rationale": "Contract unclear.",
            "findings": [{"id": 1, "severity": "P0", "type": "general", "path": None, "line": None,
                          "side": None, "comment_body": "Exposes a secret."}],
            "questions_comment": "Will this be rotated?",
        }
        with tempfile.TemporaryDirectory() as temp:
            paths = []
            for name, data in (("python", py), ("java-springboot", java)):
                path = Path(temp) / f"{name}.json"
                import json
                path.write_text(json.dumps(data), encoding="utf-8")
                paths.append((name, str(path)))
            merged = merge_results(paths)
        self.assertEqual([item["severity"] for item in merged["findings"]], ["P0", "P2"])
        self.assertEqual([item["id"] for item in merged["findings"]], [1, 2])
        self.assertEqual(merged["risk_level"], "Critical")
        self.assertEqual(merged["verdict"], "REQUEST CHANGES")
        self.assertEqual(merged["change_type"], "mixed")
        self.assertIn("**python:**", merged["questions_comment"])


if __name__ == "__main__":
    unittest.main()
