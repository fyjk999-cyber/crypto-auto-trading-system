"""Runtime hot-reloadable bounded PAPER policy (directive Phase 2, §19-§33).

AI-FIRST, QUANT-AS-EVIDENCE authority map preserved:

* This store holds ONLY bounded, online-adjustable decision-tempo / budget
  parameters (the "RuntimePaperPolicy"). Calibration may move them inside
  MIN/MAX/MAX_CHANGE_PER_WINDOW; the trading runtime hot-applies new versions
  at safe engine checkpoints WITHOUT restart.
* Safety parameters are FORBIDDEN here forever (§22): risk limits, kill
  switch, execution checks, leverage safety, data freshness requirements,
  duplicate prevention, reconciliation and lease behaviour are NOT AI policy
  and are NOT adjustable through this layer. They live exclusively in
  Settings + RiskEngine + ExecutionAuthority.
* Truth source is this DB table (§23). ``.ai-memory/PAPER_POLICY_STATE.md``
  is a REPORT, never runtime truth.
* Every update is versioned (§24) and applied atomically (§25): a single
  INSERT commits the whole parameter set; readers swap an immutable snapshot
  in one reference assignment, so no reader can observe a half-applied set.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

logger = logging.getLogger("crypto_trader.runtime_policy")


class PolicyParamError(ValueError):
    """A proposed parameter value violates the bounded policy contract."""


# §21: the ONLY parameters allowed online. Bounds mirror
# .ai-memory/PAPER_POLICY_STATE.md (report) and MAX_CHANGE is per update step
# within one 30m calibration window.
POLICY_PARAM_BOUNDS: dict[str, dict[str, Any]] = {
    "market_observer_candidate_target": {
        "min": 3, "max": 20, "max_change": 2, "type": "int", "default": 5,
    },
    "deep_analysis_candidate_limit": {
        "min": 3, "max": 12, "max_change": 2, "type": "int", "default": 5,
    },
    "per_symbol_analysis_cooldown_s": {
        "min": 60.0, "max": 900.0, "max_change": 60.0, "type": "float",
        "default": 240.0,
    },
    "reversal_cooldown_s": {
        "min": 60.0, "max": 900.0, "max_change": 60.0, "type": "float",
        "default": 240.0,
    },
    "memory_retrieval_limit": {
        "min": 3, "max": 12, "max_change": 2, "type": "int", "default": 5,
    },
    "history_context_depth": {
        "min": 1, "max": 10, "max_change": 2, "type": "int", "default": 3,
    },
    "research_budget_per_window": {
        "min": 0, "max": 6, "max_change": 1, "type": "int", "default": 2,
    },
    "tool_call_budget_per_decision": {
        "min": 2, "max": 12, "max_change": 2, "type": "int", "default": 6,
    },
    "paper_exploration_probability": {
        "min": 0.0, "max": 0.30, "max_change": 0.05, "type": "float",
        "default": 0.10,
    },
    "paper_exploration_size": {
        "min": "0.0001", "max": "0.001", "max_change": "0.0001",
        "type": "decimal", "default": "0.0005",
    },
    "max_paper_concurrent_positions": {
        "min": 4, "max": 16, "max_change": 2, "type": "int", "default": 8,
    },
}

MAX_CHANGE_WINDOW_SECONDS = 30 * 60.0


def default_params() -> dict[str, Any]:
    return {name: spec["default"] for name, spec in POLICY_PARAM_BOUNDS.items()}


def _coerce(name: str, value: Any) -> Any:
    spec = POLICY_PARAM_BOUNDS[name]
    try:
        if spec["type"] == "int":
            return int(Decimal(str(value)))
        if spec["type"] == "float":
            return float(Decimal(str(value)))
        if spec["type"] == "decimal":
            return str(Decimal(str(value)))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise PolicyParamError(f"{name}: value {value!r} is not numeric") from exc
    raise PolicyParamError(f"{name}: unknown param type {spec['type']}")


def validate_update(
    changes: dict[str, Any],
    current_params: dict[str, Any],
    window_history: list[tuple[float, dict[str, Any]]],
) -> list[str]:
    """§27 validation. Returns a list of violation strings; empty = valid.

    ``window_history`` is the ordered [(unix_ts, params)] of versions applied
    within the change window (oldest first). MAX_CHANGE is enforced BOTH per
    single step (proposed vs current) and cumulatively across the window
    (proposed vs the oldest value in the window).
    """
    errors: list[str] = []
    unknown = set(changes) - set(POLICY_PARAM_BOUNDS)
    if unknown:
        # §22 fail-closed: anything outside the allowlist is refused —
        # especially safety parameters that must never be hot-modified.
        errors.append(
            "FORBIDDEN_OR_UNKNOWN_PARAMS: "
            + ",".join(sorted(unknown))
            + " (safety parameters are never AI policy, §22)"
        )
        # drop them from further checks to avoid KeyErrors below
        changes = {k: v for k, v in changes.items() if k in POLICY_PARAM_BOUNDS}
    window_oldest = window_history[0][1] if window_history else current_params
    for name, raw in changes.items():
        spec = POLICY_PARAM_BOUNDS[name]
        try:
            value = _coerce(name, raw)
        except PolicyParamError as exc:
            errors.append(str(exc))
            continue
        lo, hi = spec["min"], spec["max"]
        if spec["type"] == "decimal":
            if not (Decimal(str(lo)) <= Decimal(str(value)) <= Decimal(str(hi))):
                errors.append(f"{name}: {value} outside [{lo}, {hi}]")
                continue
            current = Decimal(str(current_params.get(name, spec["default"])))
            oldest = Decimal(str(window_oldest.get(name, spec["default"])))
            step = abs(Decimal(str(value)) - current)
            drift = abs(Decimal(str(value)) - oldest)
            cap = Decimal(str(spec["max_change"]))
        else:
            if not (lo <= value <= hi):
                errors.append(f"{name}: {value} outside [{lo}, {hi}]")
                continue
            current = _coerce(name, current_params.get(name, spec["default"]))
            oldest = _coerce(name, window_oldest.get(name, spec["default"]))
            step = abs(value - current)
            drift = abs(value - oldest)
            cap = spec["max_change"]
        if step > cap:
            errors.append(
                f"{name}: single-step change {step} exceeds MAX_CHANGE {cap}"
            )
        if window_history and drift > cap:
            errors.append(
                f"{name}: cumulative change {drift} within "
                f"{int(MAX_CHANGE_WINDOW_SECONDS / 60)}m window exceeds "
                f"MAX_CHANGE {cap}"
            )
    return errors


@dataclass(frozen=True)
class RuntimePolicySnapshot:
    """Immutable parameter snapshot (§25 atomic apply)."""

    version: int
    params: dict[str, Any]
    active_since: str
    source: str = "runtime_policy"
    reason: str = ""

    def get(self, name: str) -> Any:
        fallback = POLICY_PARAM_BOUNDS.get(name, {}).get("default")
        return self.params.get(name, fallback)


@dataclass
class ApplyResult:
    status: str  # APPLIED / REJECTED / ROLLED_BACK / STAGED
    version: int | None
    errors: list[str] = field(default_factory=list)
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status in ("APPLIED", "ROLLED_BACK", "STAGED")


class RuntimePolicyManager:
    """Hot-reload access point. Consumers read an immutable snapshot; the
    manager swaps the snapshot atomically when the DB version changes."""

    def __init__(
        self,
        session_factory,
        audit=None,
        check_interval_seconds: float = 5.0,
        clock=None,
    ) -> None:
        self.session_factory = session_factory
        self.audit = audit
        self.check_interval_seconds = max(1.0, float(check_interval_seconds))
        self.clock = clock or (lambda: datetime.now(UTC))
        self._snapshot: RuntimePolicySnapshot | None = None
        self._last_check_mono: float = 0.0
        self._last_known_version: int | None = None

    # ------------------------------------------------------------- snapshot
    @property
    def snapshot(self) -> RuntimePolicySnapshot | None:
        return self._snapshot

    def get(self, name: str) -> Any:
        snap = self._snapshot
        if snap is None:
            spec = POLICY_PARAM_BOUNDS.get(name)
            return spec["default"] if spec else None
        return snap.get(name)

    def param(self, name: str, cast=float) -> Any:
        value = self.get(name)
        try:
            return cast(value)
        except (TypeError, ValueError):
            return value

    # ----------------------------------------------------------- bootstrap
    async def initialize(self) -> RuntimePolicySnapshot:
        """Load the active version; bootstrap a baseline row when empty."""
        from sqlalchemy import text

        async with self.session_factory() as session:
            row = (
                await session.execute(
                    text(
                        "SELECT version, params_json, created_at, reason FROM "
                        "runtime_policy ORDER BY version DESC LIMIT 1"
                    )
                )
            ).first()
        if row is None:
            params = default_params()
            await self._insert_version(
                version=1,
                params=params,
                reason="bootstrap baseline from Settings defaults",
                changed_by="bootstrap",
                calibration_window=None,
                rollback_of=None,
            )
            version, stored, created_at, reason = 1, params, None, "bootstrap"
        else:
            version, stored, created_at, reason = row
        stored = self._decode_params(stored)
        merged: dict[str, Any] = {**default_params(), **stored}
        self._snapshot = RuntimePolicySnapshot(
            version=int(version),
            params=merged,
            active_since=str(created_at or self.clock().isoformat()),
            reason=str(reason or ""),
        )
        self._last_known_version = int(version)
        return self._snapshot

    # ---------------------------------------------------------- hot reload
    async def maybe_check(self, force: bool = False) -> bool:
        """§26: cheap throttled version check at a safe checkpoint. Returns
        True when a new version was hot-applied. Never raises into trading."""
        now_mono = time.monotonic()
        if not force and now_mono - self._last_check_mono < self.check_interval_seconds:
            return False
        self._last_check_mono = now_mono
        try:
            from sqlalchemy import text

            async with self.session_factory() as session:
                row = (
                    await session.execute(
                        text(
                            "SELECT version, params_json, created_at, reason FROM "
                            "runtime_policy ORDER BY version DESC LIMIT 1"
                        )
                    )
                ).first()
            if row is None:
                return False
            version = int(row[0])
            if self._last_known_version is not None and version == self._last_known_version:
                return False
            params = {**default_params(), **self._decode_params(row[1])}
            previous = self._snapshot
            self._snapshot = RuntimePolicySnapshot(
                version=version,
                params=params,
                active_since=str(row[2] or self.clock().isoformat()),
                reason=str(row[3] or ""),
            )
            self._last_known_version = version
            logger.info(
                "POLICY_HOT_APPLIED version=%s previous=%s",
                version,
                previous.version if previous else None,
            )
            if self.audit is not None:
                try:
                    await self.audit.log(
                        "POLICY_HOT_APPLIED",
                        target=f"runtime_policy:v{version}",
                        before={"version": previous.version if previous else None},
                        after={"version": version, "params": params},
                    )
                except Exception:
                    pass
            return True
        except Exception:
            logger.warning("POLICY_CHECK_FAILED", exc_info=True)
            return False

    # ------------------------------------------------------------ mutation
    async def apply_update(
        self,
        changes: dict[str, Any],
        *,
        reason: str,
        changed_by: str,
        calibration_window: str | None = None,
        rollback_of: int | None = None,
    ) -> ApplyResult:
        if self._snapshot is None:
            await self.initialize()
        current_params = dict(self._snapshot.params)
        history = await self._window_history()
        errors = validate_update(dict(changes), current_params, history)
        if errors:
            if self.audit is not None:
                try:
                    await self.audit.log(
                        "POLICY_UPDATE_REJECTED",
                        target="runtime_policy",
                        before={"changes": changes},
                        after={"errors": errors},
                    )
                except Exception:
                    pass
            return ApplyResult("REJECTED", None, errors=errors)
        proposed = dict(current_params)
        for name, value in changes.items():
            proposed[name] = _coerce(name, value)
        version = (self._last_known_version or 0) + 1
        await self._insert_version(
            version=version,
            params=proposed,
            reason=reason[:255],
            changed_by=changed_by[:64],
            calibration_window=calibration_window,
            rollback_of=rollback_of,
        )
        applied = await self.maybe_check(force=True)
        status = "APPLIED" if applied else "STAGED"
        if rollback_of is not None:
            status = "ROLLED_BACK"
        return ApplyResult(
            status=status,
            version=version,
            detail=(
                f"version {version} written; runtime pickup "
                f"{'confirmed' if applied else 'pending'}"
            ),
        )

    async def rollback(self, to_version: int, *, changed_by: str) -> ApplyResult:
        from sqlalchemy import text

        async with self.session_factory() as session:
            row = (
                await session.execute(
                    text(
                        "SELECT params_json FROM runtime_policy WHERE version = :v"
                    ),
                    {"v": int(to_version)},
                )
            ).first()
        if row is None:
            return ApplyResult(
                "REJECTED", None, errors=[f"rollback target version {to_version} not found"]
            )
        params = self._decode_params(row[0])
        current_params = dict(self._snapshot.params) if self._snapshot else default_params()
        # Rollback restores an EXACT historical set: skip the max-change
        # validation (§28) but keep the allowlist coercion + bounds check.
        errors = validate_update(params, current_params, [])
        if errors:
            return ApplyResult("REJECTED", None, errors=errors)
        version = (self._last_known_version or 0) + 1
        await self._insert_version(
            version=version,
            params={**default_params(), **params},
            reason=f"rollback to v{to_version}",
            changed_by=changed_by[:64],
            calibration_window=None,
            rollback_of=int(to_version),
        )
        applied = await self.maybe_check(force=True)
        return ApplyResult(
            "ROLLED_BACK",
            version,
            detail=(
                f"restored v{to_version} as v{version}; pickup "
                f"{'confirmed' if applied else 'pending'}"
            ),
        )

    # ------------------------------------------------------------- storage
    async def _insert_version(
        self,
        *,
        version: int,
        params: dict[str, Any],
        reason: str,
        changed_by: str,
        calibration_window: str | None,
        rollback_of: int | None,
    ) -> None:
        from sqlalchemy import text

        # §25 atomic: ONE insert commits the WHOLE parameter set.
        now = datetime.now(UTC).replace(tzinfo=None)
        async with self.session_factory() as session:
            await session.execute(
                text(
                    "INSERT INTO runtime_policy (version, params_json, reason, "
                    "changed_by, calibration_window, rollback_of, created_at) "
                    "VALUES (:v, :p, :r, :c, :w, :ro, :ts)"
                ),
                {
                    "v": int(version),
                    "p": json.dumps(params),
                    "r": reason[:255],
                    "c": changed_by[:64],
                    "w": calibration_window,
                    "ro": rollback_of,
                    "ts": now,
                },
            )
            await session.commit()

    async def _window_history(self) -> list[tuple[float, dict[str, Any]]]:
        from sqlalchemy import text

        cutoff = time.time() - MAX_CHANGE_WINDOW_SECONDS
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    text(
                        "SELECT created_at, params_json FROM runtime_policy "
                        "ORDER BY version DESC LIMIT 64"
                    )
                )
            ).all()
        history: list[tuple[float, dict[str, Any]]] = []
        for created_at, params_json in rows:
            ts = _to_epoch(created_at)
            if ts is None or ts < cutoff:
                continue
            history.append((ts, self._decode_params(params_json)))
        history.sort(key=lambda item: item[0])
        return history

    @staticmethod
    def _decode_params(raw) -> dict[str, Any]:
        if isinstance(raw, dict):
            return dict(raw)
        try:
            decoded = json.loads(raw or "{}")
            return decoded if isinstance(decoded, dict) else {}
        except (TypeError, ValueError):
            return {}


def _to_epoch(value) -> float | None:
    # created_at is stored as naive UTC (SQLite convention); naive values
    # MUST be interpreted as UTC, not host-local, or the 30m change window
    # silently drops every row in UTC+X timezones.
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC).timestamp()
        return value.timestamp()
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        try:
            parsed = datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S.%f")
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC).timestamp()
    return parsed.timestamp()
