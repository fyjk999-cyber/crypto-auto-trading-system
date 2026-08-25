from decimal import Decimal

from crypto_trader.ai_backtest.walk_forward import WalkForwardValidator
from crypto_trader.evolution.analyzer import propose_from_error
from crypto_trader.evolution.promotion import EvolutionPromoter
from crypto_trader.evolution.validator import validate_proposal
from crypto_trader.llm.context import LLMContextBuilder, parse_llm_output
from crypto_trader.shadow.evaluation import ShadowEvaluator
from crypto_trader.shadow.virtual_position import VirtualPositionBook


def test_virtual_long_and_short_positions():
    book = VirtualPositionBook()
    long_pos = book.open("BTCUSDT", "LONG", "100", "1")
    assert long_pos.mark("110") == Decimal("10")
    book.close("BTCUSDT", "120")
    short_pos = book.open("SOLUSDT", "SHORT", "150", "1")
    assert short_pos.mark("140") == Decimal("10")
    book.close("SOLUSDT", "130")
    assert len(book.closed) == 2
    assert book.closed[0].exit_price == Decimal("120")


def test_shadow_evaluation_metrics():
    book = VirtualPositionBook()
    book.open("BTCUSDT", "LONG", "100", "1")
    book.close("BTCUSDT", "110")
    book.open("ETHUSDT", "SHORT", "200", "1")
    book.close("ETHUSDT", "195")
    metrics = ShadowEvaluator().evaluate(
        book.closed,
        [
            {"result": "CORRECT"},
            {"result": "CORRECT"},
        ],
    )
    assert metrics.trade_count == 2
    assert metrics.win_rate == Decimal("1")
    assert metrics.ai_accuracy == Decimal("1")


def test_walk_forward_no_future_leak():
    train = [{"result": "CORRECT"} for _ in range(8)]
    val = [{"result": "CORRECT"} for _ in range(5)]
    oos = [{"result": "CORRECT"} for _ in range(4)]
    report = WalkForwardValidator().validate(
        train_results=train, validation_results=val, oos_results=oos
    )
    assert report.passed is True
    bad_oos = [{"result": "CORRECT"}] * 2 + [{"result": "WRONG"}] * 6
    report2 = WalkForwardValidator().validate(
        train_results=train, validation_results=val, oos_results=bad_oos
    )
    assert report2.passed is False


def test_evolution_promotion_requires_full_evidence():
    proposal = propose_from_error("p1", "FALSE_LONG", "MEME")
    assert "momentum_weight_meme" in proposal.parameter_changes
    assert validate_proposal(proposal).passed is True
    promoter = EvolutionPromoter()
    assert promoter.promote(proposal, ["BACKTEST_PASS"]).promoted is False
    result = promoter.promote(
        proposal, ["BACKTEST_PASS", "OOS_PASS", "WALK_FORWARD_PASS", "SHADOW_PASS"]
    )
    assert result.promoted is True


def test_llm_context_and_output_schema():
    ctx = LLMContextBuilder().build(
        symbol="BTCUSDT", market_state={"price": "100"}, risk_state={"level": "NORMAL"}
    )
    prompt = LLMContextBuilder().render_prompt(ctx)
    assert "BTCUSDT" in prompt
    output = parse_llm_output(
        {
            "direction": "LONG",
            "confidence": 0.8,
            "risk_level": "MEDIUM",
            "reason_codes": ["REGIME_BULL"],
            "invalid_conditions": [],
        }
    )
    assert output.direction == "LONG"
