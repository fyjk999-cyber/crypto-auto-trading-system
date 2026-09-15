"""Phase 4B/4C/4H-contract tests (Low-Risk V2).

Proves the structured Core-LLM contract, versioned TradePlan persistence, and
execution contract validation that REJECTS invalid new-risk children instead
of silently resizing them.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from crypto_trader.domain.enums import ExecutionDecision, OrderSide, OrderStatus, TradingMode
from crypto_trader.domain.models import Instrument, OrderIntent, RiskDecision
from crypto_trader.execution.authority import (
    AuthorizationContext,
    ExecutionAuthority,
    NewRiskOrderContract,
)
from crypto_trader.execution.rate_limiter import RateLimiter
from crypto_trader.llm_chief.decision import (
    BaseExitPlan,
    ChiefTraderDecision,
    NextReassessment,
    ReassessmentCondition,
)
from crypto_trader.risk.kill_switch import KillSwitch
from crypto_trader.trade_plan.service import TradePlanService


def _decision(**overrides) -> ChiefTraderDecision:
    payload = dict(
        decision_id="dec_v2",
        symbol="BTCUSDT",
        position_state="FLAT",
        action="LONG",
        market_regime="TREND_UP",
        thesis="breakout with relative volume",
        position_size_request=0.1,
        leverage_request=5.0,
        stop_loss=95.0,
        plan_contract_version=2,
        capital_allocation_pct=20.0,
        strategy="BREAKOUT",
        base_exit=BaseExitPlan(type="PRICE", trigger="105", size_pct=100, reason_code="BASE_EXIT"),
        thesis_invalidation="close below 95",
        expected_edge_bps=80.0,
        expected_cost_bps=25.0,
        based_on_state_version="pos_v7",
    )
    payload.update(overrides)
    return ChiefTraderDecision(**payload)


def test_v2_contract_accepts_constitutional_limits() -> None:
    decision = _decision()
    assert decision.capital_allocation_pct == 20.0
    assert decision.leverage_request == 5.0
    assert decision.base_exit.trigger == "105"
    assert decision.plan_contract_version == 2


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("capital_allocation_pct", 30.0, "capital_allocation_pct"),
        ("leverage_request", 25.0, "leverage"),
        ("base_exit", None, "Base Exit"),
        ("thesis", "", "thesis"),
        ("expected_edge_bps", 20.0, "edge"),
    ],
)
def test_v2_contract_rejects_invalid_children(field, value, message) -> None:
    with pytest.raises(ValueError, match=message):
        _decision(**{field: value})


def test_v2_contract_allows_25pct_and_20x_boundary() -> None:
    decision = _decision(capital_allocation_pct=25.0, leverage_request=20.0)
    assert decision.capital_allocation_pct == 25.0
    assert decision.leverage_request == 20.0


def test_v1_legacy_decision_remains_valid() -> None:
    decision = ChiefTraderDecision(
        decision_id="dec_v1",
        symbol="BTCUSDT",
        action="LONG",
        market_regime="TREND_UP",
        thesis="legacy",
        position_size_request=1,
        leverage_request=2,
        stop_loss=90,
    )
    assert decision.plan_contract_version == 1
    assert decision.base_exit is None


def test_position_actions_and_next_reassessment_contract() -> None:
    add = ChiefTraderDecision(
        decision_id="dec_add",
        symbol="BTCUSDT",
        position_state="OPEN",
        action="ADD",
        market_regime="TREND_UP",
        thesis="add on confirmed continuation",
        position_size_request=0.05,
        leverage_request=3,
        plan_contract_version=2,
        capital_allocation_pct=10.0,
        base_exit=BaseExitPlan(type="PRICE", trigger="115"),
        next_reassessment=NextReassessment(
            logic="OR",
            conditions=[
                ReassessmentCondition(type="PRICE", value="112", priority="HIGH"),
                ReassessmentCondition(type="EVENT", value="CVD_REVERSAL", priority="URGENT"),
            ],
        ),
    )
    assert add.action.value == "ADD"
    assert add.next_reassessment.logic == "OR"
    assert len(add.next_reassessment.conditions) == 2

    with pytest.raises(ValueError, match="logic"):
        NextReassessment(logic="XOR", conditions=[ReassessmentCondition(type="PRICE", value="1")])
    with pytest.raises(ValueError, match="at least one condition"):
        NextReassessment(logic="OR", conditions=[])


async def test_trade_plan_v2_round_trips_and_requires_base_exit(database) -> None:
    plans = TradePlanService(database.session_factory)
    with pytest.raises(ValueError, match="Base Exit"):
        await plans.create(
            decision_id="dec_missing_base",
            symbol="BTCUSDT",
            direction="LONG",
            thesis="t",
            requested_quantity=Decimal("1"),
            plan_version=2,
            strategy="TREND_FOLLOWING",
        )
    plan = await plans.create(
        decision_id="dec_full_v2",
        symbol="BTCUSDT",
        direction="LONG",
        thesis="versioned plan",
        requested_quantity=Decimal("1"),
        requested_leverage=Decimal("3"),
        plan_version=2,
        strategy="BREAKOUT",
        based_on_state_version="pos_v7",
        base_exit={"type": "PRICE", "trigger": "105", "size_pct": 100, "reason_code": "BASE_EXIT"},
        exit_approach="scale out at 1.5R",
        adverse_trigger={"type": "PRICE", "trigger": "97"},
        thesis_invalidation="close below 95",
        reassessment_rules=["reassess on CVD reversal"],
        next_reassessment={"logic": "OR", "conditions": [{"type": "PRICE", "value": "103"}]},
        expected_edge_bps=80.0,
        expected_cost_bps=25.0,
    )
    loaded = await plans.get(plan.trade_plan_id)
    assert loaded is not None
    assert loaded.plan_version == 2
    assert loaded.strategy == "BREAKOUT"
    assert loaded.based_on_state_version == "pos_v7"
    assert loaded.base_exit["reason_code"] == "BASE_EXIT"
    assert loaded.exit_approach == "scale out at 1.5R"
    assert loaded.thesis_invalidation == "close below 95"
    assert loaded.reassessment_rules == ["reassess on CVD reversal"]
    assert loaded.next_reassessment["logic"] == "OR"
    assert loaded.expected_edge_bps == 80.0
    assert loaded.expected_cost_bps == 25.0
    # Idempotent replay with identical contract returns the same plan.
    again = await plans.create(
        decision_id="dec_full_v2",
        symbol="BTCUSDT",
        direction="LONG",
        thesis="versioned plan",
        requested_quantity=Decimal("1"),
        requested_leverage=Decimal("3"),
        plan_version=2,
        strategy="BREAKOUT",
        based_on_state_version="pos_v7",
        base_exit={"type": "PRICE", "trigger": "105", "size_pct": 100, "reason_code": "BASE_EXIT"},
        exit_approach="scale out at 1.5R",
        adverse_trigger={"type": "PRICE", "trigger": "97"},
        thesis_invalidation="close below 95",
        reassessment_rules=["reassess on CVD reversal"],
        next_reassessment={"logic": "OR", "conditions": [{"type": "PRICE", "value": "103"}]},
        expected_edge_bps=80.0,
        expected_cost_bps=25.0,
    )
    assert again.trade_plan_id == plan.trade_plan_id


async def test_planner_passes_v2_contract_into_plan_and_signal() -> None:
    captured: dict = {}

    class StubPlans:
        async def create(self, **kwargs):
            captured["plan"] = kwargs

            class _Plan:
                trade_plan_id = "plan_v2"

            return _Plan()

        async def link(self, *args, **kwargs):
            captured["link"] = kwargs

    from crypto_trader.llm_chief.trade_planner import LiveLLMTradePlanner

    planner = LiveLLMTradePlanner(StubPlans(), max_holding_time_seconds=86400.0)
    plan, signal = await planner.create_entry_signal(_decision())
    assert plan is not None and signal is not None
    assert captured["plan"]["plan_version"] == 2
    assert captured["plan"]["strategy"] == "BREAKOUT"
    assert captured["plan"]["base_exit"]["trigger"] == "105"
    assert captured["plan"]["based_on_state_version"] == "pos_v7"
    assert captured["plan"]["expected_edge_bps"] == 80.0
    assert signal.metadata["plan_version"] == 2
    assert signal.metadata["capital_allocation_pct"] == "20.0"
    assert signal.metadata["base_exit"]["reason_code"] == "BASE_EXIT"


async def test_planner_does_not_fabricate_base_exit_for_v1_decisions() -> None:
    captured: dict = {}

    class StubPlans:
        async def create(self, **kwargs):
            captured["plan"] = kwargs

            class _Plan:
                trade_plan_id = "plan_v1"

            return _Plan()

        async def link(self, *args, **kwargs):
            return None

    from crypto_trader.llm_chief.trade_planner import LiveLLMTradePlanner

    legacy = ChiefTraderDecision(
        decision_id="dec_v1",
        symbol="BTCUSDT",
        action="LONG",
        market_regime="TREND_UP",
        thesis="legacy entry",
        position_size_request=1,
        leverage_request=2,
        stop_loss=90,
    )
    _, signal = await LiveLLMTradePlanner(StubPlans()).create_entry_signal(legacy)
    assert captured["plan"]["plan_version"] == 1
    assert captured["plan"]["base_exit"] is None
    assert signal.metadata["base_exit"] is None


def _auth_ctx(contract: NewRiskOrderContract | None) -> AuthorizationContext:
    return AuthorizationContext(
        now=datetime.now(UTC),
        trading_mode=TradingMode.PAPER,
        live_enabled=False,
        lease_held=True,
        kill_switch=KillSwitch(False),
        order_status=OrderStatus.CREATED,
        market_data_fresh=True,
        orderbook_fresh=True,
        orderbook_healthy=True,
        symbol_tradeable=True,
        exchange_connected=True,
        balance_fresh=True,
        risk_decision=RiskDecision(
            risk_decision_id="r1",
            client_order_id="c1",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            decision=ExecutionDecision.APPROVE,
            reason="RISK_PASS",
            checks={},
            timestamp=datetime.now(UTC),
        ),
        instrument=Instrument(
            symbol="BTCUSDT",
            base_asset="BTC",
            quote_asset="USDT",
            tick_size="0.01",
            step_size="0.001",
            min_qty="0.001",
            min_notional="5",
        ),
        rate_limiter=RateLimiter(100, 10),
        order_contract=contract,
    )


def _intent() -> OrderIntent:
    return OrderIntent(
        client_order_id="c1",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        price="100.01",
        quantity="0.1",
    )


async def test_authority_rejects_child_over_25pct_without_resizing() -> None:
    contract = NewRiskOrderContract(
        is_new_risk=True,
        capital_allocation_pct=Decimal("30"),
        leverage=Decimal("5"),
        base_exit_present=True,
    )
    decision, notes = await ExecutionAuthority().authorize(_intent(), _auth_ctx(contract))
    assert decision == ExecutionDecision.REJECT
    assert "NEW_RISK_CHILD_OVER_25PCT_EQUITY" in notes


async def test_authority_rejects_leverage_over_20x() -> None:
    contract = NewRiskOrderContract(
        is_new_risk=True,
        capital_allocation_pct=Decimal("20"),
        leverage=Decimal("25"),
        base_exit_present=True,
    )
    decision, notes = await ExecutionAuthority().authorize(_intent(), _auth_ctx(contract))
    assert decision == ExecutionDecision.REJECT
    assert "LEVERAGE_OVER_20X" in notes


async def test_authority_rejects_entry_without_base_exit() -> None:
    contract = NewRiskOrderContract(
        is_new_risk=True,
        capital_allocation_pct=Decimal("20"),
        leverage=Decimal("5"),
        base_exit_present=False,
    )
    decision, notes = await ExecutionAuthority().authorize(_intent(), _auth_ctx(contract))
    assert decision == ExecutionDecision.REJECT
    assert "BASEEXIT_MISSING" in notes


async def test_authority_approves_boundary_contract_and_keeps_legacy_path() -> None:
    boundary = NewRiskOrderContract(
        is_new_risk=True,
        capital_allocation_pct=Decimal("25"),
        leverage=Decimal("20"),
        base_exit_present=True,
        strategy="BREAKOUT",
        based_on_state_version="pos_v7",
    )
    decision, notes = await ExecutionAuthority().authorize(_intent(), _auth_ctx(boundary))
    assert decision == ExecutionDecision.APPROVE
    assert notes == ["AUTHORITY_PASS"]

    # Legacy callers without a contract keep the exact previous verdict.
    legacy_decision, legacy_notes = await ExecutionAuthority().authorize(
        _intent(), _auth_ctx(None)
    )
    assert legacy_decision == ExecutionDecision.APPROVE
    assert legacy_notes == ["AUTHORITY_PASS"]
