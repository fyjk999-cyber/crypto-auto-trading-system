"""Load reviewed factual memory/research context for ChiefTrader decisions."""

from __future__ import annotations

from dataclasses import replace

from sqlalchemy import case, select

from crypto_trader.llm_chief.context import ChiefTraderContext
from crypto_trader.persistence.models import (
    AICoinProfileORM,
    AICompressedExperienceORM,
    AIMarketPatternORM,
    AITradeReviewORM,
    ResearchReportORM,
    TradeEpisodeORM,
)


class ChiefContextLoader:
    """Read-only retrieval; retrieved records never become an execution gate."""

    def __init__(self, session_factory, *, limit: int = 5) -> None:
        self.session_factory = session_factory
        self.limit = limit

    async def enrich(self, context: ChiefTraderContext) -> ChiefTraderContext:
        async with self.session_factory() as session:
            episodes = (
                await session.execute(
                    select(TradeEpisodeORM)
                    .where(
                        TradeEpisodeORM.factual.is_(True),
                        TradeEpisodeORM.review_status == "REVIEWED",
                    )
                    .order_by(
                        case((TradeEpisodeORM.symbol == context.symbol, 0), else_=1),
                        case(
                            (TradeEpisodeORM.entry_market_regime == context.regime, 0),
                            else_=1,
                        ),
                        TradeEpisodeORM.closed_at.desc(),
                    )
                    .limit(self.limit)
                )
            ).scalars().all()
            episode_ids = [row.episode_id for row in episodes]
            reviews = []
            if episode_ids:
                reviews = (
                    await session.execute(
                        select(AITradeReviewORM).where(
                            AITradeReviewORM.episode_id.in_(episode_ids)
                        )
                    )
                ).scalars().all()
            research = (
                await session.execute(
                    select(ResearchReportORM)
                    .order_by(ResearchReportORM.created_at.desc())
                    .limit(self.limit)
                )
            ).scalars().all()
            compressed = (
                await session.execute(
                    select(AICompressedExperienceORM)
                    .order_by(AICompressedExperienceORM.created_at.desc())
                    .limit(self.limit)
                )
            ).scalars().all()
            profile = (
                await session.execute(
                    select(AICoinProfileORM).where(
                        AICoinProfileORM.symbol == context.symbol
                    )
                )
            ).scalar_one_or_none()
            patterns = (
                await session.execute(
                    select(AIMarketPatternORM)
                    .where(AIMarketPatternORM.regime == context.regime)
                    .order_by(AIMarketPatternORM.sample_count.desc())
                    .limit(self.limit)
                )
            ).scalars().all()

        return replace(
            context,
            knowledge=[
                {
                    "kind": "RESEARCH",
                    "research_id": row.research_id,
                    "summary": row.summary,
                    "conclusion": row.conclusion,
                    "confidence": row.confidence,
                }
                for row in research
            ]
            + [
                {
                    "kind": "FACTUAL_PATTERN",
                    "pattern_id": row.pattern_id,
                    "regime": row.regime,
                    "direction": row.strategy,
                    "sample_count": row.sample_count,
                    "win_rate": str(row.win_rate),
                    "profit_factor": str(row.profit_factor),
                }
                for row in patterns
            ],
            similar_episodes=[
                {
                    "episode_id": row.episode_id,
                    "symbol": row.symbol,
                    "direction": row.direction,
                    "regime": row.entry_market_regime,
                    "net_pnl": str(row.net_pnl),
                    "holding_time_seconds": row.holding_time_seconds,
                }
                for row in episodes
            ],
            coin_profile=(
                {
                    "symbol": profile.symbol,
                    "sample_count": profile.sample_count,
                    "summary": profile.profile_summary,
                    "tags": list(profile.behavior_tags_json or []),
                }
                if profile is not None
                else {}
            ),
            compressed_experience=[
                {"rule_id": row.rule_id, "title": row.title, "content": row.content}
                for row in compressed
            ],
            failure_warnings=[
                warning
                for row in reviews
                for warning in list(row.failure_factors_json or [])
            ],
            memory_refs=[f"review:{row.episode_id}" for row in reviews],
            research_refs=[row.research_id for row in research],
            episode_refs=episode_ids,
            pattern_refs=[row.pattern_id for row in patterns],
        )
