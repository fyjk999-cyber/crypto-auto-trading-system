"""Restart durability for fairness clocks, rotation cursor and OI samples."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from crypto_trader.market_data.opportunity.coverage import CoverageLedger
from crypto_trader.market_data.opportunity.oi import OiSample, OiTimeSeries
from crypto_trader.market_data.opportunity.scanner import RotationScheduler
from crypto_trader.market_data.opportunity.service import OpportunityScannerService
from crypto_trader.market_data.opportunity.state_store import (
    SCANNER_STATE_KEY,
    ScannerStateStore,
)


def test_scanner_state_round_trips_through_settings_store(database):
    store = ScannerStateStore(database.session_factory)
    ledger = CoverageLedger()
    rotation = RotationScheduler()
    oi = OiTimeSeries()
    now = datetime.now(UTC)
    ledger.mark_observed("BTCUSDT", now)
    ledger.mark_analysis_attempt("ETHUSDT", now, success=True)
    ledger.mark_llm_research("SOLUSDT", now)
    oi.record(OiSample("BTCUSDT", 1000.0, now - timedelta(minutes=15)))
    oi.record(OiSample("BTCUSDT", 1100.0, now))
    rotation.sync(["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    rotation.next_batch(exclude=set(), size=2, ledger=ledger, now=now)

    service = OpportunityScannerService(
        universe=object(),
        okx_client=object(),
        board=None,
        coverage=ledger,
        oi_series=oi,
        state_store=store,
    )
    service._rotation = rotation
    service.cycles_completed = 7
    service.scan_overrun_count = 2
    assert asyncio.run(store.save(service.export_state())) is True

    # simulate a restart: brand-new objects, restore from the durable store
    fresh_ledger = CoverageLedger()
    fresh_rotation = RotationScheduler()
    fresh_oi = OiTimeSeries()
    restored_service = OpportunityScannerService(
        universe=object(),
        okx_client=object(),
        board=None,
        coverage=fresh_ledger,
        oi_series=fresh_oi,
        state_store=store,
    )
    restored_service._rotation = fresh_rotation
    restored = asyncio.run(restored_service.restore_state())

    assert restored >= 3
    assert restored_service.cycles_completed == 7
    assert restored_service.scan_overrun_count == 2
    assert fresh_ledger.as_dict("ETHUSDT")["last_successful_analysis_at"] is not None
    assert fresh_ledger.as_dict("SOLUSDT")["last_llm_research_at"] is not None
    assert fresh_oi.sample_count("BTCUSDT") == 2
    # fairness survives: the freshly analysed symbol is not the next pick
    assert fresh_rotation.next_batch(exclude=set(), size=1, ledger=fresh_ledger, now=now)


def test_missing_or_corrupt_scanner_state_is_ignored_not_fatal(database):
    from crypto_trader.persistence.models import RuntimeSettingORM

    async def corrupt():
        async with database.session_factory() as session:
            session.add(
                RuntimeSettingORM(
                    key=SCANNER_STATE_KEY,
                    value="{not json",
                    updated_at=datetime.now(UTC),
                    updated_by="test",
                )
            )
            await session.commit()

    asyncio.run(corrupt())
    store = ScannerStateStore(database.session_factory)
    assert asyncio.run(store.load()) is None
    assert store.last_error == "MALFORMED_STATE"

    service = OpportunityScannerService(
        universe=object(),
        okx_client=object(),
        board=None,
        state_store=store,
    )
    assert asyncio.run(service.restore_state()) == 0
    assert service.cycles_completed == 0
