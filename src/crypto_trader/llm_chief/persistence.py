"""Persistent stores for LLM knowledge/experience/coin/profile/compression."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select

from crypto_trader.llm_chief.memory import MarketPattern, TradeEpisode
from crypto_trader.persistence.models import (
    AICoinProfileORM,
    AICompressedExperienceORM,
    AIMarketPatternORM,
    AITradeEpisodeORM,
    AITradeReviewORM,
)


class LLMMemoryStore:
    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    async def save_episode(self, episode: TradeEpisode) -> None:
        async with self.session_factory() as session:
            session.add(
                AITradeEpisodeORM(
                    episode_id=episode.episode_id,
                    symbol=episode.symbol,
                    market_regime=episode.market_regime,
                    quant_evidence_json=episode.quant_evidence,
                    llm_reasoning=episode.llm_thesis,
                    pnl=episode.net_pnl,
                    result=episode.result,
                    review_status="PENDING",
                )
            )
            await session.commit()

    async def load_episodes(self, limit: int = 100) -> list[dict]:
        async with self.session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(AITradeEpisodeORM).order_by(AITradeEpisodeORM.id.desc()).limit(limit)
                    )
                )
                .scalars()
                .all()
            )
            return [
                {
                    "episode_id": r.episode_id,
                    "symbol": r.symbol,
                    "market_regime": r.market_regime,
                    "result": r.result,
                    "pnl": str(r.pnl),
                }
                for r in rows
            ]

    async def save_review(
        self,
        episode_id: str,
        success: list,
        failure: list,
        mistakes: list,
        lessons: list,
        future_rules: list,
        confidence: Decimal,
    ) -> None:
        async with self.session_factory() as session:
            session.add(
                AITradeReviewORM(
                    episode_id=episode_id,
                    success_factors_json=success,
                    failure_factors_json=failure,
                    mistakes_json=mistakes,
                    lessons_json=lessons,
                    future_rules_json=future_rules,
                    confidence=confidence,
                )
            )
            await session.commit()

    async def save_pattern(self, pattern: MarketPattern) -> None:
        async with self.session_factory() as session:
            row = await session.get(AIMarketPatternORM, pattern.pattern_id)
            if row is None:
                session.add(
                    AIMarketPatternORM(
                        pattern_id=pattern.pattern_id,
                        regime=pattern.regime,
                        strategy=pattern.strategy_family,
                        sample_count=pattern.sample_count,
                        win_rate=pattern.win_rate,
                        profit_factor=pattern.profit_factor,
                        version=pattern.version,
                    )
                )
            else:
                row.sample_count = pattern.sample_count
                row.win_rate = pattern.win_rate
                row.profit_factor = pattern.profit_factor
                row.version += 1
            await session.commit()

    async def save_coin_profile(
        self, symbol: str, sample_count: int, profile_summary: str, tags: list, version: int
    ) -> None:
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(AICoinProfileORM).where(AICoinProfileORM.symbol == symbol)
                )
            ).scalar_one_or_none()
            if row is None:
                session.add(
                    AICoinProfileORM(
                        symbol=symbol,
                        sample_count=sample_count,
                        profile_summary=profile_summary,
                        behavior_tags_json=tags,
                        version=version,
                    )
                )
            else:
                row.sample_count = sample_count
                row.profile_summary = profile_summary
                row.behavior_tags_json = tags
                row.version = version
                row.updated_at = datetime.now(UTC)
            await session.commit()

    async def save_compressed(
        self, rule_id: str, title: str, content: str, source_count: int
    ) -> None:
        async with self.session_factory() as session:
            session.add(
                AICompressedExperienceORM(
                    rule_id=rule_id,
                    title=title,
                    content=content,
                    source_episode_count=source_count,
                )
            )
            await session.commit()

    async def load_compressed(self, limit: int = 10) -> list[dict]:
        async with self.session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(AICompressedExperienceORM)
                        .order_by(AICompressedExperienceORM.id.desc())
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )
            return [{"rule_id": r.rule_id, "title": r.title, "content": r.content} for r in rows]
