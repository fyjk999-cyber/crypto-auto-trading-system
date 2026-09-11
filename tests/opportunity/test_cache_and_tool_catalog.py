"""Gate 4 tests: canonical shared market-data cache (§10) + tool catalog (§9)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from crypto_trader.llm.tools.alpha import build_canonical_tool_registry
from crypto_trader.llm.tools.context import register_context_tools
from crypto_trader.llm.tools.factor_runtime import register_factor_runtime_tools
from crypto_trader.llm.tools.market_history import register_market_history_tool
from crypto_trader.market_data.cache import (
    MarketDataCache,
    as_of_bucket,
    candle_cache_key,
    closed_candle_ttl_seconds,
)
from crypto_trader.market_data.quality import REQUEST_FAILED


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_cache_hit_within_ttl_and_stale_never_served():
    clock = FakeClock()
    cache = MarketDataCache(clock=clock)
    key = candle_cache_key(instrument="BTC-USDT-SWAP", timeframe="1m", limit=120)
    assert cache.put(key, [[1, 2]], source="okx") is True
    assert cache.get(key, ttl_seconds=15) is not None
    clock.now += 16
    assert cache.get(key, ttl_seconds=15) is None  # stale is NOT fresh
    assert cache.stats.as_dict()["stale_hits"] == 1


def test_failed_or_empty_requests_never_poison_the_cache():
    cache = MarketDataCache(clock=FakeClock())
    key = candle_cache_key(instrument="ETH-USDT-SWAP", timeframe="1m", limit=60)
    assert cache.put(key, [], source="okx") is False
    assert cache.put(key, None, source="okx") is False
    assert cache.put(key, [], source="okx", quality=REQUEST_FAILED) is False
    assert cache.get(key, ttl_seconds=60) is None
    cache.record_failure(key, "provider 500")
    assert cache.get(key, ttl_seconds=60) is None
    assert cache.stats.as_dict()["rejected_failures"] >= 3


def test_cache_loader_failure_is_reported_not_cached():
    cache = MarketDataCache(clock=FakeClock())
    key = candle_cache_key(instrument="BTC-USDT-SWAP", timeframe="1m", limit=60)

    async def failing_loader():
        raise RuntimeError("okx down")

    payload, quality, hit = asyncio.run(
        cache.get_or_fetch(key, failing_loader, ttl_seconds=30, source="okx")
    )
    assert payload is None
    assert quality == REQUEST_FAILED
    assert hit is False
    assert cache.get(key, ttl_seconds=30) is None


def test_cache_identity_separates_instrument_timeframe_limit_and_as_of():
    cache = MarketDataCache(clock=FakeClock())
    base = candle_cache_key(instrument="BTC-USDT-SWAP", timeframe="1m", limit=120)
    other_symbol = candle_cache_key(instrument="ETH-USDT-SWAP", timeframe="1m", limit=120)
    other_tf = candle_cache_key(instrument="BTC-USDT-SWAP", timeframe="15m", limit=120)
    other_limit = candle_cache_key(instrument="BTC-USDT-SWAP", timeframe="1m", limit=60)
    bucket_a = candle_cache_key(
        instrument="BTC-USDT-SWAP", timeframe="1m", limit=60, as_of_bucket="1000"
    )
    bucket_b = candle_cache_key(
        instrument="BTC-USDT-SWAP", timeframe="1m", limit=60, as_of_bucket="2000"
    )
    for key in (base, other_symbol, other_tf, other_limit, bucket_a, bucket_b):
        assert cache.put(key, [["data", key.as_ref()]], source="okx") is True
    assert cache.get(base, ttl_seconds=30).payload[0][1] == base.as_ref()
    assert cache.get(other_symbol, ttl_seconds=30).payload[0][1] == other_symbol.as_ref()
    assert cache.get(bucket_a, ttl_seconds=30).payload[0][1] == bucket_a.as_ref()
    assert cache.get(bucket_b, ttl_seconds=30).payload[0][1] == bucket_b.as_ref()


def test_as_of_bucket_is_interval_aligned():
    as_of = datetime(2026, 1, 1, 12, 37, 45, tzinfo=UTC)
    assert as_of_bucket(as_of, 60) == str(
        int(datetime(2026, 1, 1, 12, 37, tzinfo=UTC).timestamp())
    )
    assert as_of_bucket(as_of, 900) == str(
        int(datetime(2026, 1, 1, 12, 30, tzinfo=UTC).timestamp())
    )
    assert closed_candle_ttl_seconds(60) == 15.0


def test_cache_entry_exposes_provenance():
    cache = MarketDataCache(clock=FakeClock())
    key = candle_cache_key(instrument="BTC-USDT-SWAP", timeframe="1m", limit=120)
    latest = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    cache.put(key, [["x"]], source="OKX /api/v5/market/candles", latest_data_at=latest)
    entry = cache.get(key, ttl_seconds=60)
    assert entry.source == "OKX /api/v5/market/candles"
    assert entry.latest_data_at == latest
    assert entry.closed_only is True
    assert entry.as_dict()["quality"] == "VALID"


# ------------------------------------------------------------------ tool catalog
def test_every_canonical_tool_has_name_version_and_description():
    registry = build_canonical_tool_registry(None)
    register_context_tools(registry, None)
    register_factor_runtime_tools(registry, None)
    register_market_history_tool(registry, None)

    catalog = registry.catalog()
    versions = registry.tool_versions()
    assert len(catalog) >= 21
    for name, description in catalog.items():
        assert name
        assert description, f"{name} has no description"
        assert versions[name], f"{name} has no explicit version"


def test_registry_rejects_duplicate_or_unversioned_tools():
    registry = build_canonical_tool_registry(None)

    async def tool(symbol, context):  # pragma: no cover - never called
        return None

    with pytest.raises(ValueError):
        registry.register("trend", tool, version="v1")  # duplicate
    with pytest.raises(ValueError):
        registry.register("brand_new", tool, version="")  # no explicit version
