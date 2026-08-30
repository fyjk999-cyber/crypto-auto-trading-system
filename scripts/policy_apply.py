"""Internal governance service for the bounded runtime policy (Phase 2).

This is the ONLY sanctioned mutation path for the hot-reloadable runtime
policy (directive §29): harness calibration invokes this CLI; there is
deliberately NO public HTTP mutation route.

Usage:
  python scripts/policy_apply.py status
  python scripts/policy_apply.py apply --set per_symbol_analysis_cooldown_s=300 \
      --reason "CONTRACT window 17: TRX churn trigger" --changed-by calibration-cron \
      --calibration-window "2026-08-30T02:30Z"
  python scripts/policy_apply.py rollback --version 3 --changed-by calibration-cron
  python scripts/policy_apply.py verify --timeout 90

apply returns APPLIED (runtime confirmed the new version) / STAGED (row
written; runtime pickup not yet observed) / REJECTED (bounds violated).
verify (§31) fails (exit 2) when the next DecisionEvidence does not carry the
new policy_version within the timeout -> CALIBRATION_APPLY=FAIL.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from crypto_trader.config import Settings  # noqa: E402
from crypto_trader.governance.runtime_policy import (  # noqa: E402
    POLICY_PARAM_BOUNDS,
    RuntimePolicyManager,
)
from crypto_trader.persistence.database import Database  # noqa: E402


async def _build_manager() -> RuntimePolicyManager:
    settings = Settings()
    database = Database(settings.database_url)
    manager = RuntimePolicyManager(database.session_factory, audit=None)
    await manager.initialize()
    return manager


def _parse_set_args(pairs: list[str]) -> dict:
    changes: dict = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise SystemExit(f"--set expects key=value, got {pair!r}")
        key, _, value = pair.partition("=")
        if key not in POLICY_PARAM_BOUNDS:
            raise SystemExit(
                f"FORBIDDEN_OR_UNKNOWN param {key!r}; allowed: {sorted(POLICY_PARAM_BOUNDS)}"
            )
        changes[key] = value
    return changes


async def cmd_status() -> int:
    manager = await _build_manager()
    snap = manager.snapshot
    print(json.dumps({
        "active_version": snap.version,
        "active_since": snap.active_since,
        "parameters": snap.params,
        "reason": snap.reason,
    }, indent=2, default=str))
    return 0


async def cmd_apply(args) -> int:
    changes = _parse_set_args(args.set)
    manager = await _build_manager()
    result = await manager.apply_update(
        changes,
        reason=args.reason,
        changed_by=args.changed_by,
        calibration_window=args.calibration_window,
    )
    print(json.dumps({
        "status": result.status,
        "version": result.version,
        "errors": result.errors,
        "detail": result.detail,
    }, indent=2))
    return 0 if result.ok else 1


async def cmd_rollback(args) -> int:
    manager = await _build_manager()
    result = await manager.rollback(int(args.version), changed_by=args.changed_by)
    print(json.dumps({
        "status": result.status,
        "version": result.version,
        "errors": result.errors,
        "detail": result.detail,
    }, indent=2))
    return 0 if result.ok else 1


async def cmd_verify(args) -> int:
    """§31 CALIBRATION_APPLY verification: a NEW DecisionEvidence must carry
    the current policy_version."""
    manager = await _build_manager()
    version = manager.snapshot.version if manager.snapshot else None
    if version is None:
        print("CALIBRATION_APPLY=FAIL (no policy snapshot)")
        return 2
    from sqlalchemy import text

    deadline = asyncio.get_running_loop().time() + float(args.timeout)
    while asyncio.get_running_loop().time() < deadline:
        async with manager.session_factory() as session:
            row = (
                await session.execute(
                    text(
                        "SELECT decision_id, timestamp_utc, analysis_evidence_json "
                        "FROM decision_evidence ORDER BY id DESC LIMIT 1"
                    )
                )
            ).first()
        if row is not None:
            evidence = row[2] if isinstance(row[2], dict) else json.loads(row[2] or "{}")
            if str(evidence.get("policy_version") or "") == str(version):
                print(json.dumps({
                    "CALIBRATION_APPLY": "PASS",
                    "policy_version": version,
                    "decision_id": row[0],
                    "decision_at": row[1],
                }))
                return 0
        await asyncio.sleep(5.0)
    print(json.dumps({
        "CALIBRATION_APPLY": "FAIL",
        "policy_version": version,
        "note": f"no DecisionEvidence with policy_version={version} within {args.timeout}s",
    }))
    return 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    p_apply = sub.add_parser("apply")
    p_apply.add_argument(
        "--set", action="append", required=True,
        help="key=value; repeat for multiple params (allowlist enforced)",
    )
    p_apply.add_argument("--reason", required=True)
    p_apply.add_argument("--changed-by", required=True)
    p_apply.add_argument("--calibration-window", default=None)
    p_roll = sub.add_parser("rollback")
    p_roll.add_argument("--version", required=True)
    p_roll.add_argument("--changed-by", required=True)
    p_verify = sub.add_parser("verify")
    p_verify.add_argument("--timeout", default="90")
    args = parser.parse_args()

    handlers = {
        "status": cmd_status,
        "apply": cmd_apply,
        "rollback": cmd_rollback,
        "verify": cmd_verify,
    }
    return asyncio.run(handlers[args.cmd](args))


if __name__ == "__main__":
    raise SystemExit(main())
