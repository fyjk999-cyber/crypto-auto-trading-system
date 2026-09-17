"""Growth publication fence, revision binding and bounded retrieval contracts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from crypto_trader.learning.retrieval import (
    GrowthPublishInputMissing,
    GrowthRetriever,
    proposition_identity,
    record_version,
)
from crypto_trader.persistence.models import GrowthMemoryVersionORM

T = datetime(2026, 9, 16, 0, 0, tzinfo=UTC)


async def _version(session_factory, *, payload=None, available_at=None, object_id="p1"):
    return await record_version(
        session_factory,
        object_type="REGIME_PATTERN",
        object_id=object_id,
        available_at=available_at or T,
        sample_count=60,
        sample_tier="CANDIDATE",
        memory_speed="PATTERN",
        quality=0.6,
        post_cost_expectancy_bps=5.0,
        contradictions=0,
        payload_json=payload or {"symbol": "BTCUSDT", "regime": "TREND_UP"},
        source_refs_json={"episodes": ["e1"]},
    )


async def test_record_version_binds_proposition_input_and_known_at(database):
    version = await _version(database.session_factory)
    async with database.session_factory() as session:
        row = (
            await session.execute(
                select(GrowthMemoryVersionORM).where(GrowthMemoryVersionORM.version == version)
            )
        ).scalar_one()
    meta = dict(row.payload_json.get("_meta") or {})
    assert version == 1
    assert meta["revision"] == 1
    assert meta["proposition_id"] == proposition_identity("REGIME_PATTERN", "p1")
    assert len(meta["input_hash"]) == 64
    assert meta["known_at"].startswith(row.available_at.isoformat())


async def test_duplicate_version_fence_is_atomic(database):
    await _version(database.session_factory)
    async with database.session_factory() as session:
        session.add(
            GrowthMemoryVersionORM(
                object_type="REGIME_PATTERN",
                object_id="p1",
                version=1,
                available_at=T,
                payload_json={"symbol": "BTCUSDT"},
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_latest_visible_version_is_selected_per_proposition(database):
    await _version(database.session_factory, payload={"symbol": "BTCUSDT"})
    await _version(
        database.session_factory,
        payload={"symbol": "BTCUSDT", "promoted": True},
        available_at=T + timedelta(hours=1),
    )
    retriever = GrowthRetriever(database.session_factory)
    early = await retriever.search(symbol="BTCUSDT", as_of_timestamp=T)
    late = await retriever.search(symbol="BTCUSDT", as_of_timestamp=T + timedelta(hours=2))
    assert [item["version"] for item in early["results"]] == [1]
    assert [item["version"] for item in late["results"]] == [2]


async def test_unscoped_truth_fails_closed_for_symbol_queries(database):
    await _version(database.session_factory, payload={"global": True})
    retriever = GrowthRetriever(database.session_factory)
    closed = await retriever.search(symbol="BTCUSDT", as_of_timestamp=T)
    assert closed["result_count"] == 0
    assert retriever.metrics["scope_fail_closed"] >= 1


async def test_serialized_evidence_budget_is_hard_capped(database):
    big_refs = {"documents": ["ref-" + str(index) * 64 for index in range(80)]}
    await _version(
        database.session_factory,
        payload={"symbol": "BTCUSDT", "regime": "TREND_UP"},
        object_id="p1",
    )
    async with database.session_factory() as session:
        row = (
            await session.execute(
                select(GrowthMemoryVersionORM).where(GrowthMemoryVersionORM.object_id == "p1")
            )
        ).scalar_one()
        row.source_refs_json = big_refs
        await session.commit()
    retriever = GrowthRetriever(database.session_factory)
    response = await retriever.search(
        symbol="BTCUSDT", as_of_timestamp=T, max_serialized_bytes=1024
    )
    assert response["budget"]["omitted_count"] == 1
    assert response["result_count"] == 0


async def test_no_publish_input_is_explicit(database):
    with pytest.raises(GrowthPublishInputMissing):
        await record_version(
            database.session_factory, object_type="REGIME_PATTERN", object_id="p1"
        )


async def test_expired_and_revoked_truth_is_not_visible(database):
    await record_version(
        database.session_factory,
        object_type="REGIME_PATTERN",
        object_id="expired",
        available_at=T - timedelta(hours=2),
        expires_at=T - timedelta(hours=1),
        sample_count=60,
        sample_tier="CANDIDATE",
        payload_json={"symbol": "BTCUSDT"},
    )
    await record_version(
        database.session_factory,
        object_type="REGIME_PATTERN",
        object_id="revoked",
        available_at=T - timedelta(hours=2),
        revoked_at=T - timedelta(minutes=30),
        sample_count=60,
        sample_tier="CANDIDATE",
        payload_json={"symbol": "BTCUSDT"},
    )
    retriever = GrowthRetriever(database.session_factory)
    response = await retriever.search(symbol="BTCUSDT", as_of_timestamp=T)
    assert response["result_count"] == 0
    assert retriever.metrics["expired_filtered"] >= 1
    assert retriever.metrics["revoked_filtered"] >= 1


async def test_future_revocation_is_not_visible_before_known_at(database):
    await record_version(
        database.session_factory,
        object_type="REGIME_PATTERN",
        object_id="future-revoke",
        available_at=T,
        revoked_at=T + timedelta(hours=1),
        sample_count=60,
        sample_tier="CANDIDATE",
        payload_json={"symbol": "BTCUSDT"},
    )
    retriever = GrowthRetriever(database.session_factory)
    response = await retriever.search(symbol="BTCUSDT", as_of_timestamp=T)
    assert response["result_count"] == 1
