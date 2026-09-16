"""Low-Risk V2 hedge leg contract (Phase 4D).

SPEC: LONG and SHORT may coexist on the same symbol, but the opposite leg must
carry its own strategy, model-family evidence, thesis, Base Exit and invalidation.
Merely "reducing the original position's loss" is not a legal hedge reason.

This is a deterministic validation / book-keeping layer. It never submits an
order: every hedge/reverse is still NEW RISK and must come from the Core LLM and
pass the canonical TradePlan + ExecutionAuthority path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import select


class LegKind(StrEnum):
    ENTRY = "ENTRY"
    ADD = "ADD"
    HEDGE = "HEDGE"
    REVERSE = "REVERSE"


ILLEGAL_HEDGE_REASON_TOKENS = (
    "减少原仓亏损",
    "降低原仓亏损",
    "对冲原仓亏损",
    "cover the loss",
    "cover loss",
    "reduce the loss",
    "reduce loss",
    "offset the loss",
    "offset loss",
    "avoid admitting",
)


@dataclass
class HedgeLegContract:
    leg_id: str
    symbol: str
    side: str  # LONG | SHORT
    kind: LegKind
    strategy: str
    thesis: str
    base_exit: dict | None
    invalidation: str | None
    evidence_families: list[str] = field(default_factory=list)
    reason: str = ""
    reverse_of: str | None = None
    authority: str = "NEW_RISK_REQUIRES_CORE_LLM"
    is_order: bool = False

    @property
    def label(self) -> str:
        return "HEDGE_LEG_CONTRACT"


@dataclass
class LegValidation:
    allowed: bool
    violations: list[str]
    authority: str = "NEW_RISK_REQUIRES_CORE_LLM"
    is_order: bool = False


def validate_hedge_leg(
    contract: HedgeLegContract, existing: list[HedgeLegContract]
) -> LegValidation:
    violations: list[str] = []
    if not contract.strategy.strip():
        violations.append("MISSING_STRATEGY")
    if not contract.thesis.strip():
        violations.append("MISSING_INDEPENDENT_THESIS")
    if not contract.base_exit:
        violations.append("MISSING_BASE_EXIT")
    if not (contract.invalidation or "").strip():
        violations.append("MISSING_INVALIDATION")
    if not contract.evidence_families:
        violations.append("MISSING_EVIDENCE_FAMILIES")

    opposite = [
        leg for leg in existing if leg.symbol == contract.symbol and leg.side != contract.side
    ]
    needs_independence = contract.kind in {LegKind.HEDGE, LegKind.REVERSE} or bool(opposite)
    if needs_independence:
        reason = contract.reason.lower()
        if any(token.lower() in reason for token in ILLEGAL_HEDGE_REASON_TOKENS):
            violations.append("ILLEGAL_HEDGE_REASON_LOSS_MITIGATION_ONLY")
        for leg in opposite:
            if leg.strategy == contract.strategy:
                violations.append("SAME_STRATEGY_NOT_INDEPENDENT")
            if leg.thesis.strip().lower() == contract.thesis.strip().lower():
                violations.append("DUPLICATE_THESIS_NOT_INDEPENDENT")
        if not contract.reverse_of and contract.kind == LegKind.REVERSE:
            violations.append("REVERSE_MISSING_SOURCE_LEG")
    return LegValidation(allowed=not violations, violations=violations)


class HedgeLegRegistry:
    """Tracks factual legs so opposite-side independence can be verified."""

    def __init__(self) -> None:
        self._legs: dict[str, HedgeLegContract] = {}

    def register(self, contract: HedgeLegContract) -> LegValidation:
        validation = validate_hedge_leg(contract, list(self._legs.values()))
        if validation.allowed:
            self._legs[contract.leg_id] = contract
        return validation

    def legs_for(self, symbol: str) -> list[HedgeLegContract]:
        return [leg for leg in self._legs.values() if leg.symbol == symbol]

    def has_opposite(self, symbol: str, side: str) -> bool:
        return any(leg.symbol == symbol and leg.side != side for leg in self._legs.values())

    def snapshot(self, symbol: str | None = None) -> dict:
        legs = self.legs_for(symbol) if symbol is not None else list(self._legs.values())
        return {
            "legs": [
                {
                    "leg_id": leg.leg_id,
                    "symbol": leg.symbol,
                    "side": leg.side,
                    "kind": leg.kind.value,
                    "strategy": leg.strategy,
                    "has_base_exit": bool(leg.base_exit),
                    "has_invalidation": bool(leg.invalidation),
                    "evidence_families": list(leg.evidence_families),
                }
                for leg in legs
            ],
            "both_sides": ({leg.side for leg in legs} == {"LONG", "SHORT"} if legs else False),
            "authority": "NEW_RISK_REQUIRES_CORE_LLM",
            "not_an_order": True,
        }


class PositionLegService:
    """Durable leg storage + independent-hedge validation (Phase 4D).

    Legs are persisted in the canonical `position_legs` table. Registration of
    an illegal hedge is rejected and never stored, so the DB cannot become a
    second source of truth for a loss-mitigation "hedge".
    """

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    async def save(
        self,
        contract: HedgeLegContract,
        *,
        trade_plan_id: str | None = None,
        decision_id: str | None = None,
        state_version: str | None = None,
        state: str = "OPEN",
        opened_at=None,
        quantity=None,
    ) -> None:
        from crypto_trader.persistence.models import PositionLegORM  # local: avoid cycles

        async with self._session_factory() as session:
            row = await session.get(PositionLegORM, contract.leg_id)
            if row is None:
                row = PositionLegORM(leg_id=contract.leg_id)
                session.add(row)
            row.symbol = contract.symbol
            row.side = contract.side
            row.kind = contract.kind.value
            row.strategy = contract.strategy
            row.thesis = contract.thesis
            row.base_exit_json = contract.base_exit
            row.invalidation = contract.invalidation or ""
            row.evidence_families_json = list(contract.evidence_families)
            row.reason = contract.reason
            row.reverse_of = contract.reverse_of
            row.trade_plan_id = trade_plan_id
            row.decision_id = decision_id
            row.state_version = state_version
            row.state = state
            row.opened_at = opened_at
            if quantity is not None:
                row.quantity = quantity
                row.remaining_quantity = quantity
            await session.commit()

    async def get(self, leg_id: str) -> HedgeLegContract | None:
        from crypto_trader.persistence.models import PositionLegORM

        async with self._session_factory() as session:
            row = await session.get(PositionLegORM, leg_id)
            return self._to_contract(row) if row is not None else None

    async def list_for_symbol(self, symbol: str) -> list[HedgeLegContract]:
        from sqlalchemy import select

        from crypto_trader.persistence.models import PositionLegORM

        async with self._session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(PositionLegORM).where(PositionLegORM.symbol == symbol)
                    )
                )
                .scalars()
                .all()
            )
            return [self._to_contract(row) for row in rows]

    async def register(
        self,
        contract: HedgeLegContract,
        *,
        trade_plan_id: str | None = None,
        decision_id: str | None = None,
        state_version: str | None = None,
        quantity=None,
    ) -> LegValidation:
        existing = await self.list_for_symbol(contract.symbol)
        validation = validate_hedge_leg(contract, existing)
        if validation.allowed:
            await self.save(
                contract,
                trade_plan_id=trade_plan_id,
                decision_id=decision_id,
                state_version=state_version,
                quantity=quantity,
            )
        return validation

    QUANT = Decimal("0.00000001")

    async def apply_fill(
        self,
        leg_id: str,
        signed_quantity,
        *,
        price=None,
        fee=None,
        funding=None,
        fill_id: str | None = None,
        terminal_reason: str | None = None,
    ):
        """Apply exactly one factual fill to exactly one leg.

        Positive signed_quantity opens/adds in the leg's direction; negative
        reduces it without ever flipping it. When price is provided the leg
        keeps an auditable entry VWAP, closed quantity and realized PnL. A
        repeated fill_id is a no-op, so duplicate WS/REST delivery cannot
        double-apply a fill.
        """
        from datetime import UTC, datetime
        from decimal import Decimal

        from crypto_trader.persistence.models import PositionLegORM

        qty_raw = Decimal(str(signed_quantity))
        if qty_raw == 0:
            return None
        async with self._session_factory() as session:
            row = await session.get(PositionLegORM, leg_id)
            if row is None:
                return None
            applied = list(row.applied_fill_ids_json or [])
            if fill_id and str(fill_id) in applied:
                return Decimal(str(row.remaining_quantity or 0))
            current = Decimal(str(row.remaining_quantity or 0))
            avg = (
                Decimal(str(row.average_entry_price))
                if row.average_entry_price is not None
                else None
            )
            direction = Decimal("1") if row.side == "LONG" else Decimal("-1")
            price_d = Decimal(str(price)) if price is not None else None
            fill_qty = qty_raw.copy_abs()
            if qty_raw > 0:
                if price_d is not None:
                    if current == 0 or avg is None:
                        avg = price_d
                    else:
                        avg = (avg * current + price_d * fill_qty) / (current + fill_qty)
                row.quantity = (Decimal(str(row.quantity or 0)) + fill_qty).quantize(self.QUANT)
            else:
                closed = min(fill_qty, current)
                if closed > 0:
                    row.closed_quantity = (
                        Decimal(str(row.closed_quantity or 0)) + closed
                    ).quantize(self.QUANT)
                    if price_d is not None and avg is not None:
                        realized = (price_d - avg) * closed * direction
                        row.realized_pnl = (
                            Decimal(str(row.realized_pnl or 0)) + realized
                        ).quantize(self.QUANT)
            remaining = current + qty_raw
            row.remaining_quantity = (remaining if remaining > 0 else Decimal("0")).quantize(
                self.QUANT
            )
            row.average_entry_price = avg.quantize(self.QUANT) if avg is not None else None
            if fee is not None:
                row.fees = (Decimal(str(row.fees or 0)) + Decimal(str(fee))).quantize(self.QUANT)
            if funding is not None:
                row.funding = (Decimal(str(row.funding or 0)) + Decimal(str(funding))).quantize(
                    self.QUANT
                )
            if fill_id:
                applied.append(str(fill_id))
                row.applied_fill_ids_json = applied[-500:]
            now = datetime.now(UTC)
            if row.remaining_quantity == 0:
                row.state = "CLOSED"
                row.closed_at = now
                row.terminal_reason = terminal_reason or row.terminal_reason or "CLOSED"
            row.updated_at = now
            await session.commit()
            return row.remaining_quantity

    async def apply_order_fill(
        self,
        leg_id: str,
        order_side,
        quantity,
        *,
        price=None,
        fee=None,
        funding=None,
        fill_id: str | None = None,
        terminal_reason: str | None = None,
    ):
        """Attribute a factual order fill to its leg with the correct sign.

        LONG leg: BUY increases, SELL decreases. SHORT leg: SELL increases,
        BUY decreases. This keeps one leg's fills from silently netting into
        the other side of the same symbol.
        """
        contract = await self.get(leg_id)
        if contract is None:
            return None
        side = str(getattr(order_side, "value", order_side)).upper()
        signed = Decimal(str(quantity))
        if contract.side == "LONG":
            if side != "BUY":
                signed = -signed
        elif side != "SELL":
            signed = -signed
        return await self.apply_fill(
            leg_id,
            signed,
            price=price,
            fee=fee,
            funding=funding,
            fill_id=fill_id,
            terminal_reason=terminal_reason,
        )

    async def snapshot_state(self, leg_id: str) -> dict | None:
        """Canonical per-leg accounting view (leg truth, not a net view)."""
        from crypto_trader.persistence.models import PositionLegORM

        async with self._session_factory() as session:
            row = await session.get(PositionLegORM, leg_id)
            if row is None:
                return None
            avg = (
                Decimal(str(row.average_entry_price))
                if row.average_entry_price is not None
                else None
            )
            closed = Decimal(str(row.closed_quantity or 0))
            realized = Decimal(str(row.realized_pnl or 0))
            direction = Decimal("1") if row.side == "LONG" else Decimal("-1")
            exit_vwap = (
                (avg + realized / (closed * direction)).quantize(self.QUANT)
                if avg is not None and closed > 0
                else None
            )
            fees = Decimal(str(row.fees or 0))
            funding = Decimal(str(row.funding or 0))
            return {
                "leg_id": row.leg_id,
                "symbol": row.symbol,
                "side": row.side,
                "kind": row.kind,
                "state": row.state,
                "strategy": row.strategy,
                "thesis": row.thesis,
                "base_exit": row.base_exit_json,
                "quantity": row.quantity,
                "remaining_quantity": row.remaining_quantity,
                "average_entry_price": avg,
                "closed_quantity": closed,
                "exit_vwap": exit_vwap,
                "realized_pnl": realized,
                "unrealized_pnl": Decimal(str(row.unrealized_pnl or 0)),
                "fees": fees,
                "funding": funding,
                "net_pnl": (realized - fees + funding).quantize(self.QUANT),
                "terminal_reason": row.terminal_reason,
                "reverse_of": row.reverse_of,
                "trade_plan_id": row.trade_plan_id,
                "decision_id": row.decision_id,
                "state_version": row.state_version,
                "opened_at": row.opened_at,
                "closed_at": row.closed_at,
                "authority": "POSITION_LEG_TRUTH",
                "is_order": False,
            }

    async def record_leg_order(
        self,
        *,
        leg_id: str,
        client_order_id: str,
        side: str,
        intended_quantity,
        trade_plan_id: str | None = None,
        decision_id: str | None = None,
        reduce_only: bool = False,
        source_action: str = "",
        internal_order_id: str | None = None,
    ) -> bool:
        """Persist the intended leg allocation for one client order id.

        Duplicate client_order_id is a no-op so a repeated submission attempt
        cannot create a second allocation row.
        """
        from sqlalchemy import select

        from crypto_trader.persistence.models import PositionLegOrderORM

        async with self._session_factory() as session:
            existing = (
                await session.execute(
                    select(PositionLegOrderORM).where(
                        PositionLegOrderORM.client_order_id == client_order_id
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                return False
            session.add(
                PositionLegOrderORM(
                    leg_id=leg_id,
                    client_order_id=client_order_id,
                    internal_order_id=internal_order_id,
                    trade_plan_id=trade_plan_id,
                    decision_id=decision_id,
                    side=str(side).upper(),
                    intended_quantity=Decimal(str(intended_quantity)),
                    reduce_only=bool(reduce_only),
                    source_action=source_action,
                    state="INTENDED",
                )
            )
            await session.commit()
            return True

    async def allocate_fill(
        self,
        *,
        fill_id: str,
        leg_id: str,
        side,
        price,
        quantity,
        fee=None,
        client_order_id: str | None = None,
        order_id: str | None = None,
        terminal_reason: str | None = None,
    ) -> dict:
        """Deterministically allocate one factual fill to exactly one leg.

        The fill id is unique: a duplicate WS/REST delivery returns
        ``duplicate=True`` and never changes leg accounting.
        """
        from sqlalchemy import select

        from crypto_trader.persistence.models import PositionLegFillORM

        side_str = str(getattr(side, "value", side)).upper()
        async with self._session_factory() as session:
            existing = (
                await session.execute(
                    select(PositionLegFillORM).where(PositionLegFillORM.fill_id == str(fill_id))
                )
            ).scalar_one_or_none()
            if existing is not None:
                return {
                    "applied": False,
                    "duplicate": True,
                    "leg_id": existing.leg_id,
                    "fill_id": str(fill_id),
                }
            session.add(
                PositionLegFillORM(
                    fill_id=str(fill_id),
                    leg_id=leg_id,
                    client_order_id=client_order_id,
                    order_id=order_id,
                    side=side_str,
                    price=Decimal(str(price)),
                    quantity=Decimal(str(quantity)),
                    fee=Decimal(str(fee or 0)),
                )
            )
            await session.commit()
        remaining = await self.apply_order_fill(
            leg_id,
            side_str,
            quantity,
            price=price,
            fee=fee,
            fill_id=fill_id,
            terminal_reason=terminal_reason,
        )
        return {
            "applied": True,
            "duplicate": False,
            "leg_id": leg_id,
            "fill_id": str(fill_id),
            "remaining_quantity": remaining,
        }

    async def leg_orders(self, leg_id: str) -> list[dict]:
        from sqlalchemy import select

        from crypto_trader.persistence.models import PositionLegOrderORM

        async with self._session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(PositionLegOrderORM)
                        .where(PositionLegOrderORM.leg_id == leg_id)
                        .order_by(PositionLegOrderORM.id)
                    )
                )
                .scalars()
                .all()
            )
        return [
            {
                "client_order_id": row.client_order_id,
                "internal_order_id": row.internal_order_id,
                "trade_plan_id": row.trade_plan_id,
                "decision_id": row.decision_id,
                "side": row.side,
                "intended_quantity": row.intended_quantity,
                "reduce_only": row.reduce_only,
                "source_action": row.source_action,
                "state": row.state,
            }
            for row in rows
        ]

    async def leg_fills(self, leg_id: str) -> list[dict]:
        from sqlalchemy import select

        from crypto_trader.persistence.models import PositionLegFillORM

        async with self._session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(PositionLegFillORM)
                        .where(PositionLegFillORM.leg_id == leg_id)
                        .order_by(PositionLegFillORM.id)
                    )
                )
                .scalars()
                .all()
            )
        return [
            {
                "fill_id": row.fill_id,
                "client_order_id": row.client_order_id,
                "order_id": row.order_id,
                "side": row.side,
                "price": row.price,
                "quantity": row.quantity,
                "fee": row.fee,
            }
            for row in rows
        ]

    async def unresolved_unknowns(self, leg_id: str) -> list[dict]:
        """Canonical orders for this leg still in UNKNOWN state.

        New-risk replacement must wait until reconciliation resolves these.
        """
        import json

        from sqlalchemy import select

        from crypto_trader.persistence.models import OrderORM

        async with self._session_factory() as session:
            rows = (
                (await session.execute(select(OrderORM).where(OrderORM.status == "UNKNOWN")))
                .scalars()
                .all()
            )
        out = []
        for row in rows:
            raw = row.metadata_json
            if isinstance(raw, dict):
                metadata = raw
            else:
                try:
                    metadata = json.loads(raw or "{}")
                except (TypeError, ValueError):
                    metadata = {}
            if str(metadata.get("leg_id") or "") == leg_id:
                out.append(
                    {
                        "internal_order_id": row.internal_order_id,
                        "client_order_id": row.client_order_id,
                        "status": row.status,
                    }
                )
        return out

    @staticmethod
    def _open_leg_dict(row) -> dict:
        return {
            "leg_id": row.leg_id,
            "symbol": row.symbol,
            "side": row.side,
            "kind": row.kind,
            "remaining_quantity": row.remaining_quantity,
            "quantity": row.quantity,
            "strategy": row.strategy,
            "thesis": row.thesis,
            "base_exit": row.base_exit_json,
            "average_entry_price": row.average_entry_price,
            "state_version": row.state_version,
            "trade_plan_id": row.trade_plan_id,
            "decision_id": row.decision_id,
            "reverse_of": row.reverse_of,
            "updated_at": row.updated_at,
        }

    async def open_legs_for_symbol(self, symbol: str) -> list[dict]:
        """Factual open legs (remaining quantity > 0) for deterministic exits."""
        from sqlalchemy import select

        from crypto_trader.persistence.models import PositionLegORM

        async with self._session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(PositionLegORM).where(PositionLegORM.symbol == symbol)
                    )
                )
                .scalars()
                .all()
            )
        return [
            self._open_leg_dict(row)
            for row in rows
            if row.remaining_quantity is not None and row.remaining_quantity > 0
        ]

    async def open_legs_all(self) -> list[dict]:
        """Every factual open leg across symbols (independent of net view)."""
        from sqlalchemy import select

        from crypto_trader.persistence.models import PositionLegORM

        async with self._session_factory() as session:
            rows = (await session.execute(select(PositionLegORM))).scalars().all()
        return [
            self._open_leg_dict(row)
            for row in rows
            if row.remaining_quantity is not None and row.remaining_quantity > 0
        ]

    async def gross_exposure(self, symbol: str) -> dict:
        """Per-side factual leg exposure (dual-side LONG+SHORT tracking)."""
        from decimal import Decimal

        from crypto_trader.persistence.models import PositionLegORM

        async with self._session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(PositionLegORM).where(PositionLegORM.symbol == symbol)
                    )
                )
                .scalars()
                .all()
            )
        long_total = sum(
            (Decimal(str(row.remaining_quantity or 0)) for row in rows if row.side == "LONG"),
            Decimal("0"),
        )
        short_total = sum(
            (Decimal(str(row.remaining_quantity or 0)) for row in rows if row.side == "SHORT"),
            Decimal("0"),
        )
        return {
            "symbol": symbol,
            "long": long_total,
            "short": short_total,
            "net": long_total - short_total,
            "gross": long_total + short_total,
            "leg_count": len(rows),
            "both_sides": long_total > 0 and short_total > 0,
            "not_an_order": True,
        }

    @staticmethod
    def _to_contract(row) -> HedgeLegContract:
        return HedgeLegContract(
            leg_id=row.leg_id,
            symbol=row.symbol,
            side=row.side,
            kind=LegKind(row.kind),
            strategy=row.strategy,
            thesis=row.thesis,
            base_exit=row.base_exit_json,
            invalidation=row.invalidation,
            evidence_families=list(row.evidence_families_json or []),
            reason=row.reason,
            reverse_of=row.reverse_of,
        )


class LegPositionReconciler:
    """Compare leg-level facts with the canonical net position.

    Until this reports MATCHED the portfolio cannot treat legs as the source of
    truth, so hedge execution must stay fail-closed. This is read-only
    book-keeping and never submits an order.
    """

    authority = "RECONCILIATION_ONLY"
    is_order = False

    def __init__(self, leg_service: PositionLegService, tolerance=Decimal("0.00000001")) -> None:
        self.leg_service = leg_service
        self.tolerance = Decimal(str(tolerance))

    async def reconcile(self, symbol: str, net_quantity) -> dict:
        exposure = await self.leg_service.gross_exposure(symbol)
        computed_net = (exposure["long"] - exposure["short"]).quantize(self.tolerance)
        net = Decimal(str(net_quantity or 0))
        diff = net - computed_net
        if abs(diff) <= self.tolerance:
            status = "MATCHED"
        elif computed_net == 0 and net != 0:
            status = "UNTRACKED_NET_POSITION"
        else:
            status = "DIVERGED"
        return {
            "symbol": symbol,
            "net_quantity": net,
            "leg_long": exposure["long"],
            "leg_short": exposure["short"],
            "computed_net": computed_net,
            "difference": diff,
            "status": status,
            "leg_count": exposure["leg_count"],
            "leg_execution_safe": status == "MATCHED",
            "authority": self.authority,
            "is_order": False,
        }
