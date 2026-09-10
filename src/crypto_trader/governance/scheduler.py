"""Daily Review scheduler over factual closed episodes (legacy memory optional)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from crypto_trader.governance.daily_review import DailyReview
from crypto_trader.governance.factual_learning import FactualEpisodeLearning
from crypto_trader.governance.memory import FailureMemory, TradeMemory, TradeMemoryRecord
from crypto_trader.governance.memory_persistence import MemoryPersistence
from crypto_trader.governance.trade_episode import TradeEpisodeStore


class DailyReviewScheduler:
    def __init__(
        self,
        session_factory,
        review_time_utc: str = "00:05",
        *,
        canonical_only: bool = False,
        use_local_time: bool = False,
        owner: str = "daily-review",
        claim_lease_seconds: int = 1800,
    ) -> None:
        self.session_factory = session_factory
        self.persistence = MemoryPersistence(session_factory)
        self.episodes = TradeEpisodeStore(session_factory)
        self.learning = FactualEpisodeLearning(session_factory)
        self.review_time_utc = review_time_utc
        self.canonical_only = canonical_only
        self.use_local_time = use_local_time
        self.owner = owner
        self.claim_lease_seconds = max(60, claim_lease_seconds)

    async def run_once(self, date: str | None = None) -> dict:
        now = datetime.now().astimezone() if self.use_local_time else datetime.now(UTC)
        # Review the previous complete UTC/local day when no explicit date is
        # supplied. A 00:05 scheduler call must cover [yesterday 00:00,
        # today 00:00), not the still-incomplete current day.
        date = date or (now - timedelta(days=1)).date().isoformat()
        window_start = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=UTC)
        window_end = window_start + timedelta(days=1)
        # A late factual episode may be inserted after the day already
        # SUCCEEDED. Revision is a new owned attempt; reviewed episodes are
        # still included in the day's factual statistics.
        episodes = await self.episodes.load_all_closed_on(
            date,
            timezone=now.tzinfo or UTC,
        )
        pending = [
            episode
            for episode in episodes
            if getattr(episode, "review_status", "PENDING") != "REVIEWED"
        ]
        claim_token = await self.persistence.begin_daily_review(
            date,
            window_start,
            window_end,
            owner=self.owner,
            lease_seconds=self.claim_lease_seconds,
            allow_revision=bool(pending),
        )
        if claim_token is None:
            prior = await self.persistence.get_daily_review(date) or {}
            prior["idempotent"] = True
            return prior
        try:
            records = [_episode_record(episode) for episode in episodes]
            if not self.canonical_only and not records:
                records = await self.persistence.load_trade_memory(limit=1000)
            trade_memory = TradeMemory()
            for record in records:
                trade_memory.record(record)
            failure_memory = FailureMemory()
            for record in records:
                if record.failure_class is not None:
                    failure_memory.record(record.decision_id, record.failure_class)
            stats = DailyReview(trade_memory, failure_memory).run(date)
            # Only the live claim owner may run learning/mark/publish.
            if not await self.persistence.heartbeat_daily_review(
                date,
                claim_token,
                owner=self.owner,
                lease_seconds=self.claim_lease_seconds,
            ):
                raise RuntimeError("DAILY_REVIEW_CLAIM_LOST")
            await self.learning.review_many(pending)
            # Publish SUCCEEDED only through the fenced claim update. Episode
            # mark_reviewed must happen after that fence so an old/stale token
            # can never mark factual episodes REVIEWED without a published
            # successful review.
            saved = await self.persistence.save_daily_review(
                date,
                stats,
                episode_count=len(episodes),
                output_ref=f"daily_review:{date}",
                claim_token=claim_token,
            )
            if not saved:
                raise RuntimeError("DAILY_REVIEW_CLAIM_LOST_BEFORE_MARK")
            if not await self.episodes.mark_reviewed_fenced(
                [episode.episode_id for episode in pending],
                review_date=date,
                claim_token=claim_token,
                owner=self.owner,
                lease_seconds=self.claim_lease_seconds,
            ):
                raise RuntimeError("DAILY_REVIEW_CLAIM_LOST_BEFORE_MARK")
            return {
                "date": date,
                "status": "SUCCEEDED",
                "daily_pnl": str(stats.daily_pnl),
                "trade_count": stats.trade_count,
                "win_rate": str(stats.win_rate),
                "profit_factor": str(stats.profit_factor),
                "episode_count": len(episodes),
                "reviewed_this_attempt": len(pending),
            }
        except Exception as exc:
            await self.persistence.fail_daily_review(
                date, type(exc).__name__, str(exc), claim_token=claim_token
            )
            raise


    async def run_missed_days(self, since_date: str, end_date: str | None = None) -> list[dict]:
        """Run one review per UTC day from since_date through yesterday."""
        results: list[dict] = []
        current = datetime.strptime(since_date, "%Y-%m-%d").date()
        end = (
            datetime.strptime(end_date, "%Y-%m-%d").date()
            if end_date
            else (datetime.now(UTC) - timedelta(days=1)).date()
        )
        while current <= end:
            try:
                results.append(await self.run_once(current.isoformat()))
            except Exception:
                # Preserve retryability: failures are not fatal to other dates.
                results.append({"date": current.isoformat(), "failed": True})
            current += timedelta(days=1)
        return results

    async def loop(self) -> None:
        hour, minute = (int(part) for part in self.review_time_utc.split(":"))
        while True:
            now = datetime.now().astimezone() if self.use_local_time else datetime.now(UTC)
            next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if next_run <= now:
                next_run = next_run + timedelta(days=1)
            await asyncio.sleep((next_run - now).total_seconds())
            try:
                await self.run_once()
            except Exception:
                # idempotency: run_once saves by review_date; next loop retries safely
                continue


def _episode_record(episode) -> TradeMemoryRecord:
    return TradeMemoryRecord(
        decision_id=episode.episode_id,
        symbol=episode.symbol,
        side=episode.direction,
        regime=episode.entry_market_regime,
        strategy_scores={},
        effective_weights={},
        raw_confidence=Decimal("0"),
        calibrated_confidence=Decimal("0"),
        recommended_position=episode.opened_quantity,
        approved_position=episode.opened_quantity,
        recommended_leverage=episode.leverage,
        approved_leverage=episode.leverage,
        entry=episode.entry_price,
        exit=episode.exit_price,
        fees=episode.fees,
        funding_pnl=episode.funding_pnl,
        realized_pnl=episode.gross_pnl,
        r_multiple=Decimal("0"),
        ts=episode.closed_at,
    )
