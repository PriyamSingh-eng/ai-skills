import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from stack_detect import classify_file, detect_stacks


class StackDetectTests(unittest.TestCase):
    def test_classifies_supported_stacks(self):
        self.assertEqual(classify_file("src/main/java/PaymentService.java"), "java-springboot")
        self.assertEqual(classify_file("frontend/src/App.tsx"), "react-ui")
        self.assertEqual(classify_file("backend/app/api.py"), "python")
        self.assertEqual(classify_file("skills/review/SKILL.md"), "skill-authoring")

    def test_shared_config_follows_dominant_stack(self):
        result = detect_stacks([
            {"new_path": "service/Payment.java"},
            {"new_path": "service/PaymentTest.java"},
            {"new_path": "application.yml"},
        ])
        self.assertEqual(result["dominant_stack"], "java-springboot")
        self.assertEqual(result["stack_files"]["java-springboot"],
                         ["application.yml", "service/Payment.java", "service/PaymentTest.java"])

    def test_unknown_only_changes_use_general_pass(self):
        result = detect_stacks([{"new_path": "infra/main.tf"}, {"new_path": "README.md"}])
        self.assertEqual(result["matched_stacks"], ["general"])
        self.assertTrue(result["inconclusive"])

    def test_skill_resources_group_with_skill_stack(self):
        result = detect_stacks([
            {"new_path": "skills/foo/SKILL.md"},
            {"new_path": "skills/foo/references/api.md"},
        ])
        self.assertIn("skill-authoring", result["matched_stacks"])
        self.assertEqual(result["skill_names"], {"skills/foo/SKILL.md": "foo"})
        self.assertIn("skills/foo/references/api.md", result["stack_files"]["skill-authoring"])


if __name__ == "__main__":
    unittest.main()
