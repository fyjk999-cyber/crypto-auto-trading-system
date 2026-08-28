from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from crypto_trader.config import Settings
from crypto_trader.exchange.symbol_mapper import DEFAULT_TRADING_SYMBOLS, SymbolMapper
from crypto_trader.market_data.orderbook import OrderBook
from crypto_trader.runtime.live_decision_context import LiveDecisionContextProvider
from crypto_trader.runtime.multi_symbol_chief_trader import MultiSymbolChiefTraderStrategyAdapter
from crypto_trader.runtime.opportunity_scanner import CheapOpportunityScanner, OpportunityScore
from crypto_trader.simulator.real_market_paper import PaperRealMarketAdapter


def test_default_symbol_universe_contains_20_unique_supported_coins():
    settings = Settings(_env_file=None)
    assert settings.symbol_universe == DEFAULT_TRADING_SYMBOLS
    assert len(settings.symbol_universe) == 20
    assert len(set(settings.symbol_universe)) == 20
    mapper = SymbolMapper()
    for symbol in settings.symbol_universe:
        assert mapper.to_canonical(mapper.to_okx(symbol)) == symbol


def test_symbol_mapper_uses_okx_usdt_swap_contracts():
    mapper = SymbolMapper()
    assert mapper.to_okx("BTCUSDT") == "BTC-USDT-SWAP"
    assert mapper.to_okx("ETHUSDT") == "ETH-USDT-SWAP"
    assert mapper.to_okx("BNBUSDT") == "BNB-USDT-SWAP"
    assert mapper.to_okx("UNIUSDT") == "UNI-USDT-SWAP"
    with pytest.raises(ValueError):
        mapper.to_okx("UNKNOWNUSDT")


def test_multi_symbol_chief_trader_rotates_one_symbol_per_context_request():
    adapter = MultiSymbolChiefTraderStrategyAdapter(
        symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
        opportunity_scanner_enabled=False,
    )
    assert [adapter.symbol for _ in range(5)] == [
        "BTCUSDT",
        "ETHUSDT",
        "SOLUSDT",
        "BTCUSDT",
        "ETHUSDT",
    ]


class _StubFeed:
    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self.client = object()

    async def close(self) -> None:
        return None


def test_paper_real_market_adapter_keeps_feed_state_isolated_per_symbol():
    adapter = PaperRealMarketAdapter(feed_factory=_StubFeed)
    btc = adapter._feed_for("BTCUSDT")
    eth = adapter._feed_for("ETHUSDT")
    sol = adapter._feed_for("SOLUSDT")
    assert btc.symbol == "BTCUSDT"
    assert eth.symbol == "ETHUSDT"
    assert sol.symbol == "SOLUSDT"
    assert btc is not eth
    assert eth is not sol
    assert adapter._feed_for("ETHUSDT") is eth


def _candles(symbol: str, *, slope: float = 0.0, recent_volume: float = 100.0) -> list[dict]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    rows = []
    for index in range(80):
        price = 100.0 + index * slope
        rows.append(
            {
                "symbol": symbol,
                "interval": "1m",
                "open_time": (start + timedelta(minutes=index)).isoformat(),
                "open": str(price),
                "high": str(price + 0.2),
                "low": str(price - 0.2),
                "close": str(price + slope),
                "volume": str(recent_volume if index >= 75 else 100.0),
                "source": "TEST_REAL_SHAPE",
            }
        )
    return rows


def _book(symbol: str, *, bid_qty: str = "10", ask_qty: str = "10") -> OrderBook:
    book = OrderBook(symbol=symbol, exchange="TEST")
    book.apply_snapshot(
        1,
        [(Decimal("100.00"), Decimal(bid_qty))],
        [(Decimal("100.02"), Decimal(ask_qty))],
    )
    return book


def test_cheap_opportunity_scanner_prefers_momentum_volume_and_imbalance():
    scanner = CheapOpportunityScanner(min_score=0.10, max_spread_bps=15.0)
    quiet_ctx = SimpleNamespace(
        symbol="BTCUSDT",
        book=_book("BTCUSDT"),
        funding=Decimal("0"),
        basis=Decimal("0"),
    )
    active_ctx = SimpleNamespace(
        symbol="ETHUSDT",
        book=_book("ETHUSDT", bid_qty="30", ask_qty="5"),
        funding=Decimal("0.0004"),
        basis=Decimal("0.001"),
    )
    quiet = scanner.score(quiet_ctx, _candles("BTCUSDT"))
    active = scanner.score(
        active_ctx,
        _candles("ETHUSDT", slope=0.08, recent_volume=300.0),
    )
    assert active.eligible is True
    assert active.score > quiet.score
    assert active.direction == "LONG_BIAS"
    assert active.components["volume_impulse"] > 0
    assert active.components["orderbook_imbalance"] > 0


@pytest.mark.asyncio
async def test_live_decision_context_reuses_cached_candles_for_full_build():
    calls = 0

    async def candles(symbol: str) -> list[dict]:
        nonlocal calls
        calls += 1
        return _candles(symbol, slope=0.02)

    provider = LiveDecisionContextProvider(
        candle_provider=candles,
        symbol="BTCUSDT",
        candle_cache_seconds=60.0,
    )
    first = await provider.get_candles("BTCUSDT")
    second = await provider.get_candles("BTCUSDT")
    bundle = await provider.build({}, symbol="BTCUSDT")
    assert first == second
    assert bundle is not None
    assert calls == 1


class _HealthyProvider:
    def healthy(self) -> bool:
        return True

    def route_ready(self) -> bool:
        return True


class _CandleAccess:
    async def get_candles(self, symbol: str) -> list[dict]:
        return []

    def set_symbol(self, symbol: str) -> None:
        return None


class _StaticScanner:
    SCORES = {"BTCUSDT": 0.10, "ETHUSDT": 0.90, "SOLUSDT": 0.80}

    def score(self, ctx, candles) -> OpportunityScore:
        score = self.SCORES[ctx.symbol]
        return OpportunityScore(
            symbol=ctx.symbol,
            score=score,
            eligible=score >= 0.20,
            direction="LONG_BIAS",
            spread_bps=1.0,
            components={"test": score},
            reason="OK" if score >= 0.20 else "SCORE_BELOW_THRESHOLD",
        )


class _RecordingMultiSymbolChief(MultiSymbolChiefTraderStrategyAdapter):
    def __init__(self, **kwargs) -> None:
        self.decided: list[str] = []
        super().__init__(**kwargs)

    async def _decide(self, ctx):
        self.decided.append(ctx.symbol)
        return []


@pytest.mark.asyncio
async def test_multi_symbol_opportunity_ranking_is_advisory_not_an_ai_gate():
    adapter = _RecordingMultiSymbolChief(
        symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
        provider=_HealthyProvider(),
        decision_context_provider=_CandleAccess(),
        opportunity_scanner=_StaticScanner(),
        opportunity_top_k=2,
        min_decision_interval_seconds=0.0,
    )

    for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        await adapter.on_market_data(SimpleNamespace(symbol=symbol))

    assert adapter.eligible_symbols == ("ETHUSDT", "SOLUSDT")
    assert [item["symbol"] for item in adapter.opportunity_ranking[:2]] == [
        "ETHUSDT",
        "SOLUSDT",
    ]
    # BTC has the lowest score and is below the scanner's eligibility threshold,
    # but it still reaches the AI decision path. Quant ranking is evidence only.
    assert adapter.decided == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


@pytest.mark.asyncio
async def test_live_decision_context_builds_independent_symbol_evidence():
    start = datetime(2026, 1, 1, tzinfo=UTC)

    async def candles(symbol: str) -> list[dict]:
        bias = 100 if symbol == "BTCUSDT" else 200
        return [
            {
                "symbol": symbol,
                "interval": "1m",
                "open_time": (start + timedelta(minutes=index)).isoformat(),
                "open": str(bias + index * 0.1),
                "high": str(bias + index * 0.1 + 0.2),
                "low": str(bias + index * 0.1 - 0.2),
                "close": str(bias + index * 0.1 + 0.1),
                "volume": "100",
                "source": "TEST_REAL_SHAPE",
            }
            for index in range(80)
        ]

    provider = LiveDecisionContextProvider(candle_provider=candles, symbol="BTCUSDT")
    btc = await provider.build({}, symbol="BTCUSDT")
    eth = await provider.build({}, symbol="ETHUSDT")
    assert btc is not None
    assert eth is not None
    assert btc.evidence["symbol"] == "BTCUSDT"
    assert eth.evidence["symbol"] == "ETHUSDT"
    assert set(provider._evidence_builders) == {"BTCUSDT", "ETHUSDT"}
