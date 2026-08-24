"""Daily Review scheduler: trade memory DB -> DailyReview -> daily_review_runs."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from crypto_trader.governance.daily_review import DailyReview
from crypto_trader.governance.memory import FailureMemory, TradeMemory
from crypto_trader.governance.memory_persistence import MemoryPersistence


class DailyReviewScheduler:
    def __init__(self, session_factory, review_time_utc: str = "00:05") -> None:
        self.session_factory = session_factory
        self.persistence = MemoryPersistence(session_factory)
        self.review_time_utc = review_time_utc

    async def run_once(self, date: str | None = None) -> dict:
        date = date or datetime.now(UTC).date().isoformat()
        records = await self.persistence.load_trade_memory(limit=1000)
        trade_memory = TradeMemory()
        for record in records:
            trade_memory.record(record)
        failure_memory = FailureMemory()
        for record in records:
            if record.failure_class is not None:
                failure_memory.record(record.decision_id, record.failure_class)
        stats = DailyReview(trade_memory, failure_memory).run(date)
        await self.persistence.save_daily_review(date, stats)
        return {
            "date": date,
            "daily_pnl": str(stats.daily_pnl),
            "trade_count": stats.trade_count,
            "win_rate": str(stats.win_rate),
            "profit_factor": str(stats.profit_factor),
        }

    async def loop(self) -> None:
        hour, minute = (int(part) for part in self.review_time_utc.split(":"))
        while True:
            now = datetime.now(UTC)
            next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if next_run <= now:
                next_run = next_run + __import__("datetime").timedelta(days=1)
            await asyncio.sleep((next_run - now).total_seconds())
            try:
                await self.run_once()
            except Exception:
                # idempotency: run_once saves by review_date; next loop retries safely
                continue
