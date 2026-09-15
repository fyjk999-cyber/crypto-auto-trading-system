"""NEXT_REASSESSMENT evaluation (Low-Risk V2 Phase 4F).

The Core LLM may attach PRICE/TIME/INDICATOR/EVENT wake conditions with AND/OR
logic and NORMAL/HIGH/URGENT priority. These conditions only wake the Core
LLM; they are never orders, stops or risk limits. Existing Base/Risk/Fast
exits remain active independently.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from crypto_trader.llm_chief.invocation import InvocationPriority

PRIORITY_RANK = {
    "NORMAL": 0,
    "HIGH": 1,
    "URGENT": 2,
}


@dataclass(slots=True)
class ReassessmentWake:
    triggered: bool
    matched_conditions: list[str] = field(default_factory=list)
    unmatched_conditions: list[str] = field(default_factory=list)
    priority: InvocationPriority = InvocationPriority.NORMAL
    reason_codes: list[str] = field(default_factory=list)
    authority: str = "WAKE_LLM_ONLY"
    is_order: bool = False

    def as_dict(self) -> dict:
        return {
            "triggered": self.triggered,
            "matched_conditions": list(self.matched_conditions),
            "unmatched_conditions": list(self.unmatched_conditions),
            "priority": self.priority.value,
            "reason_codes": list(self.reason_codes),
            "authority": self.authority,
            "is_order": self.is_order,
        }


def _parse_number(text: str) -> Decimal | None:
    try:
        return Decimal(text.strip())
    except (InvalidOperation, ValueError):
        return None


def _compare(left: Decimal, operator: str, right: Decimal) -> bool:
    if operator in (">=", "=>"):
        return left >= right
    if operator == "<=":
        return left <= right
    if operator == ">":
        return left > right
    if operator == "<":
        return left < right
    if operator == "==":
        return left == right
    return False


COMPARATORS = (">=", "<=", "==", ">", "<")


def _split_comparison(value: str) -> tuple[str, str] | None:
    for comparator in COMPARATORS:
        if comparator in value:
            left, _, right = value.partition(comparator)
            if left.strip() and right.strip():
                return comparator, right.strip()
    return None


class ReassessmentEvaluator:
    """Pure evaluator for an LLM NEXT_REASSESSMENT contract."""

    def __init__(self, *, event_lookback_seconds: float = 900.0) -> None:
        self.event_lookback_seconds = float(event_lookback_seconds)

    def evaluate(
        self,
        plan: Any,
        *,
        now: datetime | None = None,
        price: Decimal | float | str | None = None,
        indicators: dict[str, Any] | None = None,
        events: list[Any] | None = None,
        anchor_time: datetime | None = None,
    ) -> ReassessmentWake:
        moment = now or datetime.now(UTC)
        conditions = self._conditions(plan)
        if not conditions:
            return ReassessmentWake(
                triggered=False, reason_codes=["NO_CONDITIONS"], unmatched_conditions=[]
            )
        logic = str(getattr(plan, "logic", None) or self._dict_get(plan, "logic") or "OR").upper()
        matched: list[str] = []
        unmatched: list[str] = []
        priorities: list[str] = []
        price_value = self._to_decimal(price)
        indicator_map = dict(indicators or {})
        event_kinds_with_time = self._event_map(events, moment)
        for condition in conditions:
            kind = str(self._dict_get(condition, "type") or "").upper()
            value = str(self._dict_get(condition, "value") or "")
            priority = str(self._dict_get(condition, "priority") or "NORMAL").upper()
            label = f"{kind}:{value}"
            ok = False
            reason = ""
            if kind == "PRICE":
                ok, reason = self._match_price(value, price_value)
            elif kind == "TIME":
                ok, reason = self._match_time(value, moment, anchor_time)
            elif kind == "INDICATOR":
                ok, reason = self._match_indicator(value, indicator_map)
            elif kind == "EVENT":
                ok, reason = self._match_event(value, event_kinds_with_time)
            else:
                reason = "UNKNOWN_CONDITION_TYPE"
            if ok:
                matched.append(label)
                priorities.append(priority)
            else:
                unmatched.append(f"{label}:{reason or 'NOT_MET'}")
        if logic == "AND":
            triggered = not unmatched
            reason_codes = ["ALL_CONDITIONS_MET"] if triggered else ["AND_CONDITION_UNMET"]
        else:
            triggered = bool(matched)
            reason_codes = ["ANY_CONDITION_MET"] if triggered else ["NO_CONDITION_MET"]
        priority = self._priority_for(priorities if triggered else [])
        return ReassessmentWake(
            triggered=triggered,
            matched_conditions=matched,
            unmatched_conditions=unmatched,
            priority=priority,
            reason_codes=reason_codes,
        )

    # -------------------------------------------------------------- matchers
    def _match_price(self, value: str, price: Decimal | None) -> tuple[bool, str]:
        if price is None:
            return False, "NO_PRICE"
        normalized = value.upper().replace("ABOVE", ">").replace("BELOW", "<").strip()
        for operator in COMPARATORS:
            if normalized.startswith(operator):
                target = _parse_number(normalized[len(operator) :])
                if target is None:
                    return False, "MALFORMED_PRICE"
                matched = _compare(price, operator, target)
                return (matched, "") if matched else (False, "PRICE_NOT_MET")
        target = _parse_number(value)
        if target is None:
            return False, "MALFORMED_PRICE"
        # Bare price is a touch condition within 1 bps.
        tolerance = abs(target) * Decimal("0.0001")
        return abs(price - target) <= tolerance, "PRICE_NOT_TOUCHED"

    def _match_time(self, value: str, now: datetime, anchor: datetime | None) -> tuple[bool, str]:
        text = value.strip()
        if text.startswith("+") and text.endswith("s"):
            offset = _parse_number(text[1:-1])
            if offset is None or anchor is None:
                return False, "MALFORMED_TIME" if offset is None else "NO_ANCHOR_TIME"
            from datetime import timedelta

            return now >= anchor + timedelta(seconds=float(offset)), "TIME_NOT_REACHED"
        try:
            target = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return False, "MALFORMED_TIME"
        if target.tzinfo is None:
            target = target.replace(tzinfo=UTC)
        return now >= target, "TIME_NOT_REACHED"

    def _match_indicator(self, value: str, indicators: dict[str, Any]) -> tuple[bool, str]:
        comparison = _split_comparison(value)
        if comparison is None:
            return False, "MALFORMED_INDICATOR"
        operator, right_text = comparison
        left_text = value[: value.index(operator)].strip()
        current = indicators.get(left_text)
        if current is None:
            return False, "INDICATOR_UNAVAILABLE"
        target = _parse_number(right_text)
        if target is None:
            return False, "MALFORMED_INDICATOR"
        current_decimal = self._to_decimal(current)
        if current_decimal is None:
            return False, "INDICATOR_NOT_NUMERIC"
        return _compare(current_decimal, operator, target), "INDICATOR_NOT_MET"

    def _match_event(self, value: str, events: dict[str, datetime]) -> tuple[bool, str]:
        kind = value.strip().upper()
        return kind in events, "EVENT_NOT_SEEN"

    # -------------------------------------------------------------- helpers
    def _conditions(self, plan: Any) -> list[Any]:
        if plan is None:
            return []
        conditions = getattr(plan, "conditions", None)
        if conditions is None:
            conditions = self._dict_get(plan, "conditions")
        return list(conditions or [])

    @staticmethod
    def _dict_get(item: Any, key: str) -> Any:
        if isinstance(item, dict):
            return item.get(key)
        return getattr(item, key, None)

    def _event_map(self, events: list[Any] | None, now: datetime) -> dict[str, datetime]:
        out: dict[str, datetime] = {}
        for event in events or []:
            kind = str(
                event.get("kind") if isinstance(event, dict) else getattr(event, "kind", event)
            ).upper()
            at = event.get("at") if isinstance(event, dict) else getattr(event, "at", None)
            if isinstance(at, str):
                try:
                    at = datetime.fromisoformat(at.replace("Z", "+00:00"))
                except ValueError:
                    at = None
            if at is not None and at.tzinfo is None:
                at = at.replace(tzinfo=UTC)
            if at is None or (now - at).total_seconds() <= self.event_lookback_seconds:
                out[kind] = at or now
        return out

    @staticmethod
    def _to_decimal(value: Any) -> Decimal | None:
        if value is None:
            return None
        if isinstance(value, Decimal):
            return value
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None

    @staticmethod
    def _priority_for(priorities: list[str]) -> InvocationPriority:
        best = max((PRIORITY_RANK.get(item, 0) for item in priorities), default=0)
        if best >= 2:
            return InvocationPriority.URGENT
        if best == 1:
            return InvocationPriority.HIGH
        return InvocationPriority.NORMAL
