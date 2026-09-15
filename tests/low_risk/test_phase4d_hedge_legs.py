"""Phase 4D hedge leg contract tests (SPEC: independent opposite leg only)."""

from __future__ import annotations

from decimal import Decimal

from crypto_trader.domain.enums import OrderSide
from crypto_trader.llm_chief.decision import BaseExitPlan, ChiefTraderDecision, PositionState
from crypto_trader.llm_chief.trade_planner import LiveLLMTradePlanner
from crypto_trader.trade_plan.service import TradePlanService
from crypto_trader.execution.hedge_legs import (
    HedgeLegContract,
    HedgeLegRegistry,
    LegKind,
    validate_hedge_leg,
)

LONG = HedgeLegContract(
    leg_id="leg-long",
    symbol="BTCUSDT",
    side="LONG",
    kind=LegKind.ENTRY,
    strategy="BREAKOUT",
    thesis="breakout continuation over 105",
    base_exit={"type": "PRICE", "trigger": ">=110"},
    invalidation="close below 98",
    evidence_families=["trend", "orderflow"],
    reason="momentum entry",
)


def _short(**overrides) -> HedgeLegContract:
    values = dict(
        leg_id="leg-short",
        symbol="BTCUSDT",
        side="SHORT",
        kind=LegKind.HEDGE,
        strategy="MEAN_REVERT",
        thesis="range rejection at 112 with exhaustion",
        base_exit={"type": "PRICE", "trigger": "<=104"},
        invalidation="acceptance above 115",
        evidence_families=["mean_reversion", "orderbook"],
        reason="independent reversal thesis",
    )
    values.update(overrides)
    return HedgeLegContract(**values)


def test_independent_opposite_leg_is_allowed() -> None:
    result = validate_hedge_leg(_short(), [LONG])
    assert result.allowed is True
    assert result.violations == []
    assert result.authority == "NEW_RISK_REQUIRES_CORE_LLM"
    assert result.is_order is False


def test_loss_mitigation_only_reason_is_rejected() -> None:
    contract = _short(reason="reduce loss on the original LONG")
    result = validate_hedge_leg(contract, [LONG])
    assert result.allowed is False
    assert "ILLEGAL_HEDGE_REASON_LOSS_MITIGATION_ONLY" in result.violations


def test_same_strategy_or_thesis_is_not_independent() -> None:
    same_strategy = _short(strategy="BREAKOUT")
    result = validate_hedge_leg(same_strategy, [LONG])
    assert result.allowed is False
    assert "SAME_STRATEGY_NOT_INDEPENDENT" in result.violations

    same_thesis = _short(thesis=LONG.thesis)
    result = validate_hedge_leg(same_thesis, [LONG])
    assert result.allowed is False
    assert "DUPLICATE_THESIS_NOT_INDEPENDENT" in result.violations


def test_missing_required_fields_are_rejected() -> None:
    contract = _short(base_exit=None, invalidation="", evidence_families=[])
    result = validate_hedge_leg(contract, [])
    assert result.allowed is False
    assert "MISSING_BASE_EXIT" in result.violations
    assert "MISSING_INVALIDATION" in result.violations
    assert "MISSING_EVIDENCE_FAMILIES" in result.violations


def test_same_side_add_does_not_require_hedge_independence() -> None:
    add = HedgeLegContract(
        leg_id="leg-add",
        symbol="BTCUSDT",
        side="LONG",
        kind=LegKind.ADD,
        strategy="BREAKOUT",
        thesis=LONG.thesis,
        base_exit={"type": "PRICE", "trigger": ">=110"},
        invalidation="close below 98",
        evidence_families=["trend"],
        reason="pyramid on strength",
    )
    result = validate_hedge_leg(add, [LONG])
    assert result.allowed is True
    assert result.violations == []


def test_reverse_requires_source_leg() -> None:
    reverse = _short(kind=LegKind.REVERSE, reverse_of=None)
    result = validate_hedge_leg(reverse, [LONG])
    assert result.allowed is False
    assert "REVERSE_MISSING_SOURCE_LEG" in result.violations


def test_registry_tracks_both_sides_and_rejects_illegal_hedge() -> None:
    registry = HedgeLegRegistry()
    assert registry.register(LONG).allowed is True
    assert registry.has_opposite("BTCUSDT", "LONG") is False

    rejected = registry.register(_short(reason="offset loss"))
    assert rejected.allowed is False
    assert registry.has_opposite("BTCUSDT", "LONG") is False

    assert registry.register(_short()).allowed is True
    assert registry.has_opposite("BTCUSDT", "LONG") is True
    snapshot = registry.snapshot("BTCUSDT")
    assert snapshot["both_sides"] is True
    assert snapshot["not_an_order"] is True
    assert len(snapshot["legs"]) == 2


async def test_position_leg_service_persists_only_legal_legs(database) -> None:
    from crypto_trader.execution.hedge_legs import PositionLegService

    service = PositionLegService(database.session_factory)
    first = await service.register(
        LONG, trade_plan_id="plan-1", decision_id="d1", state_version="v1"
    )
    assert first.allowed is True

    illegal = await service.register(
        _short(reason="reduce loss on the original LONG"),
        trade_plan_id="plan-2",
        decision_id="d2",
        state_version="v1",
    )
    assert illegal.allowed is False

    stored = await service.list_for_symbol("BTCUSDT")
    assert len(stored) == 1
    assert stored[0].leg_id == "leg-long"

    independent = await service.register(
        _short(), trade_plan_id="plan-3", decision_id="d3", state_version="v2"
    )
    assert independent.allowed is True
    reloaded = await service.get("leg-short")
    assert reloaded is not None
    assert reloaded.kind == LegKind.HEDGE
    assert reloaded.base_exit == {"type": "PRICE", "trigger": "<=104"}
    assert reloaded.evidence_families == ["mean_reversion", "orderbook"]


async def test_migration_0025_creates_position_legs_table(database) -> None:
    from sqlalchemy import inspect

    async with database.engine.begin() as conn:
        names = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())
    assert "position_legs" in names


def _hedge_decision(decision_id: str = "hedge-d1") -> ChiefTraderDecision:
    return ChiefTraderDecision(
        decision_id=decision_id,
        symbol="BTCUSDT",
        action="HEDGE",
        market_regime="RANGE",
        position_state=PositionState.OPEN,
        thesis="independent mean-reversion short thesis",
        position_size_request=0.1,
        leverage_request=2,
        plan_contract_version=2,
        capital_allocation_pct=10.0,
        strategy="MEAN_REVERT",
        base_exit=BaseExitPlan(type="PRICE", trigger="<=104", size_pct=100),
        based_on_state_version="v1",
        expected_edge_bps=40.0,
        expected_cost_bps=8.0,
    )


async def test_create_hedge_signal_builds_independent_opposite_plan(database) -> None:
    plans = TradePlanService(database.session_factory)
    planner = LiveLLMTradePlanner(plans)

    plan, signal = await planner.create_hedge_signal(
        _hedge_decision(),
        hedge_contract=_short(),
        existing_legs=[LONG],
        current_position_side="LONG",
        limit_price=Decimal("100"),
    )
    assert plan is not None and signal is not None
    assert signal.side == OrderSide.SELL  # opposite of the LONG leg
    assert signal.metadata["lifecycle_action"] == "HEDGE"
    assert signal.metadata["leg_id"] == "leg-short"
    stored = await plans.get(plan.trade_plan_id)
    assert stored is not None and stored.direction == "SHORT"


async def test_create_hedge_signal_rejects_illegal_hedge(database) -> None:
    plans = TradePlanService(database.session_factory)
    planner = LiveLLMTradePlanner(plans)

    plan, signal = await planner.create_hedge_signal(
        _hedge_decision("hedge-illegal"),
        hedge_contract=_short(reason="reduce loss on the original LONG"),
        existing_legs=[LONG],
        current_position_side="LONG",
        limit_price=Decimal("100"),
    )
    assert plan is None and signal is None
