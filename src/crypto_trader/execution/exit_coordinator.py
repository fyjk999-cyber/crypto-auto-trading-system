"""Exit Coordination (Low-Risk V2 Phase 4I / Phase 6).

One canonical coordinator for every reduce/close mechanism so the system can
never duplicate-sell, oversell or leave ghost reservations:

  priority 1 Risk Hard Exit
  priority 2 Offline Hard Exit
  priority 3 Fast Profit Protection
  priority 4 Active Base Exit
  priority 5 LLM Reduce/Close
  priority 6 LLM New Risk (recorded, never reserves reduce capacity)

Hard invariant: ``reserved_reduce_qty + active_reduce_qty <= factual_qty``.
Higher-priority exits may preempt lower-priority *pending* requests, but never
confirmed fills. This module is deterministic book-keeping only: it never
submits an order and never mutates a broker/DB itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import IntEnum

from crypto_trader.domain.enums import OrderSide
from crypto_trader.domain.identifiers import new_id


class ExitPriority(IntEnum):
    RISK_HARD_EXIT = 1
    OFFLINE_HARD_EXIT = 2
    FAST_PROFIT = 3
    ACTIVE_BASE_EXIT = 4
    LLM_REDUCE_CLOSE = 5
    LLM_NEW_RISK = 6


NEW_RISK_PRIORITIES = {ExitPriority.LLM_NEW_RISK}
REDUCE_PRIORITIES = {
    ExitPriority.RISK_HARD_EXIT,
    ExitPriority.OFFLINE_HARD_EXIT,
    ExitPriority.FAST_PROFIT,
    ExitPriority.ACTIVE_BASE_EXIT,
    ExitPriority.LLM_REDUCE_CLOSE,
}


class ExitRequestState:
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


@dataclass(slots=True)
class ExitLeg:
    leg_id: str
    symbol: str
    side: str  # LONG | SHORT (factual direction of the leg)
    factual_qty: Decimal
    state_version: str = "v0"
    closed: bool = False


@dataclass(slots=True)
class ExitRequest:
    request_id: str
    leg_id: str
    symbol: str
    side: OrderSide  # order side (opposite of the leg for reduce)
    quantity: Decimal
    priority: ExitPriority
    reason_code: str
    authority: str
    state_version: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    state: str = ExitRequestState.PENDING
    reserved_qty: Decimal = Decimal("0")
    filled_qty: Decimal = Decimal("0")
    preempted_by: str | None = None

    @property
    def remaining_qty(self) -> Decimal:
        return max(Decimal("0"), self.quantity - self.filled_qty)


@dataclass(slots=True)
class CoordinationResult:
    accepted: bool
    request: ExitRequest | None
    approved_qty: Decimal
    reason_codes: list[str] = field(default_factory=list)
    preempted: list[str] = field(default_factory=list)
    authoritative: bool = True


class ExitCoordinator:
    """Single source of truth for reduce-quantity reservations."""

    def __init__(self) -> None:
        self.legs: dict[str, ExitLeg] = {}
        self.requests: dict[str, ExitRequest] = {}
        self.rejected: list[str] = []
        self.events: list[dict] = []

    # ------------------------------------------------------------------ legs
    def register_leg(
        self,
        leg_id: str,
        *,
        symbol: str,
        side: str,
        quantity: Decimal,
        state_version: str = "v0",
    ) -> ExitLeg:
        existing = self.legs.get(leg_id)
        if existing is not None and not existing.closed and existing.factual_qty > 0:
            raise ValueError(f"leg {leg_id} already registered with a factual position")
        leg = ExitLeg(
            leg_id=leg_id,
            symbol=symbol,
            side=side.upper(),
            factual_qty=abs(quantity),
            state_version=state_version,
        )
        self.legs[leg_id] = leg
        self._event(
            "LEG_REGISTERED", leg_id=leg_id, qty=str(leg.factual_qty), version=state_version
        )
        return leg

    def apply_fill(
        self, leg_id: str, signed_qty: Decimal, *, state_version: str | None = None
    ) -> ExitLeg:
        """Apply a factual fill to the leg (positive=long quantity, negative=short)."""
        leg = self._require_leg(leg_id)
        leg.factual_qty = (
            abs(leg.factual_qty + signed_qty)
            if (leg.factual_qty + signed_qty) >= 0
            else abs(signed_qty)
        )
        if state_version is not None:
            leg.state_version = state_version
        leg.closed = leg.factual_qty == 0
        self._event(
            "LEG_FILL", leg_id=leg_id, signed_qty=str(signed_qty), factual=str(leg.factual_qty)
        )
        return leg

    def set_factual_qty(
        self, leg_id: str, quantity: Decimal, *, state_version: str | None = None
    ) -> ExitLeg:
        leg = self._require_leg(leg_id)
        leg.factual_qty = abs(quantity)
        leg.closed = leg.factual_qty == 0
        if state_version is not None:
            leg.state_version = state_version
        return leg

    def reserved_qty(self, leg_id: str) -> Decimal:
        return sum(
            (
                request.reserved_qty
                for request in self.requests.values()
                if request.leg_id == leg_id and request.priority in REDUCE_PRIORITIES
            ),
            Decimal("0"),
        )

    def available_qty(self, leg_id: str) -> Decimal:
        leg = self._require_leg(leg_id)
        return max(Decimal("0"), leg.factual_qty - self.reserved_qty(leg_id))

    # -------------------------------------------------------------- requests
    def submit(
        self,
        *,
        leg_id: str,
        side: OrderSide,
        quantity: Decimal,
        priority: ExitPriority,
        reason_code: str,
        authority: str,
        state_version: str | None = None,
        request_id: str | None = None,
        preempt: bool = True,
    ) -> CoordinationResult:
        leg = self._require_leg(leg_id)
        request = ExitRequest(
            request_id=request_id or new_id("exit"),
            leg_id=leg_id,
            symbol=leg.symbol,
            side=side,
            quantity=abs(quantity),
            priority=priority,
            reason_code=reason_code,
            authority=authority,
            state_version=state_version or leg.state_version,
        )
        self.requests[request.request_id] = request
        if leg.closed or leg.factual_qty <= 0:
            return self._reject(request, ["NO_FACTUAL_POSITION"])
        if priority in NEW_RISK_PRIORITIES:
            # New-risk requests are recorded for priority visibility only; they
            # never reserve reduce capacity and never authorize an order here.
            return CoordinationResult(
                accepted=True,
                request=request,
                approved_qty=request.quantity,
                reason_codes=["NEW_RISK_RECORDED_AUTHORITY_ELSEWHERE"],
            )
        if quantity <= 0:
            return self._reject(request, ["INVALID_QUANTITY"])
        expected_side = OrderSide.SELL if leg.side == "LONG" else OrderSide.BUY
        if side != expected_side:
            return self._reject(request, ["REDUCE_SIDE_MISMATCH"])

        preempted: list[str] = []
        available = self.available_qty(leg_id)
        if available < request.quantity and preempt and priority < ExitPriority.LLM_NEW_RISK:
            preempted = self._preempt_lower_priority(leg, request)
            available = self.available_qty(leg_id)
        approved = min(request.quantity, available)
        if approved <= 0:
            return self._reject(request, ["OVERSELL_BLOCKED_NO_AVAILABLE_QTY"], preempted)
        if approved < request.quantity:
            request.quantity = approved
        request.reserved_qty = approved
        request.state = ExitRequestState.PENDING
        self._event(
            "EXIT_RESERVED",
            leg_id=leg_id,
            request_id=request.request_id,
            priority=priority.name,
            approved=str(approved),
        )
        return CoordinationResult(
            accepted=True,
            request=request,
            approved_qty=approved,
            reason_codes=["RESERVED"] if approved == request.quantity else ["PARTIALLY_RESERVED"],
            preempted=preempted,
        )

    def mark_submitted(self, request_id: str) -> ExitRequest:
        request = self._require_request(request_id)
        request.state = ExitRequestState.SUBMITTED
        return request

    def confirm_fill(self, request_id: str, filled_qty: Decimal) -> ExitRequest:
        request = self._require_request(request_id)
        leg = self._require_leg(request.leg_id)
        qty = min(abs(filled_qty), request.reserved_qty)
        if qty <= 0:
            return request
        request.filled_qty += qty
        request.reserved_qty -= qty
        # Factual leg shrinks by the filled reduce quantity only.
        signed = -qty if leg.side == "LONG" else qty
        leg.factual_qty = max(Decimal("0"), leg.factual_qty + signed)
        leg.closed = leg.factual_qty == 0
        if leg.factual_qty == 0:
            # Nothing left: release any other reservations on this leg.
            for other in self.requests.values():
                if other.leg_id == leg.leg_id and other.reserved_qty > 0:
                    other.reserved_qty = Decimal("0")
                    if other.state in (ExitRequestState.PENDING, ExitRequestState.SUBMITTED):
                        other.state = ExitRequestState.CANCELLED
        if request.reserved_qty == 0:
            request.state = ExitRequestState.FILLED
        else:
            request.state = ExitRequestState.PARTIAL
        self._event(
            "EXIT_FILL",
            leg_id=leg.leg_id,
            request_id=request_id,
            filled=str(qty),
            factual=str(leg.factual_qty),
        )
        return request

    def cancel(self, request_id: str, reason: str = "CANCELLED") -> ExitRequest:
        request = self._require_request(request_id)
        request.reserved_qty = Decimal("0")
        request.state = ExitRequestState.CANCELLED
        self._event("EXIT_CANCELLED", request_id=request_id, reason=reason)
        return request

    def cancel_all(
        self, *, leg_id: str, reason: str, priorities: set[ExitPriority] | None = None
    ) -> list[str]:
        cancelled: list[str] = []
        for request in self.requests.values():
            if request.leg_id != leg_id:
                continue
            if priorities is not None and request.priority not in priorities:
                continue
            if request.reserved_qty > 0 and request.state in (
                ExitRequestState.PENDING,
                ExitRequestState.SUBMITTED,
                ExitRequestState.PARTIAL,
            ):
                self.cancel(request.request_id, reason)
                cancelled.append(request.request_id)
        return cancelled

    def snapshot(self, leg_id: str) -> dict:
        leg = self._require_leg(leg_id)
        active = [
            {
                "request_id": request.request_id,
                "priority": request.priority.name,
                "reason_code": request.reason_code,
                "reserved_qty": str(request.reserved_qty),
                "filled_qty": str(request.filled_qty),
                "state": request.state,
            }
            for request in self.requests.values()
            if request.leg_id == leg_id
            and request.reserved_qty > 0
            or (request.leg_id == leg_id and request.state == ExitRequestState.PENDING)
        ]
        reserved = self.reserved_qty(leg_id)
        return {
            "leg_id": leg.leg_id,
            "symbol": leg.symbol,
            "side": leg.side,
            "factual_qty": str(leg.factual_qty),
            "reserved_reduce_qty": str(reserved),
            "available_qty": str(self.available_qty(leg_id)),
            "closed": leg.closed,
            "state_version": leg.state_version,
            "active_requests": active,
            "invariant_holds": reserved <= leg.factual_qty,
        }

    # -------------------------------------------------------------- internals
    def _preempt_lower_priority(self, leg: ExitLeg, incoming: ExitRequest) -> list[str]:
        """Shrink/cancel lower-priority pending reservations for this leg."""
        preempted: list[str] = []
        deficit = incoming.quantity - self.available_qty(leg.leg_id)
        if deficit <= 0:
            return preempted
        candidates = sorted(
            (
                request
                for request in self.requests.values()
                if request.leg_id == leg.leg_id
                and request.priority > incoming.priority
                and request.reserved_qty > 0
                and request.state
                in (
                    ExitRequestState.PENDING,
                    ExitRequestState.SUBMITTED,
                    ExitRequestState.PARTIAL,
                )
            ),
            key=lambda item: item.priority,
            reverse=True,
        )
        for candidate in candidates:
            if deficit <= 0:
                break
            take = min(deficit, candidate.reserved_qty)
            candidate.reserved_qty -= take
            deficit -= take
            candidate.preempted_by = incoming.request_id
            preempted.append(candidate.request_id)
            if candidate.reserved_qty == 0:
                candidate.state = ExitRequestState.CANCELLED
            self._event(
                "EXIT_PREEMPTED",
                leg_id=leg.leg_id,
                request_id=candidate.request_id,
                by=incoming.request_id,
                taken=str(take),
            )
        return preempted

    def _reject(
        self, request: ExitRequest, reasons: list[str], preempted: list[str] | None = None
    ) -> CoordinationResult:
        request.state = ExitRequestState.REJECTED
        self.rejected.append(request.request_id)
        self._event("EXIT_REJECTED", request_id=request.request_id, reasons=reasons)
        return CoordinationResult(
            accepted=False,
            request=request,
            approved_qty=Decimal("0"),
            reason_codes=reasons,
            preempted=preempted or [],
        )

    def _require_leg(self, leg_id: str) -> ExitLeg:
        leg = self.legs.get(leg_id)
        if leg is None:
            raise KeyError(f"unknown exit leg: {leg_id}")
        return leg

    def _require_request(self, request_id: str) -> ExitRequest:
        request = self.requests.get(request_id)
        if request is None:
            raise KeyError(f"unknown exit request: {request_id}")
        return request

    def _event(self, event: str, **fields) -> None:
        self.events.append(
            {
                "event": event,
                "at": datetime.now(UTC).isoformat(),
                **{k: v for k, v in fields.items()},
            }
        )
