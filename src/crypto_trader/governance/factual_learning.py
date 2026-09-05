"""Offline learning derived only from factual, fully closed trade episodes."""

from __future__ import annotations

from decimal import Decimal
from hashlib import sha256

from sqlalchemy import select

from crypto_trader.governance.trade_episode import FactualTradeEpisode
from crypto_trader.persistence.models import (
    AIMarketPatternORM,
    AITradeReviewORM,
    TradeEpisodeORM,
)


class FactualEpisodeLearning:
    """Persist descriptive learning without mutating live Risk or Execution."""

    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    async def review(self, episode: FactualTradeEpisode) -> None:
        async with self.session_factory() as session:
            review = (
                await session.execute(
                    select(AITradeReviewORM).where(
                        AITradeReviewORM.episode_id == episode.episode_id
                    )
                )
            ).scalar_one_or_none()
            result = "WIN" if episode.net_pnl > 0 else "LOSS"
            if review is None:
                session.add(
                    AITradeReviewORM(
                        episode_id=episode.episode_id,
                        success_factors_json=["POSITIVE_NET_PNL"] if result == "WIN" else [],
                        failure_factors_json=["NON_POSITIVE_NET_PNL"]
                        if result == "LOSS"
                        else [],
                        mistakes_json=[],
                        lessons_json=[
                            f"FACTUAL_RESULT:{result}",
                            f"NET_PNL:{episode.net_pnl}",
                            f"MARKET_REGIME:{episode.entry_market_regime}",
                        ],
                        future_rules_json=[],
                        confidence=Decimal("1"),
                    )
                )

            rows = (
                await session.execute(
                    select(TradeEpisodeORM).where(
                        TradeEpisodeORM.factual.is_(True),
                        TradeEpisodeORM.symbol == episode.symbol,
                        TradeEpisodeORM.entry_market_regime == episode.entry_market_regime,
                        TradeEpisodeORM.direction == episode.direction,
                    )
                )
            ).scalars().all()
            wins = [row for row in rows if row.net_pnl > 0]
            gross_profit = sum((row.net_pnl for row in wins), Decimal("0"))
            gross_loss = abs(
                sum((row.net_pnl for row in rows if row.net_pnl <= 0), Decimal("0"))
            )
            profit_factor = gross_profit / gross_loss if gross_loss > 0 else gross_profit
            pattern_id = _pattern_id(
                episode.symbol, episode.entry_market_regime, episode.direction
            )
            pattern = (
                await session.execute(
                    select(AIMarketPatternORM).where(
                        AIMarketPatternORM.pattern_id == pattern_id
                    )
                )
            ).scalar_one_or_none()
            values = {
                "regime": episode.entry_market_regime,
                "strategy": episode.direction,
                "sample_count": len(rows),
                "win_rate": Decimal(len(wins)) / Decimal(len(rows)),
                "profit_factor": profit_factor,
                "success_drivers_json": ["POSITIVE_NET_PNL"] if wins else [],
                "failure_drivers_json": ["NON_POSITIVE_NET_PNL"]
                if len(wins) != len(rows)
                else [],
                "confidence": min(Decimal(len(rows)) / Decimal("20"), Decimal("1")),
            }
            if pattern is None:
                session.add(AIMarketPatternORM(pattern_id=pattern_id, **values))
            else:
                for key, value in values.items():
                    setattr(pattern, key, value)
                pattern.version += 1
            await session.commit()

    async def list_reviews(self, *, limit: int = 50) -> list[dict]:
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(AITradeReviewORM)
                    .order_by(AITradeReviewORM.created_at.desc())
                    .limit(limit)
                )
            ).scalars().all()
            return [
                {
                    "episode_id": row.episode_id,
                    "success_factors": list(row.success_factors_json or []),
                    "failure_factors": list(row.failure_factors_json or []),
                    "mistakes": list(row.mistakes_json or []),
                    "lessons": list(row.lessons_json or []),
                    "future_rules": list(row.future_rules_json or []),
                    "confidence": str(row.confidence),
                    "created_at": row.created_at.isoformat(),
                }
                for row in rows
            ]

    async def snapshot(self) -> dict:
        async with self.session_factory() as session:
            reviews = (await session.execute(select(AITradeReviewORM))).scalars().all()
            patterns = (await session.execute(select(AIMarketPatternORM))).scalars().all()
            return {
                "status": "FACTUAL_EPISODES_ONLY",
                "review_count": len(reviews),
                "pattern_count": len(patterns),
                "sample_count": sum(row.sample_count for row in patterns),
            }


def _pattern_id(symbol: str, regime: str, direction: str) -> str:
    identity = f"{symbol}|{regime}|{direction}".encode()
    return f"factual_{sha256(identity).hexdigest()[:24]}"
