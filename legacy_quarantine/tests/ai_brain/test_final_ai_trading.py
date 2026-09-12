from crypto_trader.ai_brain.decision.decision_engine import AITradingBrain
from crypto_trader.learning.evaluator import TradeEvaluator
from crypto_trader.learning.mistake import MistakeLog
from crypto_trader.learning.pattern import PatternMemory
from crypto_trader.position_manager.engine import PositionIntelligence, PositionStateMachine


def test_decision_scenarios_bull_bear_sideways_highvol():
    brain = AITradingBrain()
    bull = brain.analyze(
        symbol="BTC-USDT",
        market_state="TRENDING",
        direction="LONG",
        thesis="trend",
        supporting=["trend healthy"],
        contradicting=[],
        confidence=0.7,
    )
    assert bull.action == "OPEN_LONG"
    bear = brain.analyze(
        symbol="BTC-USDT",
        market_state="TRENDING",
        direction="LONG",
        thesis="weak",
        supporting=[],
        contradicting=["downtrend", "weak volume"],
        confidence=0.3,
    )
    assert bear.action == "NO_TRADE"
    sideways = brain.analyze(
        symbol="BTC-USDT",
        market_state="RANGING",
        direction="LONG",
        thesis="breakout",
        supporting=[],
        contradicting=["range"],
        confidence=0.25,
    )
    assert sideways.action == "NO_TRADE"
    high_vol = brain.analyze(
        symbol="BTC-USDT",
        market_state="HIGH_VOLATILITY",
        direction="LONG",
        thesis="vol breakout",
        supporting=[],
        contradicting=["volatility extreme"],
        confidence=0.3,
    )
    assert high_vol.action == "NO_TRADE"


def test_position_state_machine_lifecycle():
    sm = PositionStateMachine()
    sm.transition("ENTERED", "entry")
    sm.transition("MONITORING", "watching")
    sm.transition("ADJUSTING", "reduce")
    sm.transition("EXIT_PENDING", "close")
    sm.transition("EXITED", "closed")
    sm.transition("REVIEW", "review")
    assert sm.state == "REVIEW"
    assert len(sm.history) == 6


def test_position_intelligence_profit_and_loss():
    pi = PositionIntelligence()
    assert pi.decide(thesis_valid=True, risk_increased=False, opportunity_score=0.4) == "HOLD"
    assert pi.decide(thesis_valid=True, risk_increased=True, opportunity_score=0.4) == "REDUCE"
    assert pi.decide(thesis_valid=False, risk_increased=False, opportunity_score=0.4) == "EXIT"


def test_learning_system_records_and_reads():
    evaluator = TradeEvaluator()
    review = evaluator.evaluate(
        symbol="BTC-USDT",
        entry_reason="trend",
        exit_reason="thesis invalidated",
        was_win=False,
        mistakes=["chase entry"],
        lessons=["wait confirmation"],
    )
    assert review.decision_quality == 0.4
    mistakes = MistakeLog()
    mistakes.add("chase", "BTC-USDT", "entered late")
    mistakes.add("chase", "ETH-USDT", "entered late again")
    assert mistakes.frequent() == ["chase"]
    patterns = PatternMemory()
    patterns.save(
        market_pattern="trend_breakout", decision="LONG", result="WIN", lesson="volume confirms"
    )
    assert len(patterns.find("trend_breakout")) == 1
