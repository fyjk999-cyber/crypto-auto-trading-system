# ruff: noqa: E402, ASYNC240
# ML collector: PAPER learning only; no LLM, no orders.
import asyncio
import json
import os
import signal
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from crypto_trader.exchange.okx import OKXAdapter
from crypto_trader.factors.expert.engine import ExpertEvidenceEngine
from crypto_trader.market_data.okx_public_feed import OKXPublicMarketFeed
from crypto_trader.market_data.opportunity.board import OpportunityBoard
from crypto_trader.market_data.opportunity.eligibility import EligibilityFilter
from crypto_trader.market_data.opportunity.factors import DEFAULT_FACTORS
from crypto_trader.market_data.opportunity.scanner import FactorScanner
from crypto_trader.market_data.opportunity.service import OpportunityScannerService
from crypto_trader.market_data.opportunity.snapshots import ScanSnapshotCollector
from crypto_trader.market_data.opportunity.universe import OkxUniverseManager
from crypto_trader.ml_artifacts import ArtifactResolver
from crypto_trader.ml_labels import (
    HORIZON_SECONDS,
    STATUS_IMMATURE,
    STATUS_INCONCLUSIVE_ALIGNMENT,
    STATUS_INCONCLUSIVE_DATA_GAP,
    STATUS_MATURE_VALID,
    STATUS_TRANSIENT_SOURCE_ERROR,
    LabelV2Maturer,
    OkxHistoricalCandleProvider,
)
from crypto_trader.ml_registry import ModelRegistry
from crypto_trader.persistence import Database
from crypto_trader.persistence.models import ScanSnapshotLabelORM

H = HORIZON_SECONDS
STOP = False


def _sig(*_):
    global STOP
    STOP = True


LABEL_BATCH_LIMIT = 30
LABEL_TIMEOUT_SECONDS = 120.0


async def label(db, provider, now, *, limit: int = LABEL_BATCH_LIMIT, observer=None):
    """Exact factual label-v2 maturity; label-v1 is archival only.

    Bounded batch keeps the collector loop live when the external history
    provider is slow or unavailable. Persistence is committed per snapshot so
    completed factual work survives a later timeout/cancellation.
    """
    maturer = LabelV2Maturer()
    return await maturer.mature_pending(
        db.session_factory, provider, now=now, limit=limit, on_result=observer
    )


async def label_v2_counts(db) -> dict[str, int]:
    """Current DB truth for the label-v2 table, by maturation status."""
    async with db.session_factory() as session:
        rows = (
            await session.execute(
                select(
                    ScanSnapshotLabelORM.maturation_status,
                    func.count(ScanSnapshotLabelORM.id),
                )
                .where(ScanSnapshotLabelORM.label_version == "label-v2")
                .group_by(ScanSnapshotLabelORM.maturation_status)
            )
        ).all()
    return {str(status): int(count) for status, count in rows}


async def main(db, status):
    d = Database(f"sqlite+aiosqlite:///{db}")
    await d.init_schema()
    c = OKXAdapter()
    feed = OKXPublicMarketFeed(client=c)
    label_provider = OkxHistoricalCandleProvider(c)

    async def prefetch(symbols):
        await asyncio.gather(*(feed.refresh(sym) for sym in symbols[:24]), return_exceptions=True)

    async def expert_timeframes(symbol):
        bars = ("4h", "1h", "15m", "5m", "1m")
        results = await asyncio.gather(
            *(
                feed.get_closed_candles(symbol, bar=bar, limit=300)
                for bar in bars
            ),
            return_exceptions=True,
        )
        return {
            bar: ([] if isinstance(result, BaseException) else result)
            for bar, result in zip(bars, results, strict=False)
        }

    model_runtime = ArtifactResolver(ModelRegistry(REPO / "data" / "ml" / "registry.json"))
    expert_engine = ExpertEvidenceEngine(
        timeframe_provider=expert_timeframes,
        state_provider=lambda symbol: feed.states.get(symbol),
        model_runtime=model_runtime,
    )

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
        expert_engine=expert_engine,
    )
    st = {
        "pid": os.getpid(),
        "running_sha": os.environ.get("RUNNING_SHA", ""),
        "started_at": datetime.now(UTC).isoformat(),
        "cycles": 0,
        "snapshots": 0,
        "candidates": 0,
        "controls": 0,
        "labels": 0,
        "errors": 0,
        "label_v2": {},
        "last_label_symbol": None,
        "last_label_horizon": None,
        "last_label_status": None,
        "last_successful_label_at": None,
        "label_v2_total": 0,
        "label_v2_mature_valid": 0,
        "label_v2_immature": 0,
        "label_v2_inconclusive": 0,
        "label_v2_transient": 0,
        "history_requests": 0,
        "history_errors": 0,
        "history_latency_seconds": 0.0,
        "history_page_requests": 0,
        "history_cache_hits": 0,
        "label_batches_started": 0,
        "label_batches_completed": 0,
        "label_batch_timeouts": 0,
    }

    def on_label_result(meta):
        st["last_label_symbol"] = meta.get("symbol")
        st["last_label_horizon"] = meta.get("horizon")
        st["last_label_status"] = meta.get("status")
        if meta.get("status") == STATUS_MATURE_VALID:
            st["last_successful_label_at"] = datetime.now(UTC).isoformat()

    while not STOP:
        st["cycles"] += 1
        try:
            await v.scan_once()
            cs = v.collection_stats or {}
            st["snapshots"] += int(cs.get("persisted", 0))
            st["candidates"] += int(cs.get("candidates", 0))
            st["controls"] += int(cs.get("controls", 0))
            # Liveness first: scanner facts are durable even if the external
            # history provider is slow or unavailable.
            Path(status).write_text(json.dumps(st))

            st["label_batches_started"] += 1
            try:
                statuses = await asyncio.wait_for(
                    label(d, label_provider, datetime.now(UTC), observer=on_label_result),
                    timeout=LABEL_TIMEOUT_SECONDS,
                )
            except TimeoutError:
                statuses = {}
                st["errors"] += 1
                st["label_batch_timeouts"] += 1
                st["last_error"] = "LABEL_MATURATION_TIMEOUT"
            else:
                st["label_batches_completed"] += 1

            for status_key, status_count in statuses.items():
                st["label_v2"][status_key] = st["label_v2"].get(status_key, 0) + int(status_count)
            st["labels"] += int(statuses.get(STATUS_MATURE_VALID, 0))

            summary = await label_v2_counts(d)
            st["label_v2_total"] = sum(summary.values())
            st["label_v2_mature_valid"] = summary.get(STATUS_MATURE_VALID, 0)
            st["label_v2_immature"] = summary.get(STATUS_IMMATURE, 0)
            st["label_v2_inconclusive"] = summary.get(
                STATUS_INCONCLUSIVE_DATA_GAP, 0
            ) + summary.get(STATUS_INCONCLUSIVE_ALIGNMENT, 0)
            st["label_v2_transient"] = summary.get(STATUS_TRANSIENT_SOURCE_ERROR, 0)

            provider_stats = label_provider.stats()
            st["history_requests"] = provider_stats["history_requests"]
            st["history_errors"] = provider_stats["history_errors"]
            st["history_latency_seconds"] = provider_stats["history_latency_seconds"]
            st["history_page_requests"] = provider_stats["history_page_requests"]
            st["history_cache_hits"] = provider_stats["history_cache_hits"]
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
