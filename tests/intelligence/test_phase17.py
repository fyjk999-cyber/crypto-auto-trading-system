from decimal import Decimal

from crypto_trader.ai_interface.context_builder import AIContextBuilder
from crypto_trader.features.vectors import MarketFeatureVector
from crypto_trader.intelligence.derivatives import DerivativesEngine
from crypto_trader.intelligence.opportunity import OpportunityEngine
from crypto_trader.intelligence.position_analytics import LongShortProfit, PositionAnalytics
from crypto_trader.risk_v3.engine import DailyLossGuard, EmergencyRiskMode, LossStreakGuard, RiskV3
from crypto_trader.risk_v3.portfolio_risk import PortfolioRiskEngine
from crypto_trader.universe.manager import UniverseManager


def test_universe_discovery_and_mapping():
    universe = UniverseManager()
    assets = universe.list_enabled()
    assert len(assets) >= 4
    assert universe.get("BTCUSDT").provider_symbol == "BTC-USDT-SWAP"
    assert universe.provider_symbol("BTCUSDT") == "BTC-USDT-SWAP"


def test_feature_vector_from_closes():
    closes = [Decimal(100) + Decimal(i) * Decimal("0.1") for i in range(30)]
    feature = MarketFeatureVector.from_closes("BTCUSDT", closes)
    assert feature.price == closes[-1]
    assert feature.ema20 > 0
    assert feature.regime == "BULL"


def test_derivatives_parse():
    funding = DerivativesEngine.parse_funding({"fundingRate": "0.0001"})
    assert funding == Decimal("0.0001")
    assert DerivativesEngine.parse_funding({"fundingRate": "0"}) is None
    oi, change = DerivativesEngine.parse_open_interest(
        {"openInterest": "1200", "previousOpenInterest": "1000"}
    )
    assert oi == Decimal("1200")
    assert change == Decimal("20")


def test_opportunity_ranking_long_and_short():
    engine = OpportunityEngine()
    up = MarketFeatureVector.from_closes("SOLUSDT", [Decimal(100) + Decimal(i) for i in range(30)])
    down = MarketFeatureVector.from_closes(
        "PEPEUSDT", [Decimal(200) - Decimal(i) for i in range(30)]
    )
    candidates = engine.rank([up, down], {})
    sides = {c.symbol: c.side for c in candidates}
    assert sides["SOLUSDT"] == "LONG"
    assert sides["PEPEUSDT"] == "SHORT"


def test_position_long_short_profit_analytics():
    long_pos = PositionAnalytics.analyze("BTCUSDT", "LONG", "100", "110", "1", "5", "20")
    short_pos = PositionAnalytics.analyze("SOLUSDT", "SHORT", "150", "140", "1", "5", "30")
    assert long_pos.unrealized_pnl == Decimal("10")
    assert short_pos.unrealized_pnl == Decimal("10")
    profit = LongShortProfit()
    profit.add("LONG", long_pos.unrealized_pnl)
    profit.add("SHORT", short_pos.unrealized_pnl)
    assert profit.total_long_pnl == Decimal("10")
    assert profit.total_short_pnl == Decimal("10")
    assert profit.net_pnl == Decimal("20")


def test_portfolio_risk_exposure():
    engine = PortfolioRiskEngine()
    snapshot = engine.analyze(
        [
            {"symbol": "BTCUSDT", "notional": "1000", "strategy": "trend", "beta": "1"},
            {"symbol": "ETHUSDT", "notional": "500", "strategy": "momentum", "beta": "1.2"},
        ]
    )
    assert snapshot.total_exposure == Decimal("1500")
    assert snapshot.asset_concentration["BTCUSDT"] > snapshot.asset_concentration["ETHUSDT"]


def test_risk_v3_30pct_drawdown_levels():
    risk = RiskV3()
    assert risk.evaluate(Decimal("10")).level == "NORMAL"
    assert risk.evaluate(Decimal("16")).level == "CAUTION"
    assert risk.evaluate(Decimal("22")).level == "DEFENSIVE"
    halted = risk.evaluate(Decimal("30"))
    assert halted.level == "HALTED"
    assert halted.new_risk_allowed is False
    assert halted.allow_reduce_close is True


def test_loss_streak_and_daily_loss_guards():
    guard = LossStreakGuard()
    for _ in range(3):
        guard.record_loss()
    assert guard.position_multiplier() == Decimal("0.5")
    for _ in range(2):
        guard.record_loss()
    assert guard.position_multiplier() == Decimal("0")
    daily = DailyLossGuard()
    daily.record_pnl(Decimal("-0.03"))
    assert daily.block_new_risk() is True


def test_emergency_mode_allows_reduce_close_only():
    emergency = EmergencyRiskMode()
    emergency.trigger("EXCHANGE_FAILURE")
    assert emergency.new_risk_allowed() is False
    assert emergency.reduce_close_allowed() is True


def test_ai_context_builder_no_llm():
    context = AIContextBuilder().build(
        symbol="BTCUSDT", feature_vector={"price": "100"}, risk_state={"level": "NORMAL"}
    )
    assert context.symbol == "BTCUSDT"
    assert context.feature_vector["price"] == "100"
