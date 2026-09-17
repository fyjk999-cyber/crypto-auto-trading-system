"""Load reviewed factual memory/research context for ChiefTrader decisions."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from sqlalchemy import and_, case, or_, select

from crypto_trader.learning.retrieval import GrowthRetriever
from crypto_trader.llm.tools.registry import ToolEvidence
from crypto_trader.llm_chief.context import ChiefTraderContext
from crypto_trader.llm_chief.growth_context import build_growth_context
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

    def __init__(
        self,
        session_factory,
        *,
        limit: int = 5,
        news_retriever=None,
        token_budget: int | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.limit = limit
        self.news_retriever = news_retriever
        self.token_budget = token_budget

    async def enrich(self, context: ChiefTraderContext) -> ChiefTraderContext:
        async with self.session_factory() as session:
            episodes = (
                (
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
                )
                .scalars()
                .all()
            )
            episode_ids = [row.episode_id for row in episodes]
            reviews = []
            if episode_ids:
                reviews = (
                    (
                        await session.execute(
                            select(AITradeReviewORM).where(
                                AITradeReviewORM.episode_id.in_(episode_ids)
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
            research = (
                (
                    await session.execute(
                        select(ResearchReportORM)
                        .where(
                            ResearchReportORM.created_at <= _context_as_of(context),
                            _research_scope_clause(context),
                        )
                        .order_by(ResearchReportORM.created_at.desc())
                        .limit(self.limit)
                    )
                )
                .scalars()
                .all()
            )
            compressed = (
                (
                    await session.execute(
                        select(AICompressedExperienceORM)
                        .order_by(AICompressedExperienceORM.created_at.desc())
                        .limit(self.limit)
                    )
                )
                .scalars()
                .all()
            )
            profile = (
                await session.execute(
                    select(AICoinProfileORM).where(AICoinProfileORM.symbol == context.symbol)
                )
            ).scalar_one_or_none()
            patterns = (
                (
                    await session.execute(
                        select(AIMarketPatternORM)
                        .where(AIMarketPatternORM.regime == context.regime)
                        .order_by(AIMarketPatternORM.sample_count.desc())
                        .limit(self.limit)
                    )
                )
                .scalars()
                .all()
            )

        enriched = replace(
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
                {"rule_id": row.rule_id, "title": row.title, "content": row.content}
                for row in compressed
            ],
            failure_warnings=[
                warning for row in reviews for warning in list(row.failure_factors_json or [])
            ],
            memory_refs=[f"review:{row.episode_id}" for row in reviews],
            research_refs=[row.research_id for row in research],
            episode_refs=episode_ids,
            pattern_refs=[row.pattern_id for row in patterns],
        )
        if self.news_retriever is not None:
            enriched = replace(enriched, news_context=await self._news_context(enriched))
        return enriched

    async def _growth_retrieval_evidence(self, context: ChiefTraderContext):
        """Canonical as-of Growth retrieval for Chief context (read-only)."""
        retriever = GrowthRetriever(self.session_factory)
        enriched = await build_growth_context(
            retriever,
            symbol=context.symbol,
            regime=getattr(context, "regime", "") or "",
            strategy=getattr(context, "strategy", "") or "",
            horizon=getattr(context, "horizon", "") or "",
            setup_signature=getattr(context, "setup_signature", "") or "",
            top_k=self.limit,
        )
        finding = {
            "similar_episodes": enriched["similar_episodes"],
            "patterns": enriched["patterns"],
            "generalized_knowledge": enriched["generalized_knowledge"],
            "coin_profile": enriched["coin_profile"],
            "compressed_experience": enriched["compressed_experience"],
            "strategy": enriched["strategy"],
            "direction": enriched["direction"],
            "warnings": enriched["warnings"],
        }
        refs = [{"memory_ref": ref} for ref in enriched["memory_refs"]]
        return finding, refs, datetime.now(UTC)

    async def load_tool(self, name: str, context: ChiefTraderContext) -> ToolEvidence:
        """Load only the learned evidence explicitly selected by ChiefTrader."""

        loaders = {
            "memory_search": self._memory_evidence,
            "episode_search": self._episode_evidence,
            "research_retrieval": self._research_evidence,
            "coin_profile": self._coin_profile_evidence,
            "factor_intelligence": self._pattern_evidence,
            "growth_memory": self._growth_retrieval_evidence,
            "news_context": self._news_evidence,
        }
        loader = loaders.get(name)
        if loader is None:
            raise ValueError(f"unknown learned-context tool: {name}")
        finding, refs, timestamp = await loader(context)
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

    async def _news_context(self, context: ChiefTraderContext) -> dict:
        retriever = self.news_retriever
        if retriever is None:
            return _news_unavailable("NEWS_RETRIEVER_NOT_CONFIGURED")
        try:
            return await retriever.get_news_context(
                symbol=context.symbol,
                as_of=_parse_as_of(getattr(context, "prepared_at", None)),
                position_state={
                    "symbol": context.symbol,
                    "position_state": context.position_state.value,
                    **dict(context.position_context or {}),
                },
                max_items=self.limit,
                token_budget=self.token_budget,
            )
        except Exception as exc:  # fail explicit: unavailable, never fabricated
            return _news_unavailable(f"NEWS_CONTEXT_UNAVAILABLE:{type(exc).__name__}")

    async def _news_evidence(self, context: ChiefTraderContext):
        news_context = getattr(context, "news_context", None)
        if news_context is None:
            news_context = await self._news_context(context)
        events = list(news_context.get("events") or [])
        supporting: list[str] = []
        contrary: list[str] = []
        for event in events:
            label = str(event.get("event_id") or "")
            supporting.extend(f"{label}: {point}" for point in event.get("support_points") or [])
            contrary.extend(f"{label}: {point}" for point in event.get("counter_points") or [])
        available = bool(events)
        finding = news_context if available else {}
        return (
            finding,
            list(news_context.get("news_evidence_refs") or []),
            _parse_as_of(news_context.get("as_of")),
        )

    async def _episode_evidence(self, context: ChiefTraderContext):
        async with self.session_factory() as session:
            rows = (
                (
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
                )
                .scalars()
                .all()
            )
        finding = (
            {
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
            }
            if rows
            else {}
        )
        return finding, [f"episode:{row.episode_id}" for row in rows], _latest(rows, "closed_at")

    async def _memory_evidence(self, context: ChiefTraderContext):
        async with self.session_factory() as session:
            reviews = (
                (
                    await session.execute(
                        select(AITradeReviewORM)
                        .join(
                            TradeEpisodeORM,
                            TradeEpisodeORM.episode_id == AITradeReviewORM.episode_id,
                        )
                        .where(TradeEpisodeORM.symbol == context.symbol)
                        .order_by(AITradeReviewORM.created_at.desc())
                        .limit(self.limit)
                    )
                )
                .scalars()
                .all()
            )
            compressed = (
                (
                    await session.execute(
                        select(AICompressedExperienceORM)
                        .order_by(AICompressedExperienceORM.created_at.desc())
                        .limit(self.limit)
                    )
                )
                .scalars()
                .all()
            )
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
                {"rule_id": row.rule_id, "title": row.title, "content": row.content}
                for row in compressed
            ]
        refs = [f"memory:review:{row.episode_id}" for row in reviews]
        refs.extend(f"memory:rule:{row.rule_id}" for row in compressed)
        timestamp = max(
            [row.created_at for row in reviews] + [row.created_at for row in compressed],
            default=None,
        )
        return finding, refs, timestamp

    async def _research_evidence(self, context: ChiefTraderContext):
        async with self.session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(ResearchReportORM)
                        .where(
                            ResearchReportORM.created_at <= _context_as_of(context),
                            _research_scope_clause(context),
                        )
                        .order_by(ResearchReportORM.created_at.desc())
                        .limit(self.limit)
                    )
                )
                .scalars()
                .all()
            )
        finding = (
            {
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
            }
            if rows
            else {}
        )
        return finding, [f"research:{row.research_id}" for row in rows], _latest(rows, "created_at")

    async def _coin_profile_evidence(self, context: ChiefTraderContext):
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(AICoinProfileORM).where(AICoinProfileORM.symbol == context.symbol)
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

    async def _pattern_evidence(self, context: ChiefTraderContext):
        async with self.session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(AIMarketPatternORM)
                        .where(AIMarketPatternORM.regime == context.regime)
                        .order_by(AIMarketPatternORM.sample_count.desc())
                        .limit(self.limit)
                    )
                )
                .scalars()
                .all()
            )
        finding = (
            {
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
            }
            if rows
            else {}
        )
        return finding, [f"pattern:{row.pattern_id}" for row in rows], _latest(rows, "created_at")


def _parse_as_of(value) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
        except ValueError:
            return None
    return None


def _news_unavailable(reason: str) -> dict:
    return {
        "as_of": datetime.now(UTC).isoformat(),
        "health": "NO_NEWS_AVAILABLE",
        "unavailable": True,
        "events": [],
        "news_evidence_refs": [],
        "context_hash": "",
        "authority": "EVIDENCE_ONLY",
        "is_order": False,
        "reason": reason,
    }


def _context_as_of(context: ChiefTraderContext) -> datetime:
    """Decision as-of boundary; legacy contexts fall back to now (fail-safe)."""
    raw = getattr(context, "prepared_at", None)
    if isinstance(raw, str):
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            parsed = None
        if parsed is not None:
            return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    return datetime.now(UTC)


def _research_scope_clause(context: ChiefTraderContext):
    """Only research explicitly applicable to this decision may be retrieved."""
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
