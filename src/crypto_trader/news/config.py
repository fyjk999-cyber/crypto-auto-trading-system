# ruff: noqa: E501
"""Explicit configuration for the News / External Evidence subsystem."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from crypto_trader.news.models import SourceClass


@dataclass(slots=True)
class NewsProviderConfig:
    provider_id: str
    kind: str
    url: str
    source_name: str
    source_domain: str
    source_type: str
    source_class: SourceClass
    enabled: bool = True


@dataclass(slots=True)
class NewsConfig:
    enabled: bool = False
    database_url: str = ""
    news_dir: str = "data/news"
    interval_seconds: float = 180.0
    max_items_per_cycle: int = 50
    overlap_seconds: int = 12 * 3600
    context_top_k: int = 8
    context_token_budget: int = 1400
    materiality_wake_tiers: tuple[str, ...] = ("CRITICAL", "HIGH")
    http_timeout_seconds: float = 20.0
    provider_circuit_errors: int = 5
    provider_max_backoff_seconds: float = 1800.0
    provider_backoff_base_seconds: float = 15.0
    context_include_broad: bool = True
    providers: list[NewsProviderConfig] = field(default_factory=list)

    @property
    def heartbeat_path(self) -> Path:
        return Path(self.news_dir) / "news_heartbeat.json"

    @property
    def state_path(self) -> Path:
        return Path(self.news_dir) / "news_state.json"

    @classmethod
    def from_env(cls, repo_root: str | Path | None = None) -> NewsConfig:
        root = Path(repo_root or Path.cwd()).resolve()
        news_dir = os.environ.get("NEWS_DIR", str(root / "data" / "news"))
        database_url = os.environ.get(
            "NEWS_DATABASE_URL", f"sqlite+aiosqlite:///{Path(news_dir) / 'news.db'}"
        )
        config = cls(
            enabled=_bool_env("NEWS_ENABLED", False),
            database_url=database_url,
            news_dir=news_dir,
            interval_seconds=float(os.environ.get("NEWS_POLL_INTERVAL_SECONDS", "180")),
            max_items_per_cycle=max(1, int(os.environ.get("NEWS_MAX_ITEMS_PER_CYCLE", "50"))),
            overlap_seconds=int(os.environ.get("NEWS_OVERLAP_SECONDS", str(12 * 3600))),
            context_top_k=max(1, int(os.environ.get("NEWS_CONTEXT_TOP_K", "8"))),
            context_token_budget=max(100, int(os.environ.get("NEWS_CONTEXT_TOKEN_BUDGET", "1400"))),
            http_timeout_seconds=float(os.environ.get("NEWS_HTTP_TIMEOUT_SECONDS", "20")),
            provider_circuit_errors=max(1, int(os.environ.get("NEWS_PROVIDER_CIRCUIT_ERRORS", "5"))),
            context_include_broad=_bool_env("NEWS_CONTEXT_INCLUDE_BROAD", True),
        )
        config.providers = _provider_configs(root)
        return config

    def as_observable(self) -> dict:
        return {
            "enabled": self.enabled,
            "interval_seconds": self.interval_seconds,
            "max_items_per_cycle": self.max_items_per_cycle,
            "overlap_seconds": self.overlap_seconds,
            "context_top_k": self.context_top_k,
            "context_token_budget": self.context_token_budget,
            "materiality_wake_tiers": list(self.materiality_wake_tiers),
            "provider_count": len([p for p in self.providers if p.enabled]),
        }


def _provider_configs(root: Path) -> list[NewsProviderConfig]:
    providers: list[NewsProviderConfig] = []
    if _bool_env("NEWS_OKX_ANNOUNCEMENTS_ENABLED", True):
        providers.append(
            NewsProviderConfig(
                provider_id="okx_announcements",
                kind="OKX_ANNOUNCEMENTS",
                url=os.environ.get(
                    "NEWS_OKX_ANNOUNCEMENTS_URL",
                    "https://www.okx.com/api/v5/support/announcements",
                ),
                source_name="OKX Announcements",
                source_domain="okx.com",
                source_type="OFFICIAL_ANNOUNCEMENT",
                source_class=SourceClass.EXCHANGE_OFFICIAL,
            )
        )
    feeds_raw = os.environ.get("NEWS_RSS_FEEDS")
    if feeds_raw:
        try:
            feeds = json.loads(feeds_raw)
        except json.JSONDecodeError:
            feeds = []
    else:
        feeds = [
            {
                "provider_id": "rss_cointelegraph",
                "url": "https://cointelegraph.com/rss",
                "source_name": "Cointelegraph",
                "source_domain": "cointelegraph.com",
                "source_class": "ESTABLISHED_NEWS",
            }
        ]
    for index, feed in enumerate(feeds):
        if not isinstance(feed, dict) or not feed.get("url"):
            continue
        try:
            source_class = SourceClass(str(feed.get("source_class", "ESTABLISHED_NEWS")))
        except ValueError:
            source_class = SourceClass.ESTABLISHED_NEWS
        provider_id = str(feed.get("provider_id") or f"rss_{index + 1}")
        providers.append(
            NewsProviderConfig(
                provider_id=provider_id,
                kind="RSS",
                url=str(feed["url"]),
                source_name=str(feed.get("source_name") or provider_id),
                source_domain=str(feed.get("source_domain") or provider_id),
                source_type="RSS_NEWS",
                source_class=source_class,
                enabled=bool(feed.get("enabled", True)),
            )
        )
    return providers


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}
