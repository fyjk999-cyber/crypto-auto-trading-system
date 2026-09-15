"""Phase 4H tests: Risk is not a pre-trade sizing gate for V2 orders.

V2 entries carry the Core-LLM's capital allocation/leverage through execution
unchanged; Risk may still REJECT hard safety state but never silently shrinks
an LLM trade. Legacy entries keep historical APPROVE/SCALE_DOWN behavior.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select

from crypto_trader.domain.enums import ExecutionDecision, OrderSide, OrderStatus, TradingMode
from crypto_trader.domain.models import (
    Instrument,
    OrderIntent,
    RiskDecision,
    SignalIntent,
)
from crypto_trader.execution.authority import (
    AuthorizationContext,
    ExecutionAuthority,
    NewRiskOrderContract,
)
from crypto_trader.execution.contract import derive_execution_terms, plan_contract_version
from crypto_trader.execution.rate_limiter import RateLimiter
from crypto_trader.llm_chief.decision import BaseExitPlan, ChiefTraderDecision
from crypto_trader.llm_chief.decision_store import LLMDecisionStore
from crypto_trader.llm_chief.trade_planner import LiveLLMTradePlanner
from crypto_trader.persistence.models import AuditEventORM, RiskDecisionORM
from crypto_trader.risk.engine import RiskConfig, RiskEngine
from crypto_trader.risk.kill_switch import KillSwitch
from crypto_trader.trade_plan.service import TradePlanService
from tests.conftest import make_paper_engine


def _risk_decision(decision: ExecutionDecision, checks: dict) -> RiskDecision:
    return RiskDecision(
        risk_decision_id="r1",
        client_order_id="c1",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        decision=decision,
        reason="RISK_OBSERVATION",
        checks=checks,
        timestamp=datetime.now(UTC),
    )


def _signal(metadata: dict, quantity: str = "1") -> SignalIntent:
    return SignalIntent(
        signal_id="s1",
        strategy_id="live_llm",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        quantity=Decimal(quantity),
        limit_price=Decimal("100"),
        metadata=metadata,
        run_id="run1",
    )


class _Plan:
    strategy = "BREAKOUT"
    based_on_state_version = "pos_v7"
    base_exit = {"type": "PRICE", "trigger": "105", "reason_code": "BASE_EXIT"}


def test_v2_entry_ignores_risk_scale_down() -> None:
    terms = derive_execution_terms(
        is_entry=True,
        signal=_signal(
            {
                "plan_version": 2,
                "requested_leverage": "10",
                "capital_allocation_pct": "20.0",
                "base_exit": {"type": "PRICE", "trigger": "105"},
                "strategy": "BREAKOUT",
            }
        ),
        plan=_Plan(),
        risk_decision=_risk_decision(
            ExecutionDecision.SCALE_DOWN,
            {"approved_quantity": "0.4", "approved_leverage": "3", "original_quantity": "1"},
        ),
    )
    assert terms.quantity == Decimal("1")  # never resized
    assert terms.leverage == "10"
    assert terms.order_contract is not None
    assert terms.order_contract.is_new_risk is True
    assert terms.order_contract.capital_allocation_pct == Decimal("20.0")
    assert terms.risk_observation["scaled_by_risk"] is False
    assert terms.risk_observation["mode"] == "V2_LLM_OWNS_SIZE_AND_LEVERAGE"


def test_legacy_entry_now_uses_hard_contract_not_risk_resize() -> None:
    """Real PAPER evidence forced this adaptation.

    OLD BEHAVIOR: a legacy v1 entry returned ``order_contract=None``, bypassing
    Base-Exit/allocation/leverage checks, and Risk could SCALE_DOWN its size.
    NEW BEHAVIOR: legacy entries also carry the hard contract; Base Exit and
    allocation are required and the LLM's requested size is preserved.
    WHY SUPERSEDED: the soak executed order ``ord_208a5fde163148559b47b67189b80f05``
    from plan_version=1 with ``base_exit=null`` (no Base Exit) - a P0 trade
    without TradePlan Base Exit under the Low-Risk V2 constitution.
    """
    terms = derive_execution_terms(
        is_entry=True,
        signal=_signal({"plan_version": 1, "requested_leverage": "10"}),
        plan=_Plan(),
        risk_decision=_risk_decision(
            ExecutionDecision.SCALE_DOWN,
            {"approved_quantity": "0.4", "approved_leverage": "3"},
        ),
    )
    assert terms.quantity == Decimal("1")  # requested size preserved, no Risk resize
    assert terms.leverage == "10"
    assert terms.order_contract is not None
    assert terms.order_contract.is_new_risk is True
    assert terms.order_contract.base_exit_present is True

    class _NoBaseExitPlan(_Plan):
        base_exit = None

    missing = derive_execution_terms(
        is_entry=True,
        signal=_signal({"plan_version": 1, "requested_leverage": "10"}),
        plan=_NoBaseExitPlan(),
        risk_decision=_risk_decision(ExecutionDecision.APPROVE, {}),
    )
    assert missing.order_contract is not None
    assert missing.order_contract.base_exit_present is False  # authority must reject
    assert terms.risk_observation["mode"] == "V2_HARD_CONTRACT_APPLIED_TO_LEGACY_PLAN"
    assert plan_contract_version({}) == 1


def _auth_ctx(contract: NewRiskOrderContract | None, risk: RiskDecision | None):
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
        risk_decision=risk,
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


def _intent(quantity: str = "1") -> OrderIntent:
    return OrderIntent(
        client_order_id="c1",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        price="100.00",
        quantity=quantity,
    )


async def test_authority_accepts_v2_contract_without_risk_decision() -> None:
    contract = NewRiskOrderContract(
        is_new_risk=True,
        capital_allocation_pct=Decimal("20"),
        leverage=Decimal("10"),
        base_exit_present=True,
    )
    decision, notes = await ExecutionAuthority().authorize(
        _intent(), _auth_ctx(contract, risk=None)
    )
    assert decision == ExecutionDecision.APPROVE
    assert notes == ["AUTHORITY_PASS"]


async def test_authority_keeps_legacy_risk_gate_without_contract() -> None:
    decision, notes = await ExecutionAuthority().authorize(_intent(), _auth_ctx(None, risk=None))
    assert decision == ExecutionDecision.REJECT
    assert "RISK_NOT_VALID" in notes


async def test_authority_v2_contract_ignores_risk_scale_down_quantity() -> None:
    contract = NewRiskOrderContract(
        is_new_risk=True,
        capital_allocation_pct=Decimal("20"),
        leverage=Decimal("10"),
        base_exit_present=True,
    )
    risk = _risk_decision(
        ExecutionDecision.SCALE_DOWN,
        {"approved_quantity": "0.4", "approved_leverage": "3"},
    )
    decision, _ = await ExecutionAuthority().authorize(
        _intent(quantity="1"), _auth_ctx(contract, risk=risk)
    )
    assert decision == ExecutionDecision.APPROVE


async def test_engine_v2_entry_is_not_resized_by_risk_and_is_audited(database) -> None:
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    engine.risk_engine = RiskEngine(RiskConfig(max_order_notional=Decimal("50")))
    await engine.start("run-v2-noresize")
    assert await engine._strategy_context("BTCUSDT") is not None

    decisions = LLMDecisionStore(database.session_factory)
    plans = TradePlanService(database.session_factory)
    decision = ChiefTraderDecision(
        decision_id="v2-entry",
        symbol="BTCUSDT",
        action="LONG",
        market_regime="TREND_UP",
        thesis="V2 contract entry",
        position_size_request=1.0,
        leverage_request=10,
        stop_loss=Decimal("95"),
        plan_contract_version=2,
        capital_allocation_pct=20.0,
        strategy="BREAKOUT",
        base_exit=BaseExitPlan(type="PRICE", trigger="105", reason_code="BASE_EXIT"),
        based_on_state_version="pos_v1",
        expected_edge_bps=60.0,
        expected_cost_bps=20.0,
        model_provider="deepseek",
        model="deepseek-chat",
    )
    await decisions.save(decision, run_id=engine.run_id, prompt_version="v2-test")
    plan, signal = await LiveLLMTradePlanner(plans).create_entry_signal(
        decision, limit_price=Decimal("100")
    )
    assert plan is not None and signal is not None

    result = await engine.process_signal(signal)
    assert result is not None and result.decision == ExecutionDecision.SCALE_DOWN

    order = await engine.order_manager.get_by_client(f"{signal.strategy_id}_{signal.signal_id}")
    assert order is not None, "V2 order must reach the canonical order manager"
    assert order.quantity == Decimal("1")  # NOT risk-scaled to 0.4/0.5

    async with database.session_factory() as session:
        observations = (
            (
                await session.execute(
                    select(AuditEventORM).where(
                        AuditEventORM.action == "RISK_OBSERVATION_V2_NO_RESIZE"
                    )
                )
            )
            .scalars()
            .all()
        )
        persisted = (
            (
                await session.execute(
                    select(RiskDecisionORM).where(RiskDecisionORM.client_order_id.is_not(None))
                )
            )
            .scalars()
            .all()
        )
    assert observations, "the no-resize observation must be auditable"
    assert any(row.decision == "SCALE_DOWN" for row in persisted)

    await engine.stop()
