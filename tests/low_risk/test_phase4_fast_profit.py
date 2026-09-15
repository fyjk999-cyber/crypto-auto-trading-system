"""Phase 4J (Low-Risk V2) Fast Profit Protection tests.

Deterministic risk-reducing authority: net-profitable + ATR-normalized rapid
expansion + material reversal evidence -> 1..100% partial/full exit. A lone
large trade or fast move is insufficient; LONG/SHORT mirrored; no new risk.
"""

from __future__ import annotations

import inspect
from decimal import Decimal

from crypto_trader.factors.expert.context import AllInCostEstimate
from crypto_trader.market_data.state import MarketState
from crypto_trader.risk import fast_profit
from crypto_trader.risk.fast_profit import (
    FastProfitConfig,
    evaluate_fast_profit,
    exit_side_for_fast_profit,
)


def _state(
    *,
    cvd: Decimal,
    buy: Decimal,
    sell: Decimal,
    imbalance: Decimal,
    large: Decimal = Decimal("0"),
) -> MarketState:
    return MarketState(
        symbol="BTCUSDT",
        best_bid=Decimal("100"),
        best_ask=Decimal("100.1"),
        taker_buy_volume=buy,
        taker_sell_volume=sell,
        cvd=cvd,
        trade_count=120,
        large_trade_count=3,
        largest_trade_notional=large,
        imbalance_l5=imbalance,
    )


CHEAP_COSTS = AllInCostEstimate(
    entry_fee_bps=5.0,
    exit_fee_bps=5.0,
    spread_bps=1.0,
    slippage_bps=2.0,
    funding_bps=1.0,
    safety_margin_bps=1.0,
)


def test_long_fast_profit_triggers_on_profit_expansion_and_reversal() -> None:
    decision = evaluate_fast_profit(
        symbol="BTCUSDT",
        side="LONG",
        quantity=Decimal("10"),
        entry_price=Decimal("100"),
        mark_price=Decimal("101.2"),
        atr_pct=0.002,
        state=_state(
            cvd=Decimal("-300"),
            buy=Decimal("500"),
            sell=Decimal("800"),
            imbalance=Decimal("-0.4"),
            large=Decimal("150000"),
        ),
        costs=CHEAP_COSTS,
    )
    assert decision.trigger is True
    assert decision.exit_pct == 100.0  # score >= severe (cvd+book+large = 2.2)
    assert decision.exit_notional_usd == Decimal("1012.000")
    assert "CVD_REVERSAL" in decision.reason_codes
    assert "ORDERBOOK_DETERIORATION" in decision.reason_codes
    assert decision.authority == "FAST_PROFIT_PROTECTION"
    assert decision.is_new_risk is False
    assert decision.requires_llm_reassessment is True


def test_short_fast_profit_is_mirrored() -> None:
    decision = evaluate_fast_profit(
        symbol="BTCUSDT",
        side="SHORT",
        quantity=Decimal("10"),
        entry_price=Decimal("100"),
        mark_price=Decimal("98.8"),
        atr_pct=0.002,
        state=_state(
            cvd=Decimal("300"),
            buy=Decimal("800"),
            sell=Decimal("500"),
            imbalance=Decimal("0.4"),
        ),
        costs=CHEAP_COSTS,
    )
    assert decision.trigger is True
    assert decision.side == "SHORT"
    assert decision.exit_pct >= 25.0
    assert exit_side_for_fast_profit("SHORT").value == "BUY"


def test_not_net_profitable_never_triggers() -> None:
    decision = evaluate_fast_profit(
        symbol="BTCUSDT",
        side="LONG",
        quantity=Decimal("10"),
        entry_price=Decimal("100"),
        mark_price=Decimal("100.1"),  # gross 0.1% < 1.5% all-in costs
        atr_pct=0.0005,
        state=_state(
            cvd=Decimal("-300"),
            buy=Decimal("100"),
            sell=Decimal("900"),
            imbalance=Decimal("-0.9"),
        ),
        costs=AllInCostEstimate(
            entry_fee_bps=5.0,
            exit_fee_bps=5.0,
            spread_bps=2.0,
            slippage_bps=2.0,
            funding_bps=1.0,
            safety_margin_bps=0.0,
        ),
    )
    assert decision.trigger is False
    assert "NOT_NET_PROFITABLE" in decision.blocking_reasons
    assert decision.exit_pct == 0.0


def test_lone_large_trade_is_not_enough() -> None:
    decision = evaluate_fast_profit(
        symbol="BTCUSDT",
        side="LONG",
        quantity=Decimal("10"),
        entry_price=Decimal("100"),
        mark_price=Decimal("101.5"),
        atr_pct=0.002,
        state=_state(
            cvd=Decimal("50"),  # flow still with the position
            buy=Decimal("800"),
            sell=Decimal("700"),
            imbalance=Decimal("0.2"),
            large=Decimal("500000"),
        ),
        costs=CHEAP_COSTS,
    )
    assert decision.trigger is False
    assert "INSUFFICIENT_REVERSAL_EVIDENCE" in decision.blocking_reasons
    assert "large_trade_count" not in decision.evidence  # lone size is not evidence by itself


def test_fast_move_without_reversal_evidence_is_not_enough() -> None:
    decision = evaluate_fast_profit(
        symbol="BTCUSDT",
        side="LONG",
        quantity=Decimal("10"),
        entry_price=Decimal("100"),
        mark_price=Decimal("101.0"),
        atr_pct=0.001,
        state=_state(
            cvd=Decimal("0"),
            buy=Decimal("100"),
            sell=Decimal("100"),
            imbalance=Decimal("0.0"),
        ),
        costs=CHEAP_COSTS,
    )
    assert decision.trigger is False
    assert "INSUFFICIENT_REVERSAL_EVIDENCE" in decision.blocking_reasons


def test_price_rejection_alone_can_trigger_when_profitable_and_expanding() -> None:
    decision = evaluate_fast_profit(
        symbol="BTCUSDT",
        side="LONG",
        quantity=Decimal("10"),
        entry_price=Decimal("100"),
        mark_price=Decimal("101.5"),
        atr_pct=0.001,
        state=None,
        costs=CHEAP_COSTS,
        price_rejection=True,
    )
    assert decision.trigger is True
    assert 1.0 <= decision.exit_pct <= 100.0
    assert "PRICE_REJECTION" in decision.reason_codes


def test_uneconomic_fragments_are_full_exit_or_nothing() -> None:
    config = FastProfitConfig(
        min_exit_notional_usd=Decimal("100"),
        base_exit_pct=25.0,
        strong_exit_pct=50.0,
    )
    micro = evaluate_fast_profit(
        symbol="BTCUSDT",
        side="LONG",
        quantity=Decimal("0.1"),
        entry_price=Decimal("100"),
        mark_price=Decimal("101.5"),
        atr_pct=0.001,
        state=None,
        costs=CHEAP_COSTS,
        price_rejection=True,
        config=config,
    )
    # 0.1 * 101.5 = 10.15 USD leg: neither 25% nor full is economically meaningful.
    assert micro.trigger is False
    assert "EXIT_FRAGMENT_UNECONOMIC" in micro.blocking_reasons

    small_but_exitable = evaluate_fast_profit(
        symbol="BTCUSDT",
        side="LONG",
        quantity=Decimal("1"),
        entry_price=Decimal("100"),
        mark_price=Decimal("101.5"),
        atr_pct=0.001,
        state=None,
        costs=CHEAP_COSTS,
        price_rejection=True,
        config=config,
    )
    assert small_but_exitable.trigger is True
    assert small_but_exitable.exit_pct == 100.0  # 25% fragment would be < 100 USD


def test_configurable_fractions_and_offline_availability() -> None:
    config = FastProfitConfig(
        base_exit_pct=10.0,
        strong_exit_pct=40.0,
        severe_exit_pct=80.0,
        severe_score=5.0,
        min_reversal_score=0.5,
        min_exit_notional_usd=Decimal("0"),
    )
    decision = evaluate_fast_profit(
        symbol="ETHUSDT",
        side="LONG",
        quantity=Decimal("10"),
        entry_price=Decimal("100"),
        mark_price=Decimal("101"),
        atr_pct=0.001,
        state=_state(
            cvd=Decimal("-200"),
            buy=Decimal("400"),
            sell=Decimal("700"),
            imbalance=Decimal("-0.5"),
        ),
        costs=CHEAP_COSTS,
        config=config,
    )
    assert decision.trigger is True
    assert decision.exit_pct in (10.0, 40.0, 80.0)
    # The module needs no provider/network: it is usable in LLM_OFFLINE_MODE.
    assert decision.requires_llm_reassessment is True


def test_fast_profit_is_deterministic() -> None:
    def run():
        return evaluate_fast_profit(
            symbol="BTCUSDT",
            side="LONG",
            quantity=Decimal("10"),
            entry_price=Decimal("100"),
            mark_price=Decimal("101.2"),
            atr_pct=0.002,
            state=_state(
                cvd=Decimal("-300"),
                buy=Decimal("500"),
                sell=Decimal("800"),
                imbalance=Decimal("-0.4"),
            ),
            costs=CHEAP_COSTS,
        ).as_dict()

    assert run() == run()


def test_fast_profit_has_no_new_risk_or_execution_path() -> None:
    source = inspect.getsource(fast_profit)
    for forbidden in (
        "ExecutionAuthority",
        "OrderManager",
        "submit_order",
        "process_signal",
        "SignalIntent",
        "TradePlan",
    ):
        assert forbidden not in source, f"fast profit must not reference {forbidden}"
    assert fast_profit.evaluate_fast_profit is not None
