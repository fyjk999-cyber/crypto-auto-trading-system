"""Phase 1 (Low-Risk V2) market/data evidence tests.

These tests prove the extended factual market pipeline:
- taker-flow/CVD and L5/L10 microstructure facts are derived from real OKX
  public payload shapes (deterministic fixtures, no network);
- evidence-only data can never gate or authorize execution;
- caches are bounded and stale/missing evidence is explicitly degraded;
- the evidence layer has no order authority (no execution/order imports).
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from crypto_trader.market_data import okx_public_feed
from crypto_trader.market_data import state as state_module
from crypto_trader.market_data.okx_public_feed import OKXPublicMarketFeed
from crypto_trader.market_data.opportunity.eligibility import EligibilityFilter, EligibilityLimits
from crypto_trader.market_data.state import DataHealth

NOW_MS = 1_760_000_000_000


def _now_ms() -> int:
    return int(datetime.now(UTC).timestamp() * 1000)


class FakeOKXClient:
    """Minimal deterministic stand-in for OKXAdapter public REST methods."""

    def __init__(
        self,
        *,
        trades: list[dict] | None = None,
        trades_error: Exception | None = None,
        book_error: Exception | None = None,
    ) -> None:
        self.trades = trades if trades is not None else _default_trades()
        self.trades_error = trades_error
        self.book_error = book_error

    async def get_ticker(self, symbol: str) -> dict:
        return {"last": "100.0", "volume_24h": "12345", "source_timestamp": str(NOW_MS)}

    async def get_orderbook(self, symbol: str, limit: int = 100) -> dict:
        if self.book_error is not None:
            raise self.book_error
        return {
            "data": [
                {
                    "ts": str(NOW_MS),
                    "bids": [
                        ["99.9", "10"],
                        ["99.8", "8"],
                        ["99.7", "6"],
                        ["99.6", "4"],
                        ["99.5", "2"],
                        ["99.4", "1"],
                    ],
                    "asks": [
                        ["100.1", "5"],
                        ["100.2", "4"],
                        ["100.3", "3"],
                        ["100.4", "2"],
                        ["100.5", "1"],
                        ["100.6", "1"],
                    ],
                }
            ]
        }

    async def get_mark_price(self, symbol: str) -> dict:
        return {"mark_price": "100.05", "source_timestamp": str(NOW_MS)}

    async def get_index_price(self, symbol: str) -> dict:
        return {"index_price": "100.0", "source_timestamp": str(NOW_MS)}

    async def get_funding_rate(self, symbol: str) -> dict:
        return {"funding_rate": "0.0001", "next_funding_time": None}

    async def get_open_interest(self, symbol: str) -> dict:
        return {"open_interest": "900000", "source_timestamp": str(NOW_MS)}

    async def get_trades(self, symbol: str, limit: int = 100) -> list[dict]:
        if self.trades_error is not None:
            raise self.trades_error
        return list(self.trades)


def _default_trades() -> list[dict]:
    now = _now_ms()
    return [
        {"tradeId": "t1", "px": "100.0", "sz": "2", "side": "buy", "ts": str(now - 3000)},
        {"tradeId": "t2", "px": "100.0", "sz": "1", "side": "sell", "ts": str(now - 2000)},
        {
            "tradeId": "t3",
            "px": "100.1",
            "sz": "5",
            "side": "buy",
            "ts": str(now - 1000),
        },
    ]


def _fresh_feed(client: FakeOKXClient, **kwargs) -> OKXPublicMarketFeed:
    return OKXPublicMarketFeed(symbol="BTCUSDT", client=client, **kwargs)


async def test_taker_flow_cvd_and_depth_facts_are_factual() -> None:
    feed = _fresh_feed(FakeOKXClient())
    state = await feed.refresh("BTCUSDT")

    assert state.taker_buy_volume == Decimal("7")
    assert state.taker_sell_volume == Decimal("1")
    assert state.cvd == Decimal("6")
    assert state.trade_count == 3
    assert state.trade_notional == Decimal("800.5")
    assert state.last_trade_price == Decimal("100.1")
    assert state.trades_window_seconds == pytest.approx(2.0)

    # L5 depth: bids 10+8+6+4+2 = 30, asks 5+4+3+2+1 = 15.
    assert state.depth_bid_5 == Decimal("30")
    assert state.depth_ask_5 == Decimal("15")
    assert state.depth_bid_10 == Decimal("31")
    assert state.depth_ask_10 == Decimal("16")
    assert float(state.imbalance_l5) == pytest.approx(15 / 45)
    # microprice lies between the best bid/ask and is quantity weighted.
    assert state.best_bid < state.microprice < state.best_ask
    assert float(state.spread_bps) == pytest.approx(20.0)
    assert state.sources["trades"].status == DataHealth.HEALTHY
    assert state.evidence_quality == DataHealth.HEALTHY


async def test_trades_window_dedups_and_is_bounded() -> None:
    now = _now_ms()
    trades = [
        {"tradeId": "a", "px": "100", "sz": "1", "side": "buy", "ts": str(now - 4000)},
        {"tradeId": "b", "px": "100", "sz": "1", "side": "sell", "ts": str(now - 3000)},
    ]
    client = FakeOKXClient(trades=trades)
    feed = _fresh_feed(client, trades_limit=5)
    first = await feed.refresh("BTCUSDT")
    assert first.trade_count == 2

    # Provider now returns the same ids plus a new one: dedup must keep 3 only.
    client.trades = trades + [
        {"tradeId": "c", "px": "101", "sz": "3", "side": "buy", "ts": str(_now_ms() - 1000)}
    ]
    feed.min_refresh_interval = timedelta(seconds=0)
    second = await feed.refresh("BTCUSDT")
    assert second.trade_count == 3
    assert second.taker_buy_volume == Decimal("4")
    assert second.taker_sell_volume == Decimal("1")

    # Window length is bounded even if the provider keeps returning new ids.
    for index in range(20):
        client.trades = [
            {
                "tradeId": f"x{index}",
                "px": "100",
                "sz": "1",
                "side": "buy",
                "ts": str(_now_ms() - 500 + index),
            }
        ]
        feed.min_refresh_interval = timedelta(seconds=0)
        await feed.refresh("BTCUSDT")
    assert len(feed._trades["BTCUSDT"]) <= 5


async def test_missing_trades_degrades_evidence_but_never_core_health() -> None:
    client = FakeOKXClient(trades_error=RuntimeError("trades endpoint down"))
    feed = _fresh_feed(client)
    state = await feed.refresh("BTCUSDT")

    # Core execution health is unaffected by an evidence-only stream.
    assert state.health == DataHealth.HEALTHY
    assert state.new_risk_allowed is True
    # Evidence is explicitly degraded and no stale value is fabricated.
    assert state.evidence_quality == DataHealth.DEGRADED
    assert any("TRADES_UNAVAILABLE" in reason for reason in state.evidence_degraded_reasons)
    assert state.cvd is None
    assert state.taker_buy_volume is None
    assert state.trade_count == 0


async def test_core_book_failure_blocks_new_risk_and_quality() -> None:
    client = FakeOKXClient(book_error=RuntimeError("book down"))
    feed = _fresh_feed(client)
    state = await feed.refresh("BTCUSDT")

    assert state.health == DataHealth.UNAVAILABLE
    assert state.new_risk_allowed is False
    assert state.evidence_quality == DataHealth.UNAVAILABLE
    assert state.best_bid == 0 and state.best_ask == 0


async def test_multi_symbol_cache_is_bounded_and_pins_execution_symbol() -> None:
    feed = _fresh_feed(FakeOKXClient(), max_cached_symbols=3)
    for index in range(6):
        await feed.refresh(f"SYM{index}USDT")
    assert len(feed.states) <= 3
    assert "BTCUSDT" in feed.states or len(feed.states) == 3
    # Pinned default symbol survives eviction pressure.
    await feed.refresh("BTCUSDT")
    for index in range(10):
        await feed.refresh(f"OTHER{index}USDT")
    assert "BTCUSDT" in feed.states


def test_eligibility_prefilter_is_evidence_only_and_optional() -> None:
    filt = EligibilityFilter(
        EligibilityLimits(
            min_volume_24h_usd=100.0,
            min_book_depth_usd_l5=1000.0,
            min_trade_notional_window_usd=500.0,
        )
    )
    thin = filt.evaluate(
        "BTCUSDT",
        last_price=100.0,
        bid=99.9,
        ask=100.1,
        volume_24h_usd=1_000.0,
        ticker_age_seconds=1.0,
        candle_count=100,
        depth_usd_l5=100.0,
        trade_notional_window_usd=10.0,
    )
    assert thin.eligible is False
    assert "THIN_BOOK" in thin.reasons
    assert "NO_TRADE_ACTIVITY" in thin.reasons

    # Callers that cannot supply the new facts keep the previous verdict.
    legacy = filt.evaluate(
        "BTCUSDT",
        last_price=100.0,
        bid=99.9,
        ask=100.1,
        volume_24h_usd=1_000.0,
        ticker_age_seconds=1.0,
        candle_count=100,
    )
    assert legacy.eligible is True


def test_market_evidence_layer_has_no_order_authority() -> None:
    sources = [
        inspect.getsource(okx_public_feed),
        inspect.getsource(state_module),
    ]
    combined = "\n".join(sources)
    for forbidden in (
        "ExecutionAuthority",
        "OrderManager",
        "submit_order",
        "process_signal",
        "SignalIntent",
    ):
        assert forbidden not in combined, f"evidence layer must not reference {forbidden}"
