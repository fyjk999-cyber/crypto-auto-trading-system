"""Independent positive/negative wire-contract examples, no real credentials/processes."""
import copy
import unittest

from check_remediation_schemas import valid

TS = "2026-09-09T00:00:00Z"
IDENTITY = {"pid": 123, "started_at": TS, "executable_path": "/test/harness",
            "project_path": "/test/project"}
SOURCE = {"thread_id": "codex-test", "turn_or_message_id": "turn-test",
          "output_sha256": "a" * 64}
EVIDENCE = {"path": ".ops/ai-native-remediation/drills/test.log",
            "sha256": "b" * 64, "complete": True}
TEST = {"command_redacted": "isolated-test", "environment": "fixture",
        "exit_code": 0, "evidence": EVIDENCE}
REQUEST = {"schema_version": 1, "project": "fyjk999-cyber/crypto-auto-trading-system",
           "request_id": "request-test", "chapter_id": "00", "base_sha": "a" * 40,
           "candidate_sha": "b" * 40, "created_at": TS, "project_path": "/test/project",
           "branch": "codex/test", "pre_existing_dirty": [], "changed_files": ["test.md"],
           "finding_ids": ["F01"], "tests": [TEST], "migration_validation": "not applicable",
           "rollback": "isolated test only", "unverified_items": [], "prior_approval": None,
           "state": "SUBMITTED"}
REVIEW = {"schema_version": 1, "request_id": "request-test", "chapter_id": "00",
          "reviewed_sha": "b" * 40, "reviewed_at": TS, "reviewer": "CODEX",
          "reviewer_source": SOURCE, "source_verified": True, "decision": "APPROVED",
          "independent_tests": [TEST], "findings": [], "missing_evidence": [],
          "next_chapter_allowed": "01", "runtime_authorized": False}
STATUS = {"schema_version": 1, "harness_session_id": None, "process_identity": None,
          "chapter_id": "00", "work_state": "WAITING_FOR_USER",
          "last_model_event_at": None, "last_progress_at": None, "active_operation": None,
          "operation_deadline": None, "review_request_id": None, "last_supervision_at": TS,
          "recovery_attempt_id": None, "recovery_count_1h": 0, "recovery_count_24h": 0,
          "last_recovery_result": None, "binding_verified": False, "recovery_enabled": False,
          "retry_after": None, "observations_without_progress": 0}
CHECKPOINT = {"schema_version": 1, "checkpoint_id": "checkpoint-test",
              "harness_session_id": "session-test", "process_identity": IDENTITY,
              "project_path": "/test/project", "chapter_id": "00", "head": "a" * 40,
              "recorded_at": TS, "dirty_files": [], "work_state": "WAITING_FOR_REVIEW",
              "active_operation": None, "operation_deadline": None,
              "operation_may_have_completed": False, "last_confirmed_action": "submitted",
              "test_progress": "completed", "review_request_id": "request-test",
              "last_verified_approval": None, "resume_step": "wait for actual review"}
RECOVERY = {"schema_version": 1, "attempt_id": "attempt-test",
            "harness_session_id": "session-test", "project_path": "/test/project",
            "old_process_identity": IDENTITY, "new_process_identity": IDENTITY,
            "reason_code": "MODEL_TIMEOUT", "checkpoint_id": "checkpoint-test",
            "started_at": TS, "finished_at": TS, "attempts_1h": 1, "attempts_24h": 1,
            "safe_stop_verified": True, "old_writer_exited": True,
            "entrypoint_reference": "isolated-test-fixture",
            "progress_evidence": EVIDENCE, "trading_runtime_untouched": True,
            "result": "RECOVERED"}


class SchemaContracts(unittest.TestCase):
    def test_valid_examples(self):
        for name, data in (("review-request", REQUEST), ("review-result", REVIEW),
                           ("harness-status", STATUS), ("harness-checkpoint", CHECKPOINT),
                           ("recovery-event", RECOVERY)):
            with self.subTest(name=name):
                self.assertTrue(valid(name, data))

    def test_missing_required_fields(self):
        for key in REQUEST:
            data = copy.deepcopy(REQUEST)
            del data[key]
            with self.subTest(key=key):
                self.assertFalse(valid("review-request", data))

    def test_unknown_secret_field_rejected(self):
        for name, original in (("review-request", REQUEST), ("review-result", REVIEW),
                               ("harness-status", STATUS), ("harness-checkpoint", CHECKPOINT),
                               ("recovery-event", RECOVERY)):
            data = copy.deepcopy(original)
            data["raw_environment"] = "DO_NOT_LOG_SENTINEL"
            self.assertFalse(valid(name, data))

    def test_approval_requires_independent_pass_and_complete_evidence(self):
        edits = [
            ("source_verified", False), ("independent_tests", []),
            ("missing_evidence", ["missing full output"]), ("runtime_authorized", True),
            ("reviewer", "HARNESS"),
        ]
        for key, value in edits:
            data = copy.deepcopy(REVIEW)
            data[key] = value
            self.assertFalse(valid("review-result", data))
        for key, value in (("exit_code", 1), ("evidence", {**EVIDENCE, "complete": False})):
            data = copy.deepcopy(REVIEW)
            data["independent_tests"][0][key] = value
            self.assertFalse(valid("review-result", data))

    def test_rejected_review_cannot_unlock_next_chapter(self):
        data = copy.deepcopy(REVIEW)
        data["decision"] = "CHANGES_REQUIRED"
        self.assertFalse(valid("review-result", data))
        data["next_chapter_allowed"] = None
        self.assertTrue(valid("review-result", data))

    def test_unbound_session_cannot_enable_recovery(self):
        data = copy.deepcopy(STATUS)
        data["recovery_enabled"] = True
        self.assertFalse(valid("harness-status", data))

    def test_success_needs_old_writer_exit_and_actual_progress(self):
        for key, value in (("old_writer_exited", False), ("safe_stop_verified", False),
                           ("progress_evidence", None), ("new_process_identity", None),
                           ("trading_runtime_untouched", False)):
            data = copy.deepcopy(RECOVERY)
            data[key] = value
            self.assertFalse(valid("recovery-event", data))

    def test_auth_failure_not_classified_as_restartable(self):
        data = copy.deepcopy(RECOVERY)
        data["reason_code"] = "AUTH_FAILED"
        self.assertFalse(valid("recovery-event", data))

    def test_invalid_timestamp_hash_chapter_and_log_path(self):
        for key, value in (("created_at", "not-time"), ("candidate_sha", "short"),
                           ("chapter_id", "99"), ("branch", "main")):
            data = copy.deepcopy(REQUEST)
            data[key] = value
            self.assertFalse(valid("review-request", data))
        data = copy.deepcopy(REQUEST)
        data["tests"][0]["evidence"]["path"] = "../../secret.log"
        self.assertFalse(valid("review-request", data))


if __name__ == "__main__":
    unittest.main()
