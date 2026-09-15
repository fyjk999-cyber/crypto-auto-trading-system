"""Active Base Exit registry (Low-Risk V2 Phase 4C).

Every new entry has exactly one active Base Exit. Replacement is atomic:

  stage(new plan version)  -> old exit stays active
  activate(version)        -> new exit becomes active, old one deactivated

An activation bound to a stale position ``based_on_state_version`` (a fill,
partial fill, Fast Exit, Risk exit or other position change happened while the
LLM was thinking) is rejected as STALE_DECISION and can never execute.

The registry only decides *whether the pre-authorized exit is due*; the
canonical execution path and ExitCoordinator remain responsible for any order.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from crypto_trader.domain.identifiers import new_id

COMPARATORS = (">=", "<=", "==", ">", "<")


class StaleBaseExitError(ValueError):
    """Activation rejected because the factual position state moved on."""


@dataclass(slots=True)
class BaseExitVersion:
    leg_id: str
    plan_version: int
    exit_type: str
    trigger: str
    size_pct: float
    reason_code: str
    based_on_state_version: str
    version_id: str = field(default_factory=lambda: new_id("bx"))
    active: bool = False
    staged_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    activated_at: datetime | None = None
    superseded_at: datetime | None = None
    filled_at: datetime | None = None

    def as_dict(self) -> dict:
        return {
            "version_id": self.version_id,
            "leg_id": self.leg_id,
            "plan_version": self.plan_version,
            "exit_type": self.exit_type,
            "trigger": self.trigger,
            "size_pct": self.size_pct,
            "reason_code": self.reason_code,
            "based_on_state_version": self.based_on_state_version,
            "active": self.active,
            "staged_at": self.staged_at.isoformat(),
            "activated_at": self.activated_at.isoformat() if self.activated_at else None,
            "superseded_at": self.superseded_at.isoformat() if self.superseded_at else None,
            "filled_at": self.filled_at.isoformat() if self.filled_at else None,
        }


@dataclass(slots=True)
class BaseExitDecision:
    leg_id: str
    due: bool
    exit_pct: float
    reason_code: str
    version_id: str | None
    price: Decimal | None = None
    authority: str = "ACTIVE_BASE_EXIT"
    is_new_risk: bool = False
    detail: str = ""

    def as_dict(self) -> dict:
        return {
            "leg_id": self.leg_id,
            "due": self.due,
            "exit_pct": self.exit_pct,
            "reason_code": self.reason_code,
            "version_id": self.version_id,
            "price": str(self.price) if self.price is not None else None,
            "authority": self.authority,
            "is_new_risk": self.is_new_risk,
            "detail": self.detail,
        }


def _parse_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


class BaseExitRegistry:
    def __init__(
        self,
        *,
        condition_evaluator: Callable[..., Any] | None = None,
    ) -> None:
        # Optional runtime-injected evaluator for INDICATOR/EVENT conditions.
        self.condition_evaluator = condition_evaluator
        self.versions: dict[str, BaseExitVersion] = {}
        self.by_leg: dict[str, list[str]] = {}
        self.closed_legs: set[str] = set()
        self.events: list[dict] = []

    # ------------------------------------------------------------------ stage
    def stage(
        self,
        leg_id: str,
        *,
        plan_version: int,
        exit_type: str,
        trigger: str,
        size_pct: float = 100.0,
        reason_code: str = "BASE_EXIT",
        based_on_state_version: str,
    ) -> BaseExitVersion:
        if size_pct <= 0 or size_pct > 100:
            raise ValueError("Base Exit size_pct must be in (0, 100]")
        version = BaseExitVersion(
            leg_id=leg_id,
            plan_version=int(plan_version),
            exit_type=str(exit_type).upper(),
            trigger=str(trigger),
            size_pct=float(size_pct),
            reason_code=reason_code,
            based_on_state_version=based_on_state_version,
        )
        self.versions[version.version_id] = version
        self.by_leg.setdefault(leg_id, []).append(version.version_id)
        self._event("BASE_EXIT_STAGED", version)
        return version

    def activate(
        self,
        version_id: str,
        *,
        factual_state_version: str,
        now: datetime | None = None,
    ) -> BaseExitVersion:
        """Atomically replace the active exit; reject stale LLM plans."""
        moment = now or datetime.now(UTC)
        version = self._require(version_id)
        if version.filled_at is not None:
            raise StaleBaseExitError("STALE_DECISION: exit version already filled")
        if version.leg_id in self.closed_legs:
            raise StaleBaseExitError(
                "STALE_DECISION: leg already closed by a factual exit fill"
            )
        if factual_state_version != version.based_on_state_version:
            self._event(
                "BASE_EXIT_STALE_REJECTED",
                version,
                detail=f"factual={factual_state_version} based_on={version.based_on_state_version}",
            )
            raise StaleBaseExitError(
                "STALE_DECISION: position state changed after this plan was built"
            )
        previous = self.active(version.leg_id)
        if previous is not None and previous.version_id != version.version_id:
            previous.active = False
            previous.superseded_at = moment
        version.active = True
        version.activated_at = moment
        self._event("BASE_EXIT_ACTIVATED", version, detail="atomic replacement")
        return version

    def active(self, leg_id: str) -> BaseExitVersion | None:
        for version_id in self.by_leg.get(leg_id, []):
            version = self.versions[version_id]
            if version.active:
                return version
        return None

    def mark_filled(self, leg_id: str, *, now: datetime | None = None) -> BaseExitVersion | None:
        """Record that the factual position closed via the active exit."""
        moment = now or datetime.now(UTC)
        version = self.active(leg_id)
        if version is None:
            return None
        version.active = False
        version.filled_at = moment
        self.closed_legs.add(leg_id)
        self._event("BASE_EXIT_FILLED", version)
        return version

    def reopen_leg(self, leg_id: str) -> None:
        """New factual position episode on the same leg id (e.g. re-entry)."""
        self.closed_legs.discard(leg_id)

    # ---------------------------------------------------------------- evaluate
    def evaluate(
        self,
        leg_id: str,
        *,
        now: datetime | None = None,
        price: Decimal | None = None,
        anchor_time: datetime | None = None,
        indicators: dict | None = None,
        events: list | None = None,
    ) -> BaseExitDecision:
        version = self.active(leg_id)
        if version is None:
            return BaseExitDecision(
                leg_id=leg_id,
                due=False,
                exit_pct=0.0,
                reason_code="NO_ACTIVE_BASE_EXIT",
                version_id=None,
            )
        due, detail = self._evaluate_trigger(
            version,
            now=now,
            price=price,
            anchor_time=anchor_time,
            indicators=indicators or {},
            events=events or [],
        )
        if not due:
            return BaseExitDecision(
                leg_id=leg_id,
                due=False,
                exit_pct=0.0,
                reason_code="BASE_EXIT_NOT_TRIGGERED",
                version_id=version.version_id,
                price=price,
                detail=detail,
            )
        return BaseExitDecision(
            leg_id=leg_id,
            due=True,
            exit_pct=version.size_pct,
            reason_code=version.reason_code,
            version_id=version.version_id,
            price=price,
            detail=detail,
        )

    # --------------------------------------------------------------- internals
    def _evaluate_trigger(
        self,
        version: BaseExitVersion,
        *,
        now: datetime | None,
        price: Decimal | None,
        anchor_time: datetime | None,
        indicators: dict,
        events: list,
    ) -> tuple[bool, str]:
        moment = now or datetime.now(UTC)
        kind = version.exit_type.upper()
        trigger = version.trigger
        if kind == "PRICE":
            if price is None:
                return False, "NO_PRICE"
            normalized = trigger.upper().replace("ABOVE", ">").replace("BELOW", "<").strip()
            for operator in COMPARATORS:
                if normalized.startswith(operator):
                    target = _parse_decimal(normalized[len(operator) :])
                    if target is None:
                        return False, "MALFORMED_TRIGGER"
                    return self._compare(price, operator, target), f"{operator}{target}"
            target = _parse_decimal(trigger)
            if target is None:
                return False, "MALFORMED_TRIGGER"
            tolerance = abs(target) * Decimal("0.0001")
            return abs(price - target) <= tolerance, f"touch {target}"
        if kind == "TIME":
            text = trigger.strip()
            if text.startswith("+") and text.endswith("s"):
                offset = _parse_decimal(text[1:-1])
                if offset is None or anchor_time is None:
                    return False, "MALFORMED_TRIGGER"
                return moment >= anchor_time + timedelta(seconds=float(offset)), "elapsed"
            try:
                target_time = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                return False, "MALFORMED_TRIGGER"
            if target_time.tzinfo is None:
                target_time = target_time.replace(tzinfo=UTC)
            return moment >= target_time, "clock reached"
        if self.condition_evaluator is not None:
            try:
                result = self.condition_evaluator(
                    type=kind,
                    value=trigger,
                    now=moment,
                    price=price,
                    indicators=indicators,
                    events=events,
                )
            except Exception:
                return False, "EVALUATOR_ERROR"
            if isinstance(result, tuple):
                return bool(result[0]), str(result[1]) if len(result) > 1 else ""
            return bool(result), ""
        return False, "NO_EVALUATOR_FOR_CONDITION"

    @staticmethod
    def _compare(left: Decimal, operator: str, right: Decimal) -> bool:
        if operator == ">=":
            return left >= right
        if operator == "<=":
            return left <= right
        if operator == ">":
            return left > right
        if operator == "<":
            return left < right
        return left == right

    def _require(self, version_id: str) -> BaseExitVersion:
        version = self.versions.get(version_id)
        if version is None:
            raise KeyError(f"unknown Base Exit version: {version_id}")
        return version

    def _event(self, event: str, version: BaseExitVersion, detail: str = "") -> None:
        self.events.append(
            {
                "event": event,
                "version_id": version.version_id,
                "leg_id": version.leg_id,
                "plan_version": version.plan_version,
                "at": datetime.now(UTC).isoformat(),
                "detail": detail,
            }
        )
