"""SQL persistence backends for Daily Learning Brain."""

from __future__ import annotations

from sqlalchemy import select

from crypto_trader.persistence.models import (
    DailyReviewResultORM,
    DecisionEvidenceORM,
    LessonORM,
    PatternCandidateORM,
    ReviewJobORM,
)


class SqlEvidenceBackend:
    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    async def store_decision(self, evidence: dict) -> None:
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(DecisionEvidenceORM).where(
                        DecisionEvidenceORM.decision_id == evidence["decision_id"]
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                session.add(
                    DecisionEvidenceORM(
                        decision_id=evidence["decision_id"],
                        timestamp_utc=evidence["timestamp_utc"],
                        symbol=evidence["symbol"],
                        timeframe=evidence["timeframe"],
                        strategy_id=evidence["strategy_id"],
                        strategy_version=evidence["strategy_version"],
                        model_version=evidence["model_version"],
                        prompt_version=evidence["prompt_version"],
                        factor_snapshot_id=evidence["factor_snapshot_id"],
                        factor_set_version=evidence["factor_set_version"],
                        factor_profile=evidence["factor_profile"],
                        market_data_reference=evidence["market_data_reference"],
                        analysis_evidence_json=evidence.get("analysis_evidence", {}),
                        decision_json=evidence.get("decision", {}),
                        risk_decision_json=evidence.get("risk_decision", {}),
                        execution_intent_reference=evidence.get("execution_intent_reference", ""),
                        created_at_utc=evidence.get("created_at_utc", ""),
                    )
                )
                await session.commit()

    async def get_decision(self, decision_id: str) -> dict | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(DecisionEvidenceORM).where(
                        DecisionEvidenceORM.decision_id == decision_id
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            return {
                "decision_id": row.decision_id,
                "timestamp_utc": row.timestamp_utc,
                "symbol": row.symbol,
                "timeframe": row.timeframe,
                "strategy_id": row.strategy_id,
                "strategy_version": row.strategy_version,
                "model_version": row.model_version,
                "prompt_version": row.prompt_version,
                "factor_snapshot_id": row.factor_snapshot_id,
                "factor_set_version": row.factor_set_version,
                "factor_profile": row.factor_profile,
                "market_data_reference": row.market_data_reference,
                "analysis_evidence": row.analysis_evidence_json or {},
                "decision": row.decision_json or {},
                "risk_decision": row.risk_decision_json or {},
                "execution_intent_reference": row.execution_intent_reference,
                "created_at_utc": row.created_at_utc,
            }

    async def store_review(self, review: dict) -> None:
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(DailyReviewResultORM).where(
                        DailyReviewResultORM.review_id == review["review_id"]
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                session.add(
                    DailyReviewResultORM(
                        review_id=review["review_id"],
                        review_type=review.get("review_type", "DAILY"),
                        period_id=review["period_id"],
                        starts_at=review.get("starts_at", ""),
                        ends_at=review.get("ends_at", ""),
                        triggered_at=review.get("triggered_at", ""),
                        decision_count=review.get("decision_count", 0),
                        trade_count=review.get("trade_count", 0),
                        result_json=review,
                        data_quality=review.get("data_quality", "OK"),
                        warnings_json=review.get("warnings", []),
                        status=review.get("status", "COMPLETED"),
                    )
                )
                await session.commit()

    async def get_review(self, review_id: str) -> dict | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(DailyReviewResultORM).where(DailyReviewResultORM.review_id == review_id)
                )
            ).scalar_one_or_none()
            return row.result_json if row else None

    async def store_pattern(self, pattern: dict) -> None:
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(PatternCandidateORM).where(
                        PatternCandidateORM.pattern_id == pattern["pattern_id"]
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                session.add(
                    PatternCandidateORM(
                        pattern_id=pattern["pattern_id"],
                        scope=pattern.get("scope", "GLOBAL"),
                        pattern_type=pattern["pattern_type"],
                        conditions_json=pattern.get("conditions", []),
                        evidence_count=pattern.get("evidence_count", 0),
                        decision_ids_json=pattern.get("decision_ids", []),
                        confidence=pattern.get("confidence", 0.0),
                        status=pattern.get("status", "CANDIDATE"),
                    )
                )
                await session.commit()

    async def store_lesson(self, lesson: dict) -> None:
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(LessonORM).where(LessonORM.lesson_id == lesson["lesson_id"])
                )
            ).scalar_one_or_none()
            if row is None:
                session.add(
                    LessonORM(
                        lesson_id=lesson["lesson_id"],
                        scope=lesson.get("scope", "GLOBAL"),
                        type=lesson.get("type", ""),
                        canonical_statement=lesson.get("canonical_statement", ""),
                        conditions_json=lesson.get("conditions", []),
                        recommended_action=lesson.get("recommended_action", ""),
                        evidence_count=lesson.get("evidence_count", 0),
                        supporting_decisions_json=lesson.get("supporting_decisions", []),
                        contradictions_json=lesson.get("contradictions", []),
                        first_seen=lesson.get("first_seen", ""),
                        last_seen=lesson.get("last_seen", ""),
                        confidence=lesson.get("confidence", 0.0),
                        status=lesson.get("status", "CANDIDATE"),
                        source_review_ids_json=lesson.get("source_review_ids", []),
                        source_pattern_ids_json=lesson.get("source_pattern_ids", []),
                    )
                )
                await session.commit()


class SqlMemoryBackend:
    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    async def list_lessons(self) -> list[dict]:
        async with self.session_factory() as session:
            rows = (await session.execute(select(LessonORM))).scalars().all()
            return [
                {
                    "lesson_id": r.lesson_id,
                    "scope": r.scope,
                    "type": r.type,
                    "canonical_statement": r.canonical_statement,
                    "evidence_count": r.evidence_count,
                    "confidence": r.confidence,
                    "status": r.status,
                }
                for r in rows
            ]

    async def update_lesson_status(self, lesson_id: str, status: str) -> None:
        async with self.session_factory() as session:
            row = (
                await session.execute(select(LessonORM).where(LessonORM.lesson_id == lesson_id))
            ).scalar_one_or_none()
            if row is not None:
                row.status = status
                await session.commit()


class ReviewJobStore:
    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    async def get(self, review_key: str) -> dict | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(ReviewJobORM).where(ReviewJobORM.review_key == review_key)
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            return {
                "review_key": row.review_key,
                "review_id": row.review_id,
                "period_type": row.period_type,
                "period_id": row.period_id,
                "status": row.status,
                "attempt": row.attempt,
                "error": row.error,
            }

    async def put(
        self,
        review_key: str,
        review_id: str,
        period_type: str,
        period_id: str,
        status: str,
        error: str = "",
    ) -> None:
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(ReviewJobORM).where(ReviewJobORM.review_key == review_key)
                )
            ).scalar_one_or_none()
            if row is None:
                session.add(
                    ReviewJobORM(
                        review_key=review_key,
                        review_id=review_id,
                        period_type=period_type,
                        period_id=period_id,
                        status=status,
                        error=error,
                    )
                )
            else:
                row.status = status
                row.error = error
                row.attempt += 1
            await session.commit()
