"""Load reviewed factual memory/research context for ChiefTrader decisions."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from sqlalchemy import and_, or_, select

from crypto_trader.llm.tools.registry import ToolEvidence
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
        as_of = _context_as_of(context)
        async with self.session_factory() as session:
            episodes = (
                await session.execute(
                    select(TradeEpisodeORM)
                    .where(
                        TradeEpisodeORM.factual.is_(True),
                        TradeEpisodeORM.review_status == "REVIEWED",
                        TradeEpisodeORM.symbol == context.symbol,
                        TradeEpisodeORM.entry_market_regime == context.regime,
                        TradeEpisodeORM.closed_at <= as_of,
                    )
                    .order_by(TradeEpisodeORM.closed_at.desc())
                    .limit(self.limit)
                )
            ).scalars().all()
            episode_ids = [row.episode_id for row in episodes]
            reviews = []
            if episode_ids:
                reviews = (
                    await session.execute(
                        select(AITradeReviewORM).where(
                            AITradeReviewORM.episode_id.in_(episode_ids),
                            AITradeReviewORM.created_at <= as_of,
                        )
                    )
                ).scalars().all()
            research = (
                await session.execute(
                    select(ResearchReportORM)
                    .where(
                        ResearchReportORM.created_at <= as_of,
                        _research_scope_clause(context),
                    )
                    .order_by(ResearchReportORM.created_at.desc())
                    .limit(self.limit)
                )
            ).scalars().all()
            compressed = (
                await session.execute(
                    select(AICompressedExperienceORM)
                    .where(AICompressedExperienceORM.created_at <= as_of)
                    .order_by(AICompressedExperienceORM.created_at.desc())
                    .limit(self.limit)
                )
            ).scalars().all()
            profile = (
                await session.execute(
                    select(AICoinProfileORM).where(
                        AICoinProfileORM.symbol == context.symbol,
                        AICoinProfileORM.updated_at <= as_of,
                    )
                )
            ).scalar_one_or_none()
            patterns = (
                await session.execute(
                    select(AIMarketPatternORM)
                    .where(AIMarketPatternORM.regime == context.regime)
                    .where(AIMarketPatternORM.created_at <= as_of)
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
                    "scope_type": row.scope_type,
                    "symbol": row.symbol,
                    "regime": row.regime,
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
                {
                    "rule_id": row.rule_id,
                    "title": row.title,
                    "content": row.content,
                    "scope_type": "GLOBAL",
                }
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

    async def load_tool(
        self, name: str, context: ChiefTraderContext, *, as_of: datetime | None = None
    ) -> ToolEvidence:
        """Load only the learned evidence explicitly selected by ChiefTrader."""

        loaders = {
            "memory_search": self._memory_evidence,
            "episode_search": self._episode_evidence,
            "research_retrieval": self._research_evidence,
            "coin_profile": self._coin_profile_evidence,
            "factor_intelligence": self._pattern_evidence,
        }
        loader = loaders.get(name)
        if loader is None:
            raise ValueError(f"unknown learned-context tool: {name}")
        finding, refs, timestamp = await loader(context, as_of or _context_as_of(context))
        return ToolEvidence(
            tool_name=name,
            symbol=context.symbol,
            timestamp=timestamp or datetime.now(UTC),
            features=finding,
            supporting_evidence=[],
            contrary_evidence=[],
            confidence_of_measurement=1.0 if finding else 0.0,
            data_quality="FACTUAL_REVIEWED" if finding else "NO_MATCHES",
            source_refs=refs,
        )

    async def _episode_evidence(self, context: ChiefTraderContext, as_of: datetime):
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(TradeEpisodeORM)
                    .where(
                        TradeEpisodeORM.factual.is_(True),
                        TradeEpisodeORM.review_status == "REVIEWED",
                        TradeEpisodeORM.symbol == context.symbol,
                        TradeEpisodeORM.entry_market_regime == context.regime,
                        TradeEpisodeORM.closed_at <= as_of,
                    )
                    .order_by(TradeEpisodeORM.closed_at.desc())
                    .limit(self.limit)
                )
            ).scalars().all()
        finding = {
            "episodes": [
                {
                    "episode_id": row.episode_id,
                    "symbol": row.symbol,
                    "direction": row.direction,
                    "regime": row.entry_market_regime,
                    "net_pnl": str(row.net_pnl),
                    "holding_time_seconds": row.holding_time_seconds,
                }
                for row in rows
            ]
        } if rows else {}
        return finding, [f"episode:{row.episode_id}" for row in rows], _latest(rows, "closed_at")

    async def _memory_evidence(self, context: ChiefTraderContext, as_of: datetime):
        async with self.session_factory() as session:
            reviews = (
                await session.execute(
                    select(AITradeReviewORM)
                    .join(
                        TradeEpisodeORM,
                        TradeEpisodeORM.episode_id == AITradeReviewORM.episode_id,
                    )
                    .where(
                        TradeEpisodeORM.factual.is_(True),
                        TradeEpisodeORM.review_status == "REVIEWED",
                        TradeEpisodeORM.symbol == context.symbol,
                        TradeEpisodeORM.entry_market_regime == context.regime,
                        TradeEpisodeORM.closed_at <= as_of,
                        AITradeReviewORM.created_at <= as_of,
                    )
                    .order_by(AITradeReviewORM.created_at.desc())
                    .limit(self.limit)
                )
            ).scalars().all()
            compressed = (
                await session.execute(
                    select(AICompressedExperienceORM)
                    .where(AICompressedExperienceORM.created_at <= as_of)
                    .order_by(AICompressedExperienceORM.created_at.desc())
                    .limit(self.limit)
                )
            ).scalars().all()
        finding = {}
        if reviews:
            finding["reviews"] = [
                {
                    "episode_id": row.episode_id,
                    "success_factors": list(row.success_factors_json or []),
                    "failure_factors": list(row.failure_factors_json or []),
                    "lessons": list(row.lessons_json or []),
                    "future_rules": list(row.future_rules_json or []),
                }
                for row in reviews
            ]
        if compressed:
            finding["compressed_experience"] = [
                {
                    "rule_id": row.rule_id,
                    "title": row.title,
                    "content": row.content,
                    "scope_type": "GLOBAL",
                }
                for row in compressed
            ]
        refs = [f"memory:review:{row.episode_id}" for row in reviews]
        refs.extend(f"memory:rule:{row.rule_id}" for row in compressed)
        timestamp = max(
            [row.created_at for row in reviews] + [row.created_at for row in compressed],
            default=None,
        )
        return finding, refs, timestamp

    async def _research_evidence(self, context: ChiefTraderContext, as_of: datetime):
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(ResearchReportORM)
                    .where(
                        ResearchReportORM.created_at <= as_of,
                        _research_scope_clause(context),
                    )
                    .order_by(ResearchReportORM.created_at.desc())
                    .limit(self.limit)
                )
            ).scalars().all()
        finding = {
            "research": [
                {
                    "research_id": row.research_id,
                    "scope_type": row.scope_type,
                    "symbol": row.symbol,
                    "regime": row.regime,
                    "summary": row.summary,
                    "conclusion": row.conclusion,
                    "confidence": row.confidence,
                }
                for row in rows
            ]
        } if rows else {}
        return finding, [f"research:{row.research_id}" for row in rows], _latest(rows, "created_at")

    async def _coin_profile_evidence(self, context: ChiefTraderContext, as_of: datetime):
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(AICoinProfileORM).where(
                        AICoinProfileORM.symbol == context.symbol,
                        AICoinProfileORM.updated_at <= as_of,
                    )
                )
            ).scalar_one_or_none()
        finding = (
            {
                "profile": {
                    "symbol": row.symbol,
                    "sample_count": row.sample_count,
                    "summary": row.profile_summary,
                    "tags": list(row.behavior_tags_json or []),
                    "best_setups": list(row.best_setups_json or []),
                    "worst_setups": list(row.worst_setups_json or []),
                }
            }
            if row is not None
            else {}
        )
        return (
            finding,
            [f"profile:{row.symbol}:v{row.version}"] if row else [],
            row.updated_at if row else None,
        )

    async def _pattern_evidence(self, context: ChiefTraderContext, as_of: datetime):
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(AIMarketPatternORM)
                    .where(
                        AIMarketPatternORM.regime == context.regime,
                        AIMarketPatternORM.created_at <= as_of,
                    )
                    .order_by(AIMarketPatternORM.sample_count.desc())
                    .limit(self.limit)
                )
            ).scalars().all()
        finding = {
            "patterns": [
                {
                    "pattern_id": row.pattern_id,
                    "regime": row.regime,
                    "direction": row.strategy,
                    "sample_count": row.sample_count,
                    "win_rate": str(row.win_rate),
                    "profit_factor": str(row.profit_factor),
                    "success_drivers": list(row.success_drivers_json or []),
                    "failure_drivers": list(row.failure_drivers_json or []),
                }
                for row in rows
            ]
        } if rows else {}
        return finding, [f"pattern:{row.pattern_id}" for row in rows], _latest(rows, "created_at")


def _research_scope_clause(context: ChiefTraderContext):
    """Only research explicitly applicable to this decision context may be read."""

    return or_(
        ResearchReportORM.scope_type == "GLOBAL",
        and_(
            ResearchReportORM.scope_type == "SYMBOL",
            ResearchReportORM.symbol == context.symbol,
        ),
        and_(
            ResearchReportORM.scope_type == "REGIME",
            ResearchReportORM.regime == context.regime,
        ),
        and_(
            ResearchReportORM.scope_type == "SYMBOL_REGIME",
            ResearchReportORM.symbol == context.symbol,
            ResearchReportORM.regime == context.regime,
        ),
    )


def _latest(rows, field: str):
    return max((getattr(row, field) for row in rows), default=None)


def _context_as_of(context: ChiefTraderContext) -> datetime:
    parsed = datetime.fromisoformat(context.prepared_at)
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)
