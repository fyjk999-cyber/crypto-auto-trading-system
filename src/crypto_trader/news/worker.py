# ruff: noqa: E501
"""Autonomous bounded News ingestion worker.

The worker owns provider cursors, health, retry/backoff, heartbeat and bounded
backpressure. It has no order/risk/exit authority and never touches the
trading runtime, Growth service or ML services.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from crypto_trader.news.config import NewsConfig
from crypto_trader.news.models import NewsCycleMetrics, ProviderHealth, ProviderState
from crypto_trader.news.pipeline import NewsPipeline
from crypto_trader.news.providers import (
    FetchResult,
    NewsProvider,
    ProviderFetchError,
    build_provider,
)
from crypto_trader.news.repository import NewsRepository


class NewsWorker:
    name = "news_worker"

    def __init__(
        self,
        session_factory,
        config: NewsConfig,
        *,
        providers: list[NewsProvider] | None = None,
        repository: NewsRepository | None = None,
        pipeline: NewsPipeline | None = None,
        outcome_provider=None,
        clock=None,
        code_sha: str = "",
    ) -> None:
        self.config = config
        self.session_factory = session_factory
        self.repository = repository or NewsRepository(session_factory)
        self.pipeline = pipeline or NewsPipeline(self.repository, config, clock=clock)
        self.outcome_provider = outcome_provider
        self._clock = clock or (lambda: datetime.now(UTC))
        self.providers = providers or [
            build_provider(provider_config)
            for provider_config in config.providers
            if provider_config.enabled
        ]
        self.code_sha = code_sha
        self.cycles_started = 0
        self.cycles_completed = 0
        self.last_stage = "STOPPED"
        self.last_error: str | None = None
        self.last_progress_at: datetime | None = None
        self.last_metrics: dict = {}
        Path(self.config.news_dir).mkdir(parents=True, exist_ok=True)

    async def run_once(self) -> dict:
        self.cycles_started += 1
        self._set_stage("CYCLE_START")
        self.pipeline.metrics = NewsCycleMetrics()
        metrics = NewsCycleMetrics()
        provider_states: dict[str, str] = {}
        now = self._clock()
        for provider in self.providers:
            state = await self.repository.get_provider_state(provider.provider_id)
            if state is None:
                state = ProviderState(provider_id=provider.provider_id)
            if self._circuit_open(state, now):
                provider_states[provider.provider_id] = state.status.value
                metrics.provider_health[provider.provider_id] = state.status.value
                continue
            self._set_stage("PROVIDER_FETCH")
            result = await self._fetch_provider(provider, state)
            metrics.providers_polled += 1
            metrics.items_seen += len(result.items)
            if result.error:
                metrics.provider_errors += 1
                await self._record_provider_failure(provider, state, result, now)
                provider_states[provider.provider_id] = result.health.value
                metrics.provider_health[provider.provider_id] = result.health.value
                continue
            self._set_stage("PIPELINE")
            processed = 0
            ingested_before = self.pipeline.metrics.items_ingested
            for item in sorted(result.items, key=_item_priority):
                if processed >= self.config.max_items_per_cycle:
                    metrics.dropped_or_deferred += len(result.items) - processed
                    break
                try:
                    item_result = await self.pipeline.process_item(item, now=now)
                except Exception:
                    metrics.parse_errors += 1
                    continue
                processed += 1
                if item_result.skipped:
                    if item_result.relation == "EXACT_DUPLICATE":
                        metrics.duplicates_exact += 1
                    elif item_result.relation == "NEAR_DUPLICATE":
                        metrics.duplicates_near += 1
                    elif item_result.relation == "SYNDICATED_COPY":
                        metrics.duplicates_syndicated += 1
                else:
                    metrics.items_ingested += 1
                if item_result.reassessment_request_id:
                    metrics.reassessment_requests += 1
            ingested_new = self.pipeline.metrics.items_ingested - ingested_before
            await self._record_provider_success(provider, state, result, ingested_new, now)
            provider_states[provider.provider_id] = ProviderHealth.HEALTHY.value
            metrics.provider_health[provider.provider_id] = ProviderHealth.HEALTHY.value
        _merge_pipeline_metrics(metrics, self.pipeline.metrics)
        outcome_metrics = await self._run_outcome_reviews(now)
        metrics.outcome_due = int(outcome_metrics.get("due", 0) or 0)
        metrics.outcome_completed = int(outcome_metrics.get("processed", 0) or 0)
        metrics.outcome_transient = int(outcome_metrics.get("transient", 0) or 0)
        metrics.outcome_inconclusive = int(outcome_metrics.get("inconclusive", 0) or 0)
        metrics.outcome_observation_source = str(
            getattr(self.outcome_provider, "source_name", "") or ""
        )
        self.cycles_completed += 1
        self.last_progress_at = now
        self.last_error = None
        self.last_metrics = metrics.as_dict() | {"provider_state": provider_states}
        self._set_stage("CYCLE_COMPLETE")
        return self.last_metrics

    async def _run_outcome_reviews(self, now: datetime) -> dict:
        """N8.1/N9.1: bounded due-review completion after ingestion, same worker."""
        if not self.config.outcome_reviews_enabled or self.outcome_provider is None:
            return {}
        self._set_stage("OUTCOME_REVIEW")
        try:
            return await self.pipeline.outcomes.process_due(
                self.outcome_provider,
                now=now,
                limit=self.config.max_outcome_reviews_per_cycle,
            )
        except Exception as exc:
            # The queue is durable; a worker-level fault must be retried, not lost.
            return {
                "due": 0,
                "processed": 0,
                "transient": 1,
                "inconclusive": 0,
                "error": f"{type(exc).__name__}: {exc}"[:300],
            }

    async def _fetch_provider(self, provider: NewsProvider, state: ProviderState) -> FetchResult:
        try:
            return await provider.fetch_since(state.cursor)
        except ProviderFetchError as exc:
            return FetchResult(
                health=exc.kind,
                error=str(exc),
                fetched_at=self._clock(),
            )
        except Exception as exc:
            return FetchResult(
                health=ProviderHealth.NETWORK_ERROR,
                error=f"{type(exc).__name__}: {exc}"[:500],
                fetched_at=self._clock(),
            )

    async def _record_provider_failure(
        self, provider: NewsProvider, state: ProviderState, result: FetchResult, now: datetime
    ) -> None:
        state.last_attempt_at = now
        state.consecutive_errors += 1
        state.status = result.health
        state.last_error = result.error
        state.next_retry_at = now + timedelta(seconds=self._backoff_seconds(state.consecutive_errors))
        if state.status == ProviderHealth.AUTH_ERROR:
            state.next_retry_at = now + timedelta(seconds=self.config.provider_max_backoff_seconds)
        if state.consecutive_errors >= self.config.provider_circuit_errors:
            state.status = ProviderHealth.DISABLED
            state.next_retry_at = now + timedelta(seconds=self.config.provider_max_backoff_seconds)
        await self.repository.save_provider_state(state)

    async def _record_provider_success(
        self,
        provider: NewsProvider,
        state: ProviderState,
        result: FetchResult,
        processed: int,
        now: datetime,
    ) -> None:
        state.cursor = result.cursor or state.cursor
        state.last_attempt_at = now
        state.last_success_at = now
        state.consecutive_errors = 0
        state.next_retry_at = None
        state.status = ProviderHealth.HEALTHY
        state.last_error = None
        state.last_latency_ms = result.latency_ms
        state.rate_limit_state = dict(result.rate_limit_state or {})
        state.items_ingested += processed
        published = [item.published_at for item in result.items if item.published_at is not None]
        if published:
            state.last_item_at = max(published)
        await self.repository.save_provider_state(state)

    def _backoff_seconds(self, errors: int) -> float:
        return min(
            self.config.provider_max_backoff_seconds,
            self.config.provider_backoff_base_seconds * (2 ** max(0, errors - 1)),
        )

    @staticmethod
    def _circuit_open(state: ProviderState, now: datetime) -> bool:
        if state.status == ProviderHealth.DISABLED and state.next_retry_at is not None:
            return _aware(state.next_retry_at) > now
        return False

    def _set_stage(self, stage: str) -> None:
        self.last_stage = stage
        self._write_heartbeat()

    def _write_heartbeat(self) -> None:
        heartbeat = {
            "stage": self.last_stage,
            "cycles_started": self.cycles_started,
            "cycles_completed": self.cycles_completed,
            "last_progress_at": _iso(self.last_progress_at or self._clock()),
            "last_error": self.last_error,
            "runtime_sha": self.code_sha,
            "authority": "EVIDENCE_ONLY",
            "is_order": False,
            "outcome_due": int(self.last_metrics.get("outcome_due", 0) or 0),
            "outcome_completed": int(self.last_metrics.get("outcome_completed", 0) or 0),
            "outcome_transient": int(self.last_metrics.get("outcome_transient", 0) or 0),
            "outcome_inconclusive": int(
                self.last_metrics.get("outcome_inconclusive", 0) or 0
            ),
            "outcome_observation_source": str(
                self.last_metrics.get("outcome_observation_source", "") or ""
            ),
            "updated_at": _iso(self._clock()),
        }
        path = Path(self.config.heartbeat_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(heartbeat, indent=2, sort_keys=True))

    def save_state(self, *, state: str, last_error: str | None = None) -> None:
        self.last_error = last_error
        payload = {
            "state": state,
            "stage": self.last_stage,
            "cycles_started": self.cycles_started,
            "cycles_completed": self.cycles_completed,
            "last_progress_at": _iso(self.last_progress_at),
            "last_error": last_error,
            "last_metrics": self.last_metrics,
            "runtime_sha": self.code_sha,
            "authority": "EVIDENCE_ONLY",
            "is_order": False,
            "updated_at": _iso(self._clock()),
        }
        path = Path(self.config.state_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True))
        self._write_heartbeat()

    async def close(self) -> None:
        for provider in self.providers:
            await provider.close()


def _item_priority(item) -> tuple[int, float]:
    source_rank = 0 if item.source_class.value.endswith("OFFICIAL") else 1
    timestamp = item.published_at.timestamp() if item.published_at else 0.0
    return (source_rank, -timestamp)


def _merge_pipeline_metrics(metrics: NewsCycleMetrics, pipeline_metrics: NewsCycleMetrics) -> None:
    for name in (
        "items_ingested",
        "duplicates_exact",
        "duplicates_near",
        "duplicates_syndicated",
        "independent_corroborations",
        "events_created",
        "event_updates",
        "corrections",
        "retractions",
        "evidence_created",
        "material_events",
        "reassessment_requests",
        "reassessment_suppressed",
        "stale_discoveries",
        "parse_errors",
    ):
        setattr(metrics, name, getattr(pipeline_metrics, name))
    metrics.dropped_or_deferred += pipeline_metrics.dropped_or_deferred


def _aware(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _aware(value).isoformat()
