from decimal import Decimal

from crypto_trader.deepseek.calibration import calibrate_confidence
from crypto_trader.deepseek.client import DeepSeekClient
from crypto_trader.deepseek.decision_engine import fuse_quant_deepseek
from crypto_trader.deepseek.market_selector import DeepSeekMarketSelector
from crypto_trader.deepseek.memory import AIExperienceMemory, AIExperienceRecord
from crypto_trader.deepseek.review import build_review
from crypto_trader.deepseek.risk_committee import apply_capital_review
from crypto_trader.deepseek.schemas import CapitalReview, MarketOpinion
from crypto_trader.execution_intelligence.fee_model import FeeModel


def test_deepseek_client_never_logs_key():
    client = DeepSeekClient(api_key=None)
    assert client.configured() is False


def test_schemas_validate():
    opinion = MarketOpinion(
        symbol="BTCUSDT",
        direction="LONG",
        confidence=0.8,
        timeframe="1h",
        reasoning="trend",
        risk_level="LOW",
        invalid_conditions=[],
    )
    assert opinion.direction == "LONG"


def test_market_selector_ranking():
    selector = DeepSeekMarketSelector()
    scores = selector.rank(
        [
            {
                "symbol": "BTCUSDT",
                "trend": "BULL",
                "momentum": "0.3",
                "liquidity": "9",
                "volatility": "1",
                "funding_score": "1",
            },
            {
                "symbol": "PEPEUSDT",
                "trend": "BEAR",
                "momentum": "-0.5",
                "liquidity": "3",
                "volatility": "8",
                "funding_score": "0",
            },
        ]
    )
    assert scores[0].symbol == "BTCUSDT"
    assert scores[0].direction == "LONG"


def test_fusion_agreement_conflict():
    decision = fuse_quant_deepseek(
        symbol="BTCUSDT",
        quant_direction="LONG",
        quant_confidence=0.7,
        deepseek_direction="LONG",
        deepseek_confidence=0.8,
    )
    assert decision.fusion_type == "AGREEMENT"
    assert decision.confidence > 0.7
    conflict = fuse_quant_deepseek(
        symbol="BTCUSDT",
        quant_direction="LONG",
        quant_confidence=0.7,
        deepseek_direction="SHORT",
        deepseek_confidence=0.8,
    )
    assert conflict.decision == "NO_TRADE"


def test_large_capital_review_adjusts():
    review = CapitalReview(
        symbol="BTCUSDT",
        decision="ADJUST",
        risk_level="MEDIUM",
        recommended_size=25000,
        recommended_leverage=3,
        reasoning="size risk",
    )
    result = apply_capital_review(Decimal("50000"), Decimal("10"), review)
    assert result.decision == "ADJUST"
    assert result.approved_size == Decimal("25000")
    assert result.approved_leverage == Decimal("3")


def test_fee_model_net_cost_ratio():
    model = FeeModel()
    breakdown = model.calculate(
        order_size="1",
        price="100",
        leverage="5",
        maker_fee_rate="0.0002",
        taker_fee_rate="0.0005",
        funding_rate="0.0001",
        holding_hours="8",
        slippage_bps="2",
        market_impact_bps="1",
        expected_gross_pnl="10",
    )
    assert breakdown.total_cost > 0
    assert breakdown.cost_ratio < Decimal("0.5")
    assert model.profitability_decision(breakdown.cost_ratio) in (
        "NORMAL",
        "REDUCE_POSITION",
        "REJECT",
    )


def test_ai_memory_review_calibration():
    memory = AIExperienceMemory()
    record = AIExperienceRecord(
        symbol="BTCUSDT",
        market_state={"price": "100"},
        ai_prediction="LONG",
        confidence=0.85,
        quant_signal="LONG",
        final_decision="LONG",
    )
    memory.store(record)
    assert memory.count() == 1
    review = build_review("BTCUSDT", "LONG", "LOSS")
    assert review.lesson != ""
    cal = calibrate_confidence(confidence=Decimal("0.9"), historical_accuracy=Decimal("0.6"))
    assert cal.adjusted_confidence < Decimal("0.9")
