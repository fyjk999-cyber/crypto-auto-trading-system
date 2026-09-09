"""Public document-package contract, not trading/runtime acceptance."""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs" / "ai-native-remediation"


class PackageContract(unittest.TestCase):
    def test_local_document_links_resolve(self):
        for path in DOCS.rglob("*.md"):
            for target in re.findall(r"\]\(([^)]+)\)", path.read_text()):
                if "://" in target or target.startswith("#"):
                    continue
                self.assertTrue((path.parent / target.split("#")[0]).exists(),
                                f"{path.name}: {target}")

    def test_findings_are_covered_by_acceptance_matrix(self):
        findings = set(re.findall(r"\| (F\d{2}) \|",
                                 (DOCS / "FINDINGS_REGISTER.md").read_text()))
        matrix = (DOCS / "ACCEPTANCE_MATRIX.md").read_text()
        self.assertEqual(len(findings), 37)
        for finding in findings:
            self.assertIn(finding, matrix)
        for number in range(12):
            self.assertIn(f"W{number + 1:02d}", matrix)

    def test_five_public_schemas_exist(self):
        for name in ("review-request", "review-result", "harness-status",
                     "harness-checkpoint", "recovery-event"):
            schema = json.loads((DOCS / "schemas" / (name + ".schema.json")).read_text())
            self.assertFalse(schema["additionalProperties"])
            self.assertTrue(schema["required"])

    def test_all_chapters_have_handoff_contract(self):
        manifest = json.loads((DOCS / "manifest.json").read_text())
        self.assertEqual([c["id"] for c in manifest["chapters"]],
                         [f"{i:02d}" for i in range(16)])
        for chapter in manifest["chapters"]:
            text = (DOCS / chapter["file"]).read_text()
            for heading in ("目标", "允许修改", "实施任务", "测试", "证据", "Codex", "回滚"):
                self.assertIn(heading, text, chapter["id"])


if __name__ == "__main__":
    unittest.main()
