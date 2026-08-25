from crypto_trader.ai_brain.decision.decision_engine import AITradingBrain
from crypto_trader.ai_brain.exit_manager.manager import ExitManager
from crypto_trader.ai_brain.learning.loop import LearningLoop
from crypto_trader.ai_brain.position_manager.manager import PositionManager
from crypto_trader.ai_brain.review.engine import TradeReviewEngine


def test_ai_brain_no_thesis_no_trade():
    brain = AITradingBrain()
    intent = brain.analyze(
        symbol="BTC-USDT",
        market_state="TRENDING",
        factor_intelligence={"risk_notes": ["funding extreme"]},
    )
    assert intent.action == "NO_TRADE"


def test_ai_brain_long_with_self_challenge():
    brain = AITradingBrain()
    intent = brain.analyze(
        symbol="BTC-USDT",
        market_state="TRENDING",
        direction="LONG",
        thesis="trend continuation",
        supporting=["trend healthy", "OI confirmation"],
        contradicting=["funding extreme"],
        confidence=0.8,
    )
    assert intent.action == "OPEN_LONG"
    assert intent.confidence < 0.8
    assert "funding extreme" in intent.risks


def test_ai_brain_low_confidence_no_trade():
    brain = AITradingBrain()
    intent = brain.analyze(
        symbol="BTC-USDT",
        market_state="RANGING",
        direction="LONG",
        thesis="breakout",
        supporting=[],
        contradicting=["range", "weak volume", "funding", "no OI"],
        confidence=0.3,
    )
    assert intent.action == "NO_TRADE"


def test_position_manager_dynamic_decisions():
    manager = PositionManager()
    assert (
        manager.decide(
            symbol="BTC-USDT", thesis_valid=False, risk_increased=False, opportunity_score=0.5
        ).action
        == "EXIT"
    )
    assert (
        manager.decide(
            symbol="BTC-USDT", thesis_valid=True, risk_increased=True, opportunity_score=0.5
        ).action
        == "REDUCE"
    )
    assert (
        manager.decide(
            symbol="BTC-USDT", thesis_valid=True, risk_increased=False, opportunity_score=0.8
        ).action
        == "ADD"
    )
    assert (
        manager.decide(
            symbol="BTC-USDT", thesis_valid=True, risk_increased=False, opportunity_score=0.4
        ).action
        == "HOLD"
    )


def test_exit_manager_reasons():
    manager = ExitManager()
    exit_reason = manager.reason(
        symbol="BTC-USDT",
        thesis_valid=False,
        risk_increased=False,
        better_opportunity=False,
        profit_target_hit=False,
        time_window_expired=False,
    )
    assert exit_reason.category == "THESIS_INVALIDATED"
    assert (
        manager.reason(
            symbol="BTC-USDT",
            thesis_valid=True,
            risk_increased=False,
            better_opportunity=False,
            profit_target_hit=False,
            time_window_expired=False,
        )
        is None
    )


def test_trade_review_and_learning_loop():
    review = TradeReviewEngine().review(
        symbol="BTC-USDT",
        why_buy="trend",
        why_hold="thesis intact",
        why_sell="target hit",
        result="WIN",
        ignored=["funding extreme"],
    )
    assert review.correct_decisions
    loop = LearningLoop()
    record = loop.learn(symbol="BTC-USDT", result="WIN", mistakes=[], lesson="confirm trend")
    assert record["lesson"] == "confirm trend"
