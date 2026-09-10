"""Independent isolated tests for review-request submission entry.

Uses temp dirs; never writes real runtime DB or starts Codex.
"""
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "remediation_review_submission.py"


def _import():
    import importlib.util

    spec = importlib.util.spec_from_file_location("remediation_review_submission", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ReviewSubmissionContract(unittest.TestCase):
    def test_duplicate_request_id_rejected(self):
        mod = _import()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".ops" / "ai-native-remediation").mkdir(parents=True)
            status = {
                "schema_version": 1,
                "harness_session_id": None,
                "process_identity": None,
                "chapter_id": "00",
                "work_state": "WAITING_FOR_USER",
                "last_model_event_at": None,
                "last_progress_at": None,
                "active_operation": None,
                "operation_deadline": None,
                "review_request_id": None,
                "last_supervision_at": "2026-09-09T00:00:00Z",
                "recovery_attempt_id": None,
                "recovery_count_1h": 0,
                "recovery_count_24h": 0,
                "last_recovery_result": None,
                "binding_verified": False,
                "recovery_enabled": False,
                "retry_after": None,
                "observations_without_progress": 0,
            }
            (root / ".ops" / "ai-native-remediation" / "status.json").write_text(
                json.dumps(status)
            )
            mod.REQUEST_DIR = root / ".ops" / "ai-native-remediation" / "requests"
            mod.STATUS_FILE = root / ".ops" / "ai-native-remediation" / "status.json"
            test = {
                "command_redacted": "isolated-test",
                "environment": "fixture",
                "exit_code": 0,
                "evidence": {
                    "path": ".ops/ai-native-remediation/submission.log",
                    "sha256": "a" * 64,
                    "complete": True,
                },
            }
            kwargs = dict(
                chapter_id="00",
                base_sha="a" * 40,
                candidate_sha="b" * 40,
                branch="codex/remediation-00-baseline",
                project_path=str(root),
                changed_files=["scripts/remediation_review_submission.py"],
                finding_ids=["F01"],
                tests=[test],
                migration_validation="not applicable",
                rollback="isolated test only",
                unverified_items=[],
                pre_existing_dirty=[],
                request_id="req-duplicate",
            )
            first = mod.create_request(**kwargs)
            self.assertTrue(first.exists())
            with self.assertRaises(FileExistsError):
                mod.create_request(**kwargs)

    def test_placeholder_test_evidence_rejected(self):
        mod = _import()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".ops" / "ai-native-remediation").mkdir(parents=True)
            (root / ".ops" / "ai-native-remediation" / "status.json").write_text(
                json.dumps(
                    {
                        "review_request_id": None,
                        "work_state": "WAITING_FOR_USER",
                        "last_progress_at": None,
                        "active_operation": None,
                        "last_supervision_at": "2026-09-09T00:00:00Z",
                    }
                )
            )
            mod.REQUEST_DIR = root / ".ops" / "ai-native-remediation" / "requests"
            mod.STATUS_FILE = root / ".ops" / "ai-native-remediation" / "status.json"
            with self.assertRaises(ValueError):
                mod.create_request(
                    chapter_id="00",
                    base_sha="a" * 40,
                    candidate_sha="b" * 40,
                    branch="codex/test",
                    project_path=str(root),
                    changed_files=[],
                    finding_ids=[],
                    tests=[
                        {
                            "command_redacted": "fake",
                            "environment": "fixture",
                            "exit_code": 0,
                            "evidence": {
                                "path": ".ops/ai-native-remediation/submission.log",
                                "sha256": "0" * 64,
                                "complete": True,
                            },
                        }
                    ],
                    migration_validation="not applicable",
                    rollback="none",
                    unverified_items=[],
                    pre_existing_dirty=[],
                )

    def test_invalid_sha_and_branch_rejected(self):
        mod = _import()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".ops" / "ai-native-remediation").mkdir(parents=True)
            (root / ".ops" / "ai-native-remediation" / "status.json").write_text(
                json.dumps(
                    {
                        "review_request_id": None,
                        "work_state": "WAITING_FOR_USER",
                        "last_progress_at": None,
                        "active_operation": None,
                        "last_supervision_at": "2026-09-09T00:00:00Z",
                    }
                )
            )
            mod.REQUEST_DIR = root / ".ops" / "ai-native-remediation" / "requests"
            mod.STATUS_FILE = root / ".ops" / "ai-native-remediation" / "status.json"
            with self.assertRaises(ValueError):
                mod.create_request(
                    chapter_id="00",
                    base_sha="bad",
                    candidate_sha="b" * 40,
                    branch="codex/test",
                    project_path=str(root),
                    changed_files=[],
                    finding_ids=[],
                    tests=[],
                    migration_validation="not applicable",
                    rollback="none",
                    unverified_items=[],
                    pre_existing_dirty=[],
                )


if __name__ == "__main__":
    unittest.main()
