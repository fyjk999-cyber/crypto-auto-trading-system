from crypto_trader.ai_brain.decision.decision_engine import AITradingBrain
from crypto_trader.ai_brain.position_manager.manager import PositionContext, PositionManager
from crypto_trader.ai_brain.position_manager.state import PositionLifecycle
from crypto_trader.ai_brain.runtime_adapter import map_trading_intent


def test_hold_when_thesis_intact():
    manager = PositionManager()
    ctx = PositionContext(
        symbol="BTC-USDT",
        position_side="LONG",
        position_quantity=1.0,
        thesis_status="THESIS_INTACT",
        supporting_evidence=["trend healthy"],
    )
    decision = manager.decide(ctx)
    assert decision.action == "HOLD"
    assert decision.reason != ""


def test_hold_does_not_order():
    mapping = map_trading_intent(intent_action="HOLD", position_side="LONG", position_quantity=1.0)
    assert mapping.executable is False


def test_reduce_when_thesis_weakens():
    manager = PositionManager()
    ctx = PositionContext(
        symbol="BTC-USDT",
        position_side="LONG",
        position_quantity=1.0,
        thesis_status="THESIS_WEAKENING",
        unrealized_pnl=10.0,
    )
    decision = manager.decide(ctx)
    assert decision.action == "REDUCE"
    assert decision.requested_change <= 1.0


def test_exit_when_thesis_invalidated():
    manager = PositionManager()
    ctx = PositionContext(
        symbol="BTC-USDT",
        position_side="LONG",
        position_quantity=1.0,
        thesis_status="THESIS_INVALIDATED",
    )
    assert manager.decide(ctx).action == "EXIT"


def test_hard_risk_exit_priority():
    manager = PositionManager()
    ctx = PositionContext(
        symbol="BTC-USDT",
        position_side="LONG",
        position_quantity=1.0,
        thesis_status="THESIS_INTACT",
        hard_risk_exit=True,
    )
    assert manager.decide(ctx).exit_reason == "EMERGENCY_RISK_EXIT"


def test_add_only_when_thesis_strengthens():
    manager = PositionManager()
    ctx = PositionContext(
        symbol="BTC-USDT",
        position_side="LONG",
        position_quantity=1.0,
        thesis_status="THESIS_STRENGTHENING",
    )
    assert manager.decide(ctx).action == "ADD"


def test_no_martingale_add_on_loss():
    manager = PositionManager()
    ctx = PositionContext(
        symbol="BTC-USDT",
        position_side="LONG",
        position_quantity=1.0,
        unrealized_pnl=-100.0,
        thesis_status="THESIS_WEAKENING",
    )
    decision = manager.decide(ctx)
    assert decision.action != "ADD"


def test_zero_position_cannot_reduce_or_exit_twice():
    manager = PositionManager()
    ctx = PositionContext(symbol="BTC-USDT", position_quantity=0.0)
    decision = manager.decide(ctx)
    assert decision.action == "NO_ACTION"
    mapping = map_trading_intent(intent_action="EXIT", position_side="LONG", position_quantity=0.0)
    assert mapping.executable is False


def test_reduce_caps_quantity_to_position():
    mapping = map_trading_intent(
        intent_action="REDUCE", position_side="LONG", position_quantity=1.0, requested_change=2.0
    )
    assert mapping.quantity == 1.0
    assert mapping.side == "SELL"
    assert mapping.reduce_only is True


def test_exit_does_not_reverse():
    mapping = map_trading_intent(intent_action="EXIT", position_side="LONG", position_quantity=1.0)
    assert mapping.quantity == 1.0
    assert mapping.side == "SELL"
    short_mapping = map_trading_intent(
        intent_action="EXIT", position_side="SHORT", position_quantity=1.0
    )
    assert short_mapping.side == "BUY"


def test_state_machine_legal_transitions():
    sm = PositionLifecycle()
    sm.transition("ENTERED", "entry")
    sm.transition("MONITORING", "monitor")
    sm.transition("ADJUSTING", "reduce")
    sm.transition("MONITORING", "re-evaluate")
    sm.transition("EXIT_PENDING", "exit")
    sm.transition("EXITED", "closed")
    sm.transition("REVIEW", "review")
    assert sm.state == "REVIEW"


def test_state_machine_illegal_transition_rejected():
    sm = PositionLifecycle()
    try:
        sm.transition("MONITORING", "bad")
        raise AssertionError()
    except ValueError:
        pass


def test_ai_brain_routes_position_aware():
    brain = AITradingBrain()
    # no position -> entry
    entry = brain.analyze(
        symbol="BTC-USDT",
        market_state="TRENDING",
        direction="LONG",
        thesis="trend",
        supporting=["trend healthy"],
        confidence=0.7,
    )
    assert entry.action == "OPEN_LONG"
    # active long + thesis intact -> HOLD
    hold = brain.analyze(
        symbol="BTC-USDT",
        market_state="TRENDING",
        active_position={
            "quantity": 1.0,
            "side": "LONG",
            "thesis_status": "THESIS_INTACT",
            "thesis": "trend",
        },
    )
    assert hold.action == "HOLD"
    # active long + invalidated -> EXIT
    exit_ = brain.analyze(
        symbol="BTC-USDT",
        market_state="RANGING",
        active_position={
            "quantity": 1.0,
            "side": "LONG",
            "thesis_status": "THESIS_INVALIDATED",
            "thesis": "trend",
        },
    )
    assert exit_.action == "EXIT"
    # active short + strengthening -> ADD
    add = brain.analyze(
        symbol="BTC-USDT",
        market_state="TRENDING",
        active_position={
            "quantity": 0.5,
            "side": "SHORT",
            "thesis_status": "THESIS_STRENGTHENING",
            "thesis": "downtrend",
        },
    )
    assert add.action == "ADD"


def test_simulated_runtime_lifecycle_open_hold_reduce_exit():
    """Simulated paper lifecycle using canonical state machine + intent mapping."""
    from crypto_trader.ai_brain.position_manager.state import PositionLifecycle

    brain = AITradingBrain()
    lifecycle = PositionLifecycle()
    position = {
        "quantity": 0.0,
        "side": "",
        "thesis_status": "THESIS_INTACT",
        "thesis": "trend",
        "hard_risk_exit": False,
    }

    # OPEN
    entry = brain.analyze(
        symbol="BTC-USDT",
        market_state="TRENDING",
        direction="LONG",
        thesis="trend",
        supporting=["trend healthy"],
        confidence=0.7,
    )
    mapping = map_trading_intent(
        intent_action=entry.action,
        position_side="LONG",
        position_quantity=0.0,
        requested_change=0.1,
    )
    assert mapping.executable is True
    assert mapping.side == "BUY"
    lifecycle.transition("ENTERED", "open long")
    position = {
        "quantity": 0.1,
        "side": "LONG",
        "thesis_status": "THESIS_INTACT",
        "thesis": "trend",
        "hard_risk_exit": False,
    }
    lifecycle.transition("MONITORING", "monitor")

    # HOLD on next tick
    hold = brain.analyze(symbol="BTC-USDT", market_state="TRENDING", active_position=position)
    assert hold.action == "HOLD"
    assert (
        map_trading_intent(
            intent_action="HOLD", position_side="LONG", position_quantity=0.1
        ).executable
        is False
    )

    # REDUCE after risk increase
    position["thesis_status"] = "THESIS_WEAKENING"
    reduce_ = brain.analyze(
        symbol="BTC-USDT", market_state="HIGH_VOLATILITY", active_position=position
    )
    assert reduce_.action == "REDUCE"
    reduce_mapping = map_trading_intent(
        intent_action=reduce_.action,
        position_side="LONG",
        position_quantity=position["quantity"],
        requested_change=0.03,
    )
    assert reduce_mapping.quantity == 0.03
    lifecycle.transition("ADJUSTING", "partial reduce")

    # EXIT after invalidation
    position["thesis_status"] = "THESIS_INVALIDATED"
    exit_ = brain.analyze(symbol="BTC-USDT", market_state="RANGING", active_position=position)
    assert exit_.action == "EXIT"
    exit_mapping = map_trading_intent(
        intent_action="EXIT", position_side="LONG", position_quantity=position["quantity"]
    )
    assert exit_mapping.quantity == 0.1
    lifecycle.transition("EXIT_PENDING", "exit")
    lifecycle.transition("EXITED", "closed")
    lifecycle.transition("REVIEW", "review")
    assert lifecycle.state == "REVIEW"
