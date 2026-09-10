#!/usr/bin/env python3
"""Create and validate a Harness Chapter review submission.

This script only creates a durable review request in .ops/ai-native-remediation/.
It never creates approvals, starts Codex, or touches trading/runtime code.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUEST_DIR = ROOT / ".ops" / "ai-native-remediation" / "requests"
STATUS_FILE = ROOT / ".ops" / "ai-native-remediation" / "status.json"
SCHEMA_PATH = ROOT / "docs" / "ai-native-remediation" / "schemas" / "review-request.schema.json"

VALID_CHAPTER = re.compile(r"^(0[0-9]|1[0-5])$")
VALID_SHA = re.compile(r"^[a-f0-9]{40}$")


def load_status() -> dict:
    if not STATUS_FILE.exists():
        raise FileNotFoundError(STATUS_FILE)
    return json.loads(STATUS_FILE.read_text())


def validate(payload: dict) -> None:
    from jsonschema import Draft202012Validator

    schema = json.loads(SCHEMA_PATH.read_text())
    Draft202012Validator(schema).validate(payload)


def create_request(
    *,
    chapter_id: str,
    base_sha: str,
    candidate_sha: str,
    branch: str,
    project_path: str,
    changed_files: list[str],
    finding_ids: list[str],
    tests: list[dict],
    migration_validation: str,
    rollback: str,
    unverified_items: list[str],
    pre_existing_dirty: list[dict],
    request_id: str | None = None,
    supersedes_request_id: str | None = None,
) -> Path:
    if not VALID_CHAPTER.match(chapter_id):
        raise ValueError("chapter_id must be 00-15")
    if not VALID_SHA.match(base_sha) or not VALID_SHA.match(candidate_sha):
        raise ValueError("SHA must be 40 lowercase hex")
    if not branch.startswith("codex/"):
        raise ValueError("branch must begin with codex/")
    if not tests:
        raise ValueError("at least one test record required")
    for index, test in enumerate(tests):
        evidence = test.get("evidence") or {}
        digest = evidence.get("sha256")
        if (
            evidence.get("complete") is not True
            or not isinstance(digest, str)
            or re.fullmatch(r"[a-f0-9]{64}", digest) is None
            or digest == "0" * 64
        ):
            raise ValueError(
                f"test[{index}] requires complete evidence with real sha256"
            )
    request_id = request_id or f"req-{uuid.uuid4().hex}"
    payload = {
        "schema_version": 1,
        "project": "fyjk999-cyber/crypto-auto-trading-system",
        "request_id": request_id,
        "chapter_id": chapter_id,
        "base_sha": base_sha,
        "candidate_sha": candidate_sha,
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "project_path": str(project_path),
        "branch": branch,
        "pre_existing_dirty": pre_existing_dirty,
        "changed_files": changed_files,
        "finding_ids": finding_ids,
        "tests": tests,
        "migration_validation": migration_validation,
        "rollback": rollback,
        "unverified_items": unverified_items,
        "supersedes_request_id": supersedes_request_id,
        "prior_approval": None,
        "state": "SUBMITTED",
    }
    validate(payload)
    REQUEST_DIR.mkdir(parents=True, exist_ok=True)
    target = REQUEST_DIR / f"{request_id}.json"
    if target.exists():
        raise FileExistsError(f"duplicate request_id: {request_id}")
    target.write_text(json.dumps(payload, indent=2) + "\n")
    status = load_status()
    status["review_request_id"] = request_id
    status["work_state"] = "SUBMISSION_PENDING"
    status["last_progress_at"] = payload["created_at"]
    status["active_operation"] = "submit-review-request"
    STATUS_FILE.write_text(json.dumps(status, indent=2) + "\n")
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chapter", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--project-path", required=True)
    parser.add_argument("--changed-files", nargs="*", default=[])
    parser.add_argument("--finding-ids", nargs="*", default=[])
    parser.add_argument(
        "--tests-json",
        required=True,
        help="JSON file containing real test evidence records",
    )
    parser.add_argument("--migration-validation", required=True)
    parser.add_argument("--rollback", required=True)
    parser.add_argument("--unverified-items", nargs="*", default=[])
    parser.add_argument("--dirty", nargs="*", default=[])
    parser.add_argument("--supersedes-request-id", default=None)
    args = parser.parse_args()
    try:
        dirty = []
        for item in args.dirty:
            path, status = item.split("=", 1)
            dirty.append({"path": path, "status": status, "sha256": None})
        tests = json.loads(Path(args.tests_json).read_text())
        path = create_request(
            chapter_id=args.chapter,
            base_sha=args.base_sha,
            candidate_sha=args.candidate_sha,
            branch=args.branch,
            project_path=args.project_path,
            changed_files=args.changed_files,
            finding_ids=args.finding_ids,
            tests=tests,
            migration_validation=args.migration_validation,
            rollback=args.rollback,
            unverified_items=args.unverified_items,
            pre_existing_dirty=dirty,
            supersedes_request_id=args.supersedes_request_id,
        )
    except (ValueError, FileExistsError, FileNotFoundError, ImportError) as exc:
        print(f"SUBMISSION_FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"SUBMISSION_PENDING request={path.name} path={path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
