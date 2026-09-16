"""Read-only News observability status (no mutation endpoint)."""

from __future__ import annotations

import json
from pathlib import Path

from crypto_trader.news.config import NewsConfig
from crypto_trader.news.models import AggregateHealth, ProviderHealth
from crypto_trader.news.repository import NewsRepository


async def news_status(
    session_factory,
    *,
    news_dir: str | None = None,
    config: NewsConfig | None = None,
) -> dict:
    repository = NewsRepository(session_factory)
    raw_items = await repository.raw_item_count()
    event_counts = await repository.event_counts()
    evidence_count = await repository.evidence_count()
    provider_rows = await repository.provider_status_rows()
    reassessment_counts = await repository.reassessment_counts()
    outcome_counts = await repository.outcome_counts()
    last_ingest = await repository.latest_raw_ingest_at()
    pending_reassessments = int(
        reassessment_counts.get("PENDING", reassessment_counts.get("pending", 0)) or 0
    )
    last_error = next(
        (row.get("last_error") for row in provider_rows if row.get("last_error")), None
    )
    health = _aggregate_health(provider_rows, event_counts["events"])
    heartbeat = _read_json(Path(news_dir) / "news_heartbeat.json") if news_dir else {}
    state = _read_json(Path(news_dir) / "news_state.json") if news_dir else {}
    return {
        "service": {
            "state": state.get("state", "UNKNOWN"),
            "stage": heartbeat.get("stage") or state.get("stage"),
            "cycles_started": heartbeat.get("cycles_started", state.get("cycles_started", 0)),
            "cycles_completed": heartbeat.get("cycles_completed", state.get("cycles_completed", 0)),
            "last_progress_at": heartbeat.get("last_progress_at") or state.get("last_progress_at"),
            "last_error": heartbeat.get("last_error") or state.get("last_error") or last_error,
            "runtime_sha": heartbeat.get("runtime_sha") or state.get("runtime_sha") or "unknown",
            "authority": "EVIDENCE_ONLY",
            "is_order": False,
        },
        "health": health.value,
        "providers": provider_rows,
        "provider_count": len(provider_rows),
        "healthy_provider_count": sum(
            1 for row in provider_rows if row.get("status") == ProviderHealth.HEALTHY.value
        ),
        "last_ingest_at": last_ingest.isoformat() if last_ingest else None,
        "raw_items": raw_items,
        "events": event_counts["events"],
        "active_events": event_counts["active_events"],
        "material_events": event_counts["material_events"],
        "evidence": evidence_count,
        "queue_depth": pending_reassessments,
        "reassessments": reassessment_counts,
        "outcomes": outcome_counts,
        "configuration": (config or NewsConfig()).as_observable(),
        "last_error": last_error,
    }


def _aggregate_health(provider_rows: list[dict], event_count: int) -> AggregateHealth:
    if not provider_rows:
        return AggregateHealth.NO_NEWS_AVAILABLE
    statuses = [str(row.get("status") or "") for row in provider_rows]
    healthy = [status for status in statuses if status == ProviderHealth.HEALTHY.value]
    if healthy and len(healthy) == len(statuses):
        return AggregateHealth.HEALTHY
    if healthy or event_count > 0:
        return AggregateHealth.PARTIAL_NEWS_AVAILABLE
    return AggregateHealth.NO_NEWS_AVAILABLE


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text()) if path.exists() else {}
    except (OSError, json.JSONDecodeError):
        return {}
