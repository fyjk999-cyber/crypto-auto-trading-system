"""Relevant-memory retrieval for the Live Trading Brain (CORE_TRADING_DOCTRINE_V1).

Memory is EVIDENCE, never a veto and never a second decision authority. This
provider reads the EXISTING canonical memory stores (no second memory system):

- learning_lessons      : confirmed Lessons (hierarchical engine CONFIRMED)
- ai_market_patterns    : learned Patterns (regime, strategy, win_rate, ...)
- ai_trade_episodes     : historical Episodes (result, pnl, holding time)
- ai_compressed_experience : compressed experience rules
- trade_memory_records  : recent decision/failure experience (via count)

Retrieval is bounded (top-N, relevance-scored by regime/symbol match) and
read-only. Memory refs are persisted with every decision so Daily Learning and
Evolution can audit what the Live brain actually saw.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from crypto_trader.persistence.models import (
    AICompressedExperienceORM,
    AIMarketPatternORM,
    AITradeEpisodeORM,
    LessonORM,
)


class LiveMemoryProvider:
    version = "1.0.0"

    def __init__(
        self,
        session_factory,
        *,
        max_lessons: int = 5,
        max_patterns: int = 3,
        max_episodes: int = 5,
        max_experience: int = 3,
    ) -> None:
        self.session_factory = session_factory
        self.max_lessons = max_lessons
        self.max_patterns = max_patterns
        self.max_episodes = max_episodes
        self.max_experience = max_experience

    async def _collect(self, session, regime: str, symbol: str) -> dict[str, Any]:
        lessons = (
            (
                await session.execute(
                    select(LessonORM)
                    .where(LessonORM.status == "CONFIRMED")
                    .order_by(LessonORM.confidence.desc(), LessonORM.evidence_count.desc())
                    .limit(self.max_lessons)
                )
            )
            .scalars()
            .all()
        )
        pattern_query = select(AIMarketPatternORM)
        if regime and regime != "UNKNOWN":
            pattern_query = pattern_query.where(AIMarketPatternORM.regime == regime)
        patterns = (
            (
                await session.execute(
                    pattern_query.order_by(AIMarketPatternORM.sample_count.desc())
                    .limit(self.max_patterns)
                )
            )
            .scalars()
            .all()
        )
        episodes = (
            (
                await session.execute(
                    select(AITradeEpisodeORM)
                    .order_by(AITradeEpisodeORM.created_at.desc())
                    .limit(60)
                )
            )
            .scalars()
            .all()
        )
        # Relevance: same regime weighs most, same symbol next; cross-coin
        # episodes remain eligible (same regime explains similar behaviour).
        scored: list[tuple[float, Any]] = []
        for episode in episodes:
            score = 0.0
            if regime and episode.market_regime == regime:
                score += 2.0
            if episode.symbol == symbol:
                score += 1.0
            if score > 0:
                scored.append((score, episode))
        scored.sort(key=lambda item: item[0], reverse=True)
        similar = [episode for _, episode in scored[: self.max_episodes]]
        experience = (
            (
                await session.execute(
                    select(AICompressedExperienceORM)
                    .order_by(AICompressedExperienceORM.created_at.desc())
                    .limit(self.max_experience)
                )
            )
            .scalars()
            .all()
        )
        return {
            "lessons": lessons,
            "patterns": patterns,
            "similar": similar,
            "experience": experience,
        }

    async def retrieve(self, regime: str = "", symbol: str = "") -> dict[str, Any]:
        """Bounded, read-only relevant memory. Never raises into trading."""
        async with self.session_factory() as session:
            collected = await self._collect(session, regime, symbol)

        knowledge = [
            {
                "lesson_id": lesson.lesson_id,
                "type": lesson.type,
                "statement": lesson.canonical_statement,
                "recommended_action": lesson.recommended_action,
                "confidence": lesson.confidence,
                "status": lesson.status,
            }
            for lesson in collected["lessons"]
        ]
        patterns = [
            {
                "pattern_id": pattern.pattern_id,
                "regime": pattern.regime,
                "strategy": pattern.strategy,
                "sample_count": pattern.sample_count,
                "win_rate": str(pattern.win_rate),
                "profit_factor": str(pattern.profit_factor),
            }
            for pattern in collected["patterns"]
        ]
        episodes = [
            {
                "episode_id": episode.episode_id,
                "symbol": episode.symbol,
                "market_regime": episode.market_regime,
                "strategy_selected": episode.strategy_selected,
                "result": episode.result,
                "pnl": str(episode.pnl),
                "holding_time_seconds": episode.holding_time_seconds,
            }
            for episode in collected["similar"]
        ]
        compressed = [
            {
                "rule_id": rule.rule_id,
                "title": rule.title,
                "content": rule.content[:300],
            }
            for rule in collected["experience"]
        ]
        memory_refs = (
            [item["lesson_id"] for item in knowledge]
            + [item["pattern_id"] for item in patterns]
            + [item["episode_id"] for item in episodes]
            + [item["rule_id"] for item in compressed]
        )
        return {
            "memory_refs": memory_refs,
            "knowledge": knowledge,
            "patterns": patterns,
            "similar_episodes": episodes,
            "compressed_experience": compressed,
        }
