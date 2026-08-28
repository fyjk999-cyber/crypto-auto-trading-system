"""Daily Review scheduler: trade memory DB -> DailyReview -> daily_review_runs."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime

from crypto_trader.governance.daily_review import DailyReview
from crypto_trader.governance.memory import FailureMemory, TradeMemory
from crypto_trader.governance.memory_persistence import MemoryPersistence
from crypto_trader.llm_runtime.contracts import (
    DailyReviewReasoning,
    LessonExtractionResult,
    LLMRequest,
)

logger = logging.getLogger(__name__)


class DailyLLMRetryableError(RuntimeError):
    """Semantic daily work failed; deterministic trading runtime stays available."""


class DailyReviewScheduler:
    def __init__(
        self,
        session_factory,
        review_time_utc: str = "00:05",
        llm_gateway=None,
        domain_model_runtime=None,
    ) -> None:
        self.session_factory = session_factory
        self.persistence = MemoryPersistence(session_factory)
        self.review_time_utc = review_time_utc
        self.llm_gateway = llm_gateway
        self.domain_model_runtime = domain_model_runtime

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
        # §18 exploration comparison: HIGH-CONFIDENCE (NORMAL) vs EXPLORATION
        # trade buckets from decision evidence (read-only; degrades to None).
        exploration_summary = None
        try:
            from crypto_trader.config import get_settings
            from crypto_trader.runtime.exploration_analytics import (
                exploration_status,
            )

            exploration_summary = await exploration_status(
                self.session_factory, get_settings()
            )
        except Exception as exc:  # daily review must never crash trading
            logger.warning("exploration summary unavailable: %s", exc)
        semantic_review = None
        semantic_lessons = None
        if self.llm_gateway is not None:
            evidence = {
                "date": date,
                "trade_count": stats.trade_count,
                "daily_pnl": str(stats.daily_pnl),
                "win_rate": str(stats.win_rate),
                "failure_distribution": stats.failure_distribution,
                "exploration_summary": exploration_summary,
            }
            if self.domain_model_runtime is not None:
                review_response = await self.domain_model_runtime.invoke(
                    route="daily_review",
                    context={"DecisionEvidence": evidence, "ReviewContext": {"date": date}},
                    response_model=DailyReviewReasoning,
                )
            else:
                review_response = await self.llm_gateway.invoke(
                    LLMRequest(
                        route="daily_review",
                        brain="DAILY",
                        prompt=f"Reason over immutable daily evidence: {json.dumps(evidence)}",
                        correlation_id=f"daily:{date}",
                    ),
                    DailyReviewReasoning,
                )
            if not review_response.ok:
                reason = (
                    review_response.error_code.value if review_response.error_code else "failed"
                )
                raise DailyLLMRetryableError(f"daily_review:{reason}")
            if self.domain_model_runtime is not None:
                lesson_response = await self.domain_model_runtime.invoke(
                    route="daily_lesson_extraction",
                    context={
                        "ReviewReasoning": review_response.content or {},
                        "HistoricalLessons": [],
                    },
                    response_model=LessonExtractionResult,
                )
            else:
                lesson_response = await self.llm_gateway.invoke(
                    LLMRequest(
                        route="daily_lesson_extraction",
                        brain="DAILY",
                        prompt=(
                            "Extract evidence-backed lessons from: "
                            f"{json.dumps(review_response.content)}"
                        ),
                        correlation_id=f"daily:{date}",
                    ),
                    LessonExtractionResult,
                )
            if not lesson_response.ok:
                reason = (
                    lesson_response.error_code.value if lesson_response.error_code else "failed"
                )
                raise DailyLLMRetryableError(f"daily_lesson_extraction:{reason}")
            semantic_review = review_response.content
            semantic_lessons = lesson_response.content
        await self.persistence.save_daily_review(date, stats)
        return {
            "date": date,
            "daily_pnl": str(stats.daily_pnl),
            "trade_count": stats.trade_count,
            "win_rate": str(stats.win_rate),
            "profit_factor": str(stats.profit_factor),
            "llm_review": semantic_review,
            "llm_lessons": semantic_lessons,
            "exploration_summary": exploration_summary,
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
