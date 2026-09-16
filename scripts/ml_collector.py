# ruff: noqa: E402, ASYNC240
# ML collector: PAPER learning only; no LLM, no orders.
import asyncio
import json
import os
import signal
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from sqlalchemy import select

from crypto_trader.exchange.okx import OKXAdapter
from crypto_trader.market_data.okx_public_feed import OKXPublicMarketFeed
from crypto_trader.market_data.opportunity.board import OpportunityBoard
from crypto_trader.market_data.opportunity.eligibility import EligibilityFilter
from crypto_trader.market_data.opportunity.factors import DEFAULT_FACTORS
from crypto_trader.market_data.opportunity.scanner import FactorScanner
from crypto_trader.market_data.opportunity.service import OpportunityScannerService
from crypto_trader.market_data.opportunity.snapshots import ScanSnapshotCollector
from crypto_trader.market_data.opportunity.universe import OkxUniverseManager
from crypto_trader.persistence import Database
from crypto_trader.persistence.models import ScanSnapshotLabelORM, ScanSnapshotORM

H = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400}
STOP = False


def _sig(*_):
    global STOP
    STOP = True


async def prices(c):
    rows = await c.get_tickers("SWAP")
    return {str(r["instId"]).split("-")[0] + "USDT": float(r["last"]) for r in rows}


async def label(db, px, now):
    n = 0
    async with db.session_factory() as s:
        q = select(
            ScanSnapshotLabelORM.snapshot_id,
            ScanSnapshotLabelORM.horizon,
            ScanSnapshotLabelORM.label_version,
        )
        have = {(a, b, c) for a, b, c in (await s.execute(q)).all()}
        pend = select(ScanSnapshotORM).where(ScanSnapshotORM.outcome_status == "PENDING")
        snaps = (await s.execute(pend)).scalars().all()
        for x in snaps:
            entry = (x.features_json or {}).get("price")
            price = px.get(x.symbol)
            if not entry or not price:
                continue
            for h, sec in H.items():
                k = (x.snapshot_id, h, "label-v1")
                m = x.captured_at.replace(tzinfo=UTC) + timedelta(seconds=sec)
                if k in have or m > now:
                    continue
                g = (price - float(entry)) / float(entry) * 10000
                c = 22.0
                ln, sn = g - c, -g - c
                s.add(
                    ScanSnapshotLabelORM(
                        snapshot_id=x.snapshot_id,
                        symbol=x.symbol,
                        snapshot_ts=x.captured_at,
                        horizon=h,
                        feature_version="scan-features-v1",
                        label_version="label-v1",
                        future_high=price,
                        future_low=price,
                        long_gross_bps=g,
                        short_gross_bps=-g,
                        all_in_cost_bps=c,
                        long_net_bps=ln,
                        short_net_bps=sn,
                        long_net_edge_bps=ln,
                        short_net_edge_bps=sn,
                        long_label="PROFITABLE" if ln > 10 else "NOT_PROFITABLE",
                        short_label="PROFITABLE" if sn > 10 else "NOT_PROFITABLE",
                        matured_at=m,
                    )
                )
                have.add(k)
                n += 1
            if all((x.snapshot_id, h, "label-v1") in have for h in H):
                x.outcome_status = "LABELED"
        await s.commit()
    return n


async def main(db, status):
    d = Database(f"sqlite+aiosqlite:///{db}")
    await d.init_schema()
    c = OKXAdapter()
    feed = OKXPublicMarketFeed(client=c)

    async def prefetch(symbols):
        await asyncio.gather(*(feed.refresh(sym) for sym in symbols[:24]), return_exceptions=True)

    v = OpportunityScannerService(
        universe=OkxUniverseManager(c),
        okx_client=c,
        board=OpportunityBoard(),
        scanner=FactorScanner(factors=DEFAULT_FACTORS),
        eligibility=EligibilityFilter(),
        scan_interval_seconds=0,
        active_set_size=8,
        rotation_size=2,
        state_provider=lambda symbol: feed.states.get(symbol),
        state_prefetch=prefetch,
        snapshot_collector=ScanSnapshotCollector(d.session_factory),
        control_sample_size=20,
    )
    st = {
        "pid": os.getpid(),
        "started_at": datetime.now(UTC).isoformat(),
        "cycles": 0,
        "snapshots": 0,
        "candidates": 0,
        "controls": 0,
        "labels": 0,
        "errors": 0,
    }
    while not STOP:
        st["cycles"] += 1
        try:
            await v.scan_once()
            cs = v.collection_stats or {}
            st["snapshots"] += int(cs.get("persisted", 0))
            st["candidates"] += int(cs.get("candidates", 0))
            st["controls"] += int(cs.get("controls", 0))
            st["labels"] += await label(d, await prices(c), datetime.now(UTC))
        except Exception as e:
            st["errors"] += 1
            st["last_error"] = f"{type(e).__name__}: {e}"[:200]
        Path(status).write_text(json.dumps(st))
        await asyncio.sleep(90)
    await feed.close()
    await d.close()


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _sig)
    signal.signal(signal.SIGINT, _sig)
    db = sys.argv[1] if len(sys.argv) > 1 else "data/ml/scan_dataset.db"
    status = sys.argv[2] if len(sys.argv) > 2 else "data/ml/collector_heartbeat.json"
    asyncio.run(main(db, status))
