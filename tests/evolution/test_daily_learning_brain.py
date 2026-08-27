from datetime import UTC, datetime

from crypto_trader.decision_replay.evidence import DecisionEvidence
from crypto_trader.decision_replay.store import EvidenceStore
from crypto_trader.evolution.daily.error_mining import classify_decision_quality, mine_error
from crypto_trader.evolution.daily.lesson import LessonEngine
from crypto_trader.evolution.daily.pattern import extract_patterns
from crypto_trader.evolution.daily.pipeline import DailyReviewPipeline
from crypto_trader.evolution.daily.replay import HistoricalReplayEngine


def make_evidence(decision_id="d1", snapshot_id="fs1"):
    now = datetime.now(UTC).isoformat()
    return DecisionEvidence(
        decision_id=decision_id,
        timestamp_utc=now,
        symbol="BTCUSDT",
        timeframe="15m",
        strategy_id="llm",
        strategy_version="1",
        model_version="1",
        prompt_version="1",
        factor_snapshot_id=snapshot_id,
        factor_set_version="factorset-v1",
        factor_profile="FULL",
        market_data_reference="md1",
        analysis_evidence={},
        decision={"action": "LONG"},
        risk_decision={"decision": "APPROVE"},
    )


def test_decision_quality_separated_from_outcome():
    assert classify_decision_quality(decision_quality="GOOD", outcome_quality="LOSS") == "GOOD_LOSS"
    assert classify_decision_quality(decision_quality="BAD", outcome_quality="WIN") == "BAD_WIN"


def test_error_mining_good_decision_loss_not_automatic_error():
    event = mine_error(decision_quality="GOOD", outcome_quality="BAD")
    assert event is None


def test_error_mining_bad_decision_win_not_system_error():
    event = mine_error(decision_quality="BAD", outcome_quality="GOOD")
    assert event is not None
    assert event.category == "BAD_DECISION_GOOD_OUTCOME"
    assert event.avoidable is False


def test_error_mining_rule_violation_despite_profit():
    event = mine_error(decision_quality="GOOD", outcome_quality="GOOD", rule_violation=True)
    assert event is not None
    assert event.category == "RULE_VIOLATION"
    assert event.avoidable is True


def test_pattern_extraction_requires_repeat():
    from crypto_trader.evolution.daily.error_mining import ErrorEvent

    patterns = extract_patterns([ErrorEvent("d1", "FACTOR_CONFLICT", True)])
    assert patterns == []
    patterns = extract_patterns(
        [
            ErrorEvent("d1", "FACTOR_CONFLICT", True),
            ErrorEvent("d2", "FACTOR_CONFLICT", True),
        ]
    )
    assert len(patterns) == 1
    assert patterns[0].status == "CANDIDATE"


def test_lesson_engine_candidate_only_and_deduplicate():
    from crypto_trader.evolution.daily.pattern import PatternCandidate

    engine = LessonEngine(memory_gateway=type("M", (), {"lessons": []})())
    pattern = PatternCandidate(
        pattern_id="p1",
        scope="GLOBAL",
        pattern_type="FACTOR_CONFLICT",
        conditions=[],
        evidence_count=2,
        decision_ids=["d1", "d2"],
        confidence=0.7,
    )
    lesson = engine.derive_from_pattern(pattern)
    assert lesson.status == "CANDIDATE"
    assert engine.deduplicate(lesson) is not None
    engine.memory_gateway.lessons.append(lesson.to_dict())
    assert engine.deduplicate(lesson) is None


def test_daily_pipeline_idempotent():
    pipeline = DailyReviewPipeline()
    decisions = [
        {
            "decision_id": "d1",
            "trade": True,
            "decision_quality": "BAD",
            "outcome_quality": "BAD",
            "factor_conflict": True,
        },
        {"decision_id": "d2", "trade": True, "decision_quality": "GOOD", "outcome_quality": "GOOD"},
        {
            "decision_id": "d3",
            "trade": True,
            "decision_quality": "BAD",
            "outcome_quality": "BAD",
            "factor_conflict": True,
        },
    ]
    result1 = pipeline.run(
        review_id="r1",
        period_id="2026-08-25",
        starts_at="2026-08-25T00:00:00+00:00",
        ends_at="2026-08-25T23:59:59.999999+00:00",
        decisions=decisions,
    )
    result2 = pipeline.run(
        review_id="r1",
        period_id="2026-08-25",
        starts_at="2026-08-25T00:00:00+00:00",
        ends_at="2026-08-25T23:59:59.999999+00:00",
        decisions=decisions,
    )
    assert result1.status == "COMPLETED"
    assert result2.status == "ALREADY_COMPLETED"
    assert result1.candidate_lessons


def test_replay_uses_historical_snapshot_not_recompute():
    store = EvidenceStore()
    evidence = make_evidence()
    store.store_decision(evidence)
    from crypto_trader.factors.version import FactorSnapshotContract

    snapshot = FactorSnapshotContract(
        snapshot_id="fs1",
        timestamp_utc=evidence.timestamp_utc,
        symbol="BTCUSDT",
        timeframe="15m",
        factor_set_version="factorset-v1",
        factor_registry_version="r1",
        factor_config_hash="c1",
        factors=(),
        market_regime="TRENDING",
        market_data_version="m1",
        source_timestamp=evidence.timestamp_utc,
    )
    store.store_snapshot(snapshot)
    replay = HistoricalReplayEngine()
    replay.wire(evidence_store=store, snapshot_store=store)
    result = replay.replay("d1")
    assert result.factor_snapshot is not None
    assert result.factor_snapshot["snapshot_id"] == "fs1"
    assert result.information_available_at == evidence.timestamp_utc
