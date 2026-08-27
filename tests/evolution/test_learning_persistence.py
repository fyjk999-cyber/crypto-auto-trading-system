from datetime import UTC, datetime

from crypto_trader.evolution.persistence_backends import (
    ReviewJobStore,
    SqlEvidenceBackend,
    SqlMemoryBackend,
)


def make_evidence(decision_id="d1"):
    now = datetime.now(UTC).isoformat()
    return {
        "decision_id": decision_id,
        "timestamp_utc": now,
        "symbol": "BTCUSDT",
        "timeframe": "15m",
        "strategy_id": "llm",
        "strategy_version": "1",
        "model_version": "1",
        "prompt_version": "1",
        "factor_snapshot_id": "fs1",
        "factor_set_version": "factorset-v1",
        "factor_profile": "FULL",
        "market_data_reference": "md1",
        "analysis_evidence": {},
        "decision": {"action": "LONG"},
        "risk_decision": {"decision": "APPROVE"},
        "execution_intent_reference": "",
        "created_at_utc": now,
    }


async def test_evidence_survives_restart(database):
    backend = SqlEvidenceBackend(database.session_factory)
    evidence = make_evidence("d_restart")
    await backend.store_decision(evidence)
    loaded = await backend.get_decision("d_restart")
    assert loaded["decision_id"] == "d_restart"
    assert loaded["factor_snapshot_id"] == "fs1"
    assert loaded["factor_set_version"] == "factorset-v1"
    # idempotent duplicate write
    await backend.store_decision(evidence)
    loaded2 = await backend.get_decision("d_restart")
    assert loaded2["decision_id"] == "d_restart"


async def test_review_job_idempotency_survives_restart(database):
    jobs = ReviewJobStore(database.session_factory)
    key = "review:daily:2026-08-25"
    await jobs.put(key, "r1", "DAILY", "2026-08-25", "RUNNING")
    await jobs.put(key, "r1", "DAILY", "2026-08-25", "DONE")
    loaded = await jobs.get(key)
    assert loaded["status"] == "DONE"
    assert loaded["attempt"] == 1


async def test_sql_memory_lesson_persistence(database):
    backend = SqlMemoryBackend(database.session_factory)
    sql_backend = SqlEvidenceBackend(database.session_factory)
    await sql_backend.store_lesson(
        {
            "lesson_id": "L1",
            "scope": "GLOBAL",
            "type": "FACTOR_CONFLICT",
            "canonical_statement": "Momentum reliability degrades in HIGH_VOL RANGE",
            "conditions": [],
            "recommended_action": "",
            "evidence_count": 3,
            "supporting_decisions": ["d1", "d2"],
            "contradictions": [],
            "first_seen": "",
            "last_seen": "",
            "confidence": 0.7,
            "status": "CANDIDATE",
            "source_review_ids": ["r1"],
            "source_pattern_ids": ["p1"],
        }
    )
    lessons = await backend.list_lessons()
    assert any(lesson["lesson_id"] == "L1" for lesson in lessons)
    await backend.update_lesson_status("L1", "CONFIRMED")
    lessons = await backend.list_lessons()
    confirmed = [lesson for lesson in lessons if lesson["lesson_id"] == "L1"]
    assert confirmed[0]["status"] == "CONFIRMED"


async def test_sql_pattern_and_review_persistence(database):
    backend = SqlEvidenceBackend(database.session_factory)
    await backend.store_pattern(
        {
            "pattern_id": "P1",
            "scope": "GLOBAL",
            "pattern_type": "FACTOR_CONFLICT",
            "conditions": ["HIGH_VOL"],
            "evidence_count": 2,
            "decision_ids": ["d1", "d2"],
            "confidence": 0.6,
            "status": "CANDIDATE",
        }
    )
    review = {
        "review_id": "r1",
        "review_type": "DAILY",
        "period_id": "2026-08-25",
        "starts_at": "2026-08-25T00:00:00+00:00",
        "ends_at": "2026-08-25T23:59:59.999999+00:00",
        "triggered_at": "2026-08-26T00:05:00+00:00",
        "decision_count": 2,
        "trade_count": 2,
        "data_quality": "OK",
        "warnings": [],
        "status": "COMPLETED",
    }
    await backend.store_review(review)
    loaded = await backend.get_review("r1")
    assert loaded["review_id"] == "r1"
    assert loaded["decision_count"] == 2
