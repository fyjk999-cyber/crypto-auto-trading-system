import os
from datetime import UTC, datetime

import pytest

from crypto_trader.evolution.persistence_backends import (
    HierarchicalReviewStore,
    ReviewJobStore,
    SqlEvidenceBackend,
)
from crypto_trader.persistence.database import Database

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").startswith("postgresql"),
    reason="PostgreSQL qualification requires DATABASE_URL",
)


def make_evidence(decision_id="d_pg"):
    now = datetime.now(UTC).isoformat()
    return {
        "decision_id": decision_id, "timestamp_utc": now, "symbol": "BTCUSDT",
        "timeframe": "15m", "strategy_id": "llm", "strategy_version": "1",
        "model_version": "1", "prompt_version": "1", "factor_snapshot_id": "fs_pg",
        "factor_set_version": "factorset-v1", "factor_profile": "FULL",
        "market_data_reference": "md_pg", "analysis_evidence": {},
        "decision": {"action": "LONG"}, "risk_decision": {"decision": "APPROVE"},
        "execution_intent_reference": "", "created_at_utc": now,
    }


async def test_postgres_persistence_and_restart_like_recovery():
    url = os.environ["DATABASE_URL"]
    db1 = Database(url)
    backend = SqlEvidenceBackend(db1.session_factory)
    evidence = make_evidence("d_pg_restart")
    await backend.store_decision(evidence)
    await db1.close()

    db2 = Database(url)
    backend2 = SqlEvidenceBackend(db2.session_factory)
    loaded = await backend2.get_decision("d_pg_restart")
    assert loaded is not None
    assert loaded["decision_id"] == "d_pg_restart"
    assert loaded["factor_snapshot_id"] == "fs_pg"
    assert loaded["factor_set_version"] == "factorset-v1"
    # idempotent duplicate write
    await backend2.store_decision(evidence)
    assert (await backend2.get_decision("d_pg_restart"))["decision_id"] == "d_pg_restart"
    await db2.close()


async def test_postgres_review_job_and_hierarchy_persistence():
    url = os.environ["DATABASE_URL"]
    db = Database(url)
    jobs = ReviewJobStore(db.session_factory)
    key = "review:daily:2026-08-25"
    await jobs.put(key, "r1", "DAILY", "2026-08-25", "RUNNING")
    await jobs.put(key, "r1", "DAILY", "2026-08-25", "DONE")
    assert (await jobs.get(key))["status"] == "DONE"

    store = HierarchicalReviewStore(db.session_factory)
    weekly = {
        "review_id": "w_pg", "period_id": "2026-W35",
        "starts_at": "2026-08-24T00:00:00+00:00",
        "ends_at": "2026-08-30T23:59:59.999999+00:00",
        "created_at_utc": datetime.now(UTC).isoformat(), "status": "COMPLETED",
        "daily_review_ids": ["d_pg"], "confirmed_lessons": [],
        "invalidated_lessons": [], "candidate_lessons": [],
        "persistent_patterns": [], "research_questions": [],
        "data_quality": "OK", "warnings": [],
    }
    await store.store_review("WEEKLY", weekly)
    loaded = await store.get_review("WEEKLY", "w_pg")
    assert loaded["period_id"] == "2026-W35"
    await db.close()


async def test_postgres_canonical_bootstrap_uses_postgres_url():
    from crypto_trader.config import Settings
    from crypto_trader.runtime.bootstrap import build_system

    url = os.environ["DATABASE_URL"]
    settings = Settings(
        _env_file=None, app_env="test", trading_mode="PAPER",
        live_trading_enabled=False, database_url=url,
        auto_start_runtime=False, paper_mode="PAPER_SYNTHETIC",
        paper_initial_equity="100000", engine_tick_seconds=3600,
        reconciliation_interval_seconds=3600, run_lease_renew_interval_seconds=3600)
    bundle = await build_system(settings)
    assert bundle.database.url == url
    assert bundle.factor_gateway is not None
    assert bundle.ai_bridge is not None
    await bundle.database.close()
