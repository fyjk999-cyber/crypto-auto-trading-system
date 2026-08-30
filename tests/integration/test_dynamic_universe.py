"""DynamicMarketUniverse tests: batch-first Layer-1, no cross-symbol fallback."""

from crypto_trader.market_data.universe import DynamicMarketUniverse, MarketSnapshotBatch
from crypto_trader.market_registry.registry import InstrumentRecord, persist_registry_sync


def _record(inst_id, inst_type, state="live", quote="USDT"):
    base = inst_id.split("-")[0]
    return InstrumentRecord(
        inst_id=inst_id, inst_type=inst_type, uly=None, inst_family=None,
        base_ccy=base, quote_ccy=quote, settle_ccy="USDT" if inst_type != "SPOT" else None,
        state=state, tick_sz="0.1", lot_sz="0.1", min_sz="0.1",
        ct_val=None, ct_val_ccy=None, ct_type=None, lever=None, exp_time=None, list_time=None)


class FakeDataClient:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    async def get_tickers(self, inst_type):
        self.calls.append(inst_type)
        return self.rows


def test_observable_universe_reads_registry(tmp_path):
    db = str(tmp_path / "market.db")
    records = [_record("BTC-USDT", "SPOT"), _record("ETH-USDT", "SPOT"),
               _record("SOL-USDT", "SPOT", state="DELISTED")]
    persist_registry_sync(db, records)
    universe = DynamicMarketUniverse(db)
    obs = universe.observable_universe()
    assert {r["inst_id"] for r in obs} == {"BTC-USDT", "ETH-USDT"}
    assert "SOL-USDT" not in {r["inst_id"] for r in obs}


async def test_layer1_batch_single_request_and_not_available(tmp_path):
    import sqlite3 as _sqlite3

    db_path = str(tmp_path / "market.db")
    conn = _sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS okx_instruments ("
        "inst_id VARCHAR(64) PRIMARY KEY, inst_type VARCHAR(16), "
        "state VARCHAR(16), quote_ccy VARCHAR(32))"
    )
    conn.execute("INSERT INTO okx_instruments VALUES ('BTC-USDT','SPOT','live','USDT')")
    conn.commit()
    conn.close()
    fake = FakeDataClient([{"instId": "BTC-USDT", "last": "100", "bidPx": "99",
                            "askPx": "101", "bidSz": "1", "askSz": "2",
                            "high24h": "110", "low24h": "90", "vol24h": "50",
                            "volCcy24h": "5000", "ts": "1700000000000"}])
    universe = DynamicMarketUniverse(db_path, data_client=fake)
    batch = await universe.layer1_batch("SPOT")
    assert isinstance(batch, MarketSnapshotBatch)
    assert len(fake.calls) == 1  # batch-first, never N calls
    fact = batch.facts[0]
    assert fact.inst_id == "BTC-USDT"
    assert fact.spread == "2"
    assert fact.freshness == "LIVE"
