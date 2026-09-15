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

    async def apply_fill(self, leg_id: str, signed_quantity):
        """Apply a factual fill to one leg without ever going negative."""
        from decimal import Decimal

        from crypto_trader.persistence.models import PositionLegORM

        async with self._session_factory() as session:
            row = await session.get(PositionLegORM, leg_id)
            if row is None:
                return None
            current = Decimal(str(row.remaining_quantity or 0))
            remaining = current + Decimal(str(signed_quantity))
            row.remaining_quantity = remaining if remaining > 0 else Decimal("0")
            if row.remaining_quantity == 0:
                row.state = "CLOSED"
            await session.commit()
            return row.remaining_quantity

    async def apply_order_fill(self, leg_id: str, order_side, quantity):
        """Attribute a factual order fill to its leg with the correct sign.

        LONG leg: BUY increases, SELL decreases. SHORT leg: SELL increases,
        BUY decreases. This keeps one leg's fills from silently netting into
        the other side of the same symbol.
        """
        from decimal import Decimal

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
        return await self.apply_fill(leg_id, signed)

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
            {
                "leg_id": row.leg_id,
                "symbol": row.symbol,
                "side": row.side,
                "remaining_quantity": row.remaining_quantity,
                "strategy": row.strategy,
            }
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
