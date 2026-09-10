"""P2: refreshed multi-position marks; never pair new freshness with old price."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from crypto_trader.domain.models import Account, Instrument, Position
from crypto_trader.ledger.service import LedgerService
from crypto_trader.portfolio.service import PortfolioService
from crypto_trader.valuation.service import ValuationService
from tests.conftest import make_paper_engine


def _instrument(symbol: str) -> Instrument:
    base = symbol.removesuffix("USDT")
    return Instrument(
        symbol=symbol,
        base_asset=base,
        quote_asset="USDT",
        instrument_type="LINEAR_PERP",
        contract_size="1",
        step_size="0.001",
    )


def _position(symbol: str, *, entry: str = "100") -> Position:
    return Position(
        symbol=symbol,
        base_asset=symbol.removesuffix("USDT"),
        quote_asset="USDT",
        quantity=Decimal("1"),
        avg_entry_price=Decimal(entry),
        instrument_type="LINEAR_PERP",
        contract_size=Decimal("1"),
        contract_multiplier=Decimal("1"),
    )


async def _seed_book(engine, symbol: str, mid: str, *, age_seconds: int = 0) -> None:
    await engine.market_data.ingest_snapshot(
        symbol,
        sequence=1,
        bids=[(Decimal(mid) - Decimal("0.1"), Decimal("10"))],
        asks=[(Decimal(mid) + Decimal("0.1"), Decimal("10"))],
    )
    if age_seconds:
        engine.market_data.books[symbol].updated_at = datetime.now(UTC) - timedelta(
            seconds=age_seconds
        )


async def test_refresh_then_read_new_price_not_old_map(database, monkeypatch):
    engine = make_paper_engine(database)
    engine._instruments = {
        "BTCUSDT": _instrument("BTCUSDT"),
        "ETHUSDT": _instrument("ETHUSDT"),
    }
    positions = {"BTCUSDT": _position("BTCUSDT"), "ETHUSDT": _position("ETHUSDT")}
    await _seed_book(engine, "BTCUSDT", "110")
    await _seed_book(engine, "ETHUSDT", "100", age_seconds=7200)

    refreshed: list[str] = []

    async def fake_refresh(symbol: str) -> bool:
        refreshed.append(symbol)
        await _seed_book(engine, symbol, "120")
        return True

    monkeypatch.setattr(engine, "_refresh_execution_market", fake_refresh)
    batch = await engine._build_valuation_candidate(
        account=Account(equity=Decimal("1000")), positions=positions
    )
    assert refreshed == ["ETHUSDT"]
    assert batch.quality == "HEALTHY"
    components = {row["instrument_id"]: row for row in batch.components}
    assert Decimal(components["ETHUSDT"]["mark_price"]) == Decimal("120")
    assert Decimal(components["BTCUSDT"]["mark_price"]) == Decimal("110")
    # 1000 + (110-100) + (120-100), never the stale 100 ETH mark.
    assert batch.raw_mtm_equity == Decimal("1030")


async def test_refresh_failure_makes_whole_valuation_incomplete(database, monkeypatch):
    engine = make_paper_engine(database)
    engine._instruments = {
        "BTCUSDT": _instrument("BTCUSDT"),
        "ETHUSDT": _instrument("ETHUSDT"),
    }
    positions = {"BTCUSDT": _position("BTCUSDT"), "ETHUSDT": _position("ETHUSDT")}
    await _seed_book(engine, "BTCUSDT", "110")
    await _seed_book(engine, "ETHUSDT", "100", age_seconds=7200)

    async def failed_refresh(_symbol: str) -> bool:
        return False

    monkeypatch.setattr(engine, "_refresh_execution_market", failed_refresh)
    batch = await engine._build_valuation_candidate(
        account=Account(equity=Decimal("1000")), positions=positions
    )
    assert batch.quality == "UNAVAILABLE"
    assert batch.raw_mtm_equity is None
    assert "ETHUSDT" in batch.stale_marks
    assert any(reason.startswith("MARK_REFRESH_FAILED:ETHUSDT") for reason in batch.reason_codes)
    assert not batch.usable_for_new_risk
    # No entry-price / zero / cross-symbol fallback was invented.
    assert {row["instrument_id"] for row in batch.components} == {"BTCUSDT"}


async def _build_with_validated_marks(
    database, *, timestamp: datetime, instrument_type: str = "LINEAR_PERP"
):
    portfolio = PortfolioService(database.session_factory)
    ledger = LedgerService(database.session_factory)
    service = ValuationService(portfolio=portfolio, ledger=ledger)
    positions = {"ETHUSDT": _position("ETHUSDT")}
    instrument = _instrument("ETHUSDT")
    instrument = instrument.model_copy(update={"instrument_type": instrument_type})
    return await service.build(
        account=Account(equity=Decimal("1000")),
        positions=positions,
        market_prices={"ETHUSDT": Decimal("110")},
        instruments={"ETHUSDT": instrument},
        is_fresh=lambda _symbol: True,
        require_mark_healthy=lambda _symbol: True,
        mark_timestamps={"ETHUSDT": timestamp},
        allowed_future_skew_seconds=0,
    )


async def test_future_mark_timestamp_invalidates_batch(database):
    batch = await _build_with_validated_marks(
        database, timestamp=datetime.now(UTC) + timedelta(minutes=5)
    )
    assert batch.quality == "UNAVAILABLE"
    assert batch.raw_mtm_equity is None
    assert "FUTURE_MARK_TIMESTAMP:ETHUSDT" in batch.reason_codes


async def test_instrument_product_mismatch_invalidates_batch(database):
    batch = await _build_with_validated_marks(
        database,
        timestamp=datetime.now(UTC),
        instrument_type="SPOT",
    )
    assert batch.quality == "UNAVAILABLE"
    assert "INSTRUMENT_PRODUCT_MISMATCH:ETHUSDT" in batch.reason_codes


async def test_missing_instrument_metadata_invalidates_batch(database):
    portfolio = PortfolioService(database.session_factory)
    ledger = LedgerService(database.session_factory)
    service = ValuationService(portfolio=portfolio, ledger=ledger)
    batch = await service.build(
        account=Account(equity=Decimal("1000")),
        positions={"ETHUSDT": _position("ETHUSDT")},
        market_prices={"ETHUSDT": Decimal("110")},
        instruments={},
        is_fresh=lambda _symbol: True,
        mark_timestamps={"ETHUSDT": datetime.now(UTC)},
    )
    assert batch.quality == "UNAVAILABLE"
    assert "INSTRUMENT_METADATA_UNAVAILABLE:ETHUSDT" in batch.reason_codes
