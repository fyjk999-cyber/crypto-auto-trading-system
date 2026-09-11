"""Load reviewed factual memory/research context for ChiefTrader decisions."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from sqlalchemy import case, or_, select

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
                        TradeEpisodeORM.closed_at <= as_of,
                    )
                    .order_by(
                        case((TradeEpisodeORM.symbol == context.symbol, 0), else_=1),
                        case(
                            (TradeEpisodeORM.entry_market_regime == context.regime, 0),
                            else_=1,
                        ),
                        TradeEpisodeORM.closed_at.desc(),
                    )
                    .limit(self.limit * 5)
                )
            ).scalars().all()
            episodes = [
                row
                for row in episodes
                if _scope_applies(
                    row.applicability_scope_json, context.symbol, context.regime
                )
            ][: self.limit]
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
                        or_(
                            ResearchReportORM.symbol.is_(None),
                            ResearchReportORM.symbol == context.symbol,
                        ),
                    )
                    .order_by(ResearchReportORM.created_at.desc())
                    .limit(self.limit * 5)
                )
            ).scalars().all()
            research = [
                row
                for row in research
                if _scope_applies(
                    row.applicability_scope_json, context.symbol, context.regime
                )
            ][: self.limit]
            compressed = (
                await session.execute(
                    select(AICompressedExperienceORM)
                    .where(
                        AICompressedExperienceORM.created_at <= as_of,
                        or_(
                            AICompressedExperienceORM.symbol.is_(None),
                            AICompressedExperienceORM.symbol == context.symbol,
                        ),
                    )
                    .order_by(AICompressedExperienceORM.created_at.desc())
                    .limit(self.limit * 5)
                )
            ).scalars().all()
            compressed = [
                row
                for row in compressed
                if _scope_applies(
                    row.applicability_scope_json, context.symbol, context.regime
                )
            ][: self.limit]
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
                    .where(
                        AIMarketPatternORM.regime == context.regime,
                        AIMarketPatternORM.created_at <= as_of,
                        or_(
                            AIMarketPatternORM.symbol.is_(None),
                            AIMarketPatternORM.symbol == context.symbol,
                        ),
                    )
                    .order_by(AIMarketPatternORM.sample_count.desc())
                    .limit(self.limit * 5)
                )
            ).scalars().all()
            patterns = [
                row
                for row in patterns
                if _scope_applies(
                    row.applicability_scope_json, context.symbol, context.regime
                )
            ][: self.limit]

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
                        TradeEpisodeORM.closed_at <= as_of,
                    )
                    .order_by(
                        case((TradeEpisodeORM.symbol == context.symbol, 0), else_=1),
                        case(
                            (TradeEpisodeORM.entry_market_regime == context.regime, 0),
                            else_=1,
                        ),
                        TradeEpisodeORM.closed_at.desc(),
                    )
                    .limit(self.limit * 5)
                )
            ).scalars().all()
            rows = [
                row
                for row in rows
                if _scope_applies(
                    row.applicability_scope_json, context.symbol, context.regime
                )
            ][: self.limit]
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
            review_rows = (
                await session.execute(
                    select(AITradeReviewORM, TradeEpisodeORM)
                    .join(
                        TradeEpisodeORM,
                        TradeEpisodeORM.episode_id == AITradeReviewORM.episode_id,
                    )
                    .where(
                        TradeEpisodeORM.symbol == context.symbol,
                        TradeEpisodeORM.factual.is_(True),
                        TradeEpisodeORM.review_status == "REVIEWED",
                        TradeEpisodeORM.closed_at <= as_of,
                        AITradeReviewORM.created_at <= as_of,
                    )
                    .order_by(AITradeReviewORM.created_at.desc())
                    .limit(self.limit * 5)
                )
            ).all()
            reviews = [
                review
                for review, episode in review_rows
                if _scope_applies(
                    episode.applicability_scope_json,
                    context.symbol,
                    context.regime,
                )
            ][: self.limit]
            compressed = (
                await session.execute(
                    select(AICompressedExperienceORM)
                    .where(
                        AICompressedExperienceORM.created_at <= as_of,
                        or_(
                            AICompressedExperienceORM.symbol.is_(None),
                            AICompressedExperienceORM.symbol == context.symbol,
                        ),
                    )
                    .order_by(AICompressedExperienceORM.created_at.desc())
                    .limit(self.limit * 5)
                )
            ).scalars().all()
            compressed = [
                row
                for row in compressed
                if _scope_applies(
                    row.applicability_scope_json, context.symbol, context.regime
                )
            ][: self.limit]
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

    async def _research_evidence(self, context: ChiefTraderContext, as_of: datetime):
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(ResearchReportORM)
                    .where(
                        ResearchReportORM.created_at <= as_of,
                        or_(
                            ResearchReportORM.symbol.is_(None),
                            ResearchReportORM.symbol == context.symbol,
                        ),
                    )
                    .order_by(ResearchReportORM.created_at.desc())
                    .limit(self.limit * 5)
                )
            ).scalars().all()
            rows = [
                row
                for row in rows
                if _scope_applies(
                    row.applicability_scope_json, context.symbol, context.regime
                )
            ][: self.limit]
        finding = {
            "research": [
                {
                    "research_id": row.research_id,
                    "summary": row.summary,
                    "conclusion": row.conclusion,
                    "confidence": row.confidence,
                }
                for row in rows
            ]
        } if rows else {}
        return finding, [f"research:{row.research_id}" for row in rows], _latest(rows, "created_at")

    async def _coin_profile_evidence(self, context: ChiefTraderContext, as_of: datetime):
        # R12 fail-closed: AICoinProfileORM has no account/mode provenance, so
        # a symbol-only profile must not cross account/mode boundaries.  The
        # canonical runtime path is the Growth V2 Adaptive Experience Card
        # retriever; this v1 loader reports scope-unavailable instead of
        # guessing a global profile.
        return (
            {"scope_unavailable": True, "reason": "NO_ACCOUNT_MODE_PROVENANCE"},
            [],
            None,
        )

    async def _pattern_evidence(self, context: ChiefTraderContext, as_of: datetime):
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(AIMarketPatternORM)
                    .where(
                        AIMarketPatternORM.regime == context.regime,
                        AIMarketPatternORM.created_at <= as_of,
                        or_(
                            AIMarketPatternORM.symbol.is_(None),
                            AIMarketPatternORM.symbol == context.symbol,
                        ),
                    )
                    .order_by(AIMarketPatternORM.sample_count.desc())
                    .limit(self.limit * 5)
                )
            ).scalars().all()
            rows = [
                row
                for row in rows
                if _scope_applies(
                    row.applicability_scope_json, context.symbol, context.regime
                )
            ][: self.limit]
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


def _scope_applies(scope, symbol: str, regime: str) -> bool:
    """FAIL CLOSED: missing/unknown scope is not silently applicable.

    Migration 0039 backfills legacy rows with an explicit GLOBAL scope; new
    records must carry an explicit SYMBOL / REGIME / SYMBOL_REGIME scope.
    """
    if not isinstance(scope, dict):
        return False
    kind = scope.get("scope")
    if kind == "GLOBAL":
        return True
    if kind not in {"SYMBOL", "REGIME", "SYMBOL_REGIME"}:
        return False
    symbols = scope.get("symbols")
    regimes = scope.get("regimes")
    if symbols is not None and symbol not in symbols:
        return False
    if regimes is not None and regime not in regimes:
        return False
    return bool(symbols or regimes)


def _latest(rows, field: str):
    return max((getattr(row, field) for row in rows), default=None)


def _context_as_of(context: ChiefTraderContext) -> datetime:
    parsed = datetime.fromisoformat(context.prepared_at)
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)
