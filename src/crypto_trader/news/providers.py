# ruff: noqa: E501
"""Pluggable factual News provider adapters.

No provider is a single point of semantic truth. Provider failure returns an
explicit degraded FetchResult or raises for the worker isolation layer; it
never touches the trading runtime.
"""

from __future__ import annotations

import hashlib
import json
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from crypto_trader.news.config import NewsProviderConfig
from crypto_trader.news.models import (
    ProviderHealth,
    ProviderItem,
    SourceClass,
)
from crypto_trader.news.normalization import canonicalize_url, sanitize_external_text


class ProviderFetchError(RuntimeError):
    def __init__(self, kind: ProviderHealth, message: str) -> None:
        super().__init__(message)
        self.kind = kind


@dataclass(slots=True)
class FetchResult:
    items: list[ProviderItem] = field(default_factory=list)
    cursor: str | None = None
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    health: ProviderHealth = ProviderHealth.HEALTHY
    error: str | None = None
    latency_ms: float | None = None
    rate_limit_state: dict[str, Any] = field(default_factory=dict)


class NewsProvider:
    provider_id: str = "base"
    kind: str = "BASE"

    def __init__(self, config: NewsProviderConfig, *, client: httpx.AsyncClient | None = None) -> None:
        self.config = config
        self._client = client
        self._owns_client = client is None
        self.provider_id = config.provider_id
        self.kind = config.kind
        self.last_health = ProviderHealth.HEALTHY
        self.last_error: str | None = None
        self.last_rate_limit: dict[str, Any] = {}

    async def _get(self, url: str, **kwargs) -> httpx.Response:
        if self._client is not None:
            return await self._client.get(url, **kwargs)
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            return await client.get(url, **kwargs)

    async def fetch_since(self, cursor: str | None) -> FetchResult:
        raise NotImplementedError

    async def fetch_item(self, provider_item_id: str) -> ProviderItem | None:
        return None

    def health(self) -> ProviderHealth:
        return self.last_health

    def rate_limit_state(self) -> dict[str, Any]:
        return dict(self.last_rate_limit)

    def source_metadata(self) -> dict[str, Any]:
        return {
            "provider_id": self.config.provider_id,
            "kind": self.config.kind,
            "source_name": self.config.source_name,
            "source_domain": self.config.source_domain,
            "source_type": self.config.source_type,
            "source_class": self.config.source_class.value,
        }

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None


class OKXAnnouncementsProvider(NewsProvider):
    kind = "OKX_ANNOUNCEMENTS"

    async def fetch_since(self, cursor: str | None) -> FetchResult:
        started = time.monotonic()
        try:
            response = await self._get(self.config.url, headers={"Accept": "application/json"})
        except httpx.TimeoutException as exc:
            return self._failure(ProviderHealth.NETWORK_ERROR, f"timeout: {exc}", started)
        except httpx.HTTPError as exc:
            return self._failure(ProviderHealth.NETWORK_ERROR, f"http error: {exc}", started)
        if response.status_code == 429:
            return self._failure(ProviderHealth.RATE_LIMITED, "provider rate limited", started)
        if response.status_code in {401, 403}:
            return self._failure(ProviderHealth.AUTH_ERROR, "provider auth error", started)
        if response.status_code >= 400:
            return self._failure(ProviderHealth.DEGRADED, f"http {response.status_code}", started)
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            return self._failure(ProviderHealth.PARSE_ERROR, f"invalid json: {exc}", started)
        if str(payload.get("code")) not in {"0", "None", ""}:
            return self._failure(
                ProviderHealth.DEGRADED, f"provider code {payload.get('code')}", started
            )
        items = _okx_items(payload, self.config)
        latency_ms = (time.monotonic() - started) * 1000.0
        return FetchResult(
            items=items,
            cursor=_max_published_cursor(items) or cursor,
            fetched_at=datetime.now(UTC),
            health=ProviderHealth.HEALTHY,
            latency_ms=latency_ms,
            rate_limit_state={"remaining": response.headers.get("x-ratelimit-remaining")},
        )

    def _failure(self, health: ProviderHealth, error: str, started: float) -> FetchResult:
        self.last_health = health
        self.last_error = error
        return FetchResult(
            items=[],
            cursor=None,
            fetched_at=datetime.now(UTC),
            health=health,
            error=error,
            latency_ms=(time.monotonic() - started) * 1000.0,
        )


class RSSNewsProvider(NewsProvider):
    kind = "RSS"

    async def fetch_since(self, cursor: str | None) -> FetchResult:
        started = time.monotonic()
        try:
            response = await self._get(self.config.url, headers={"Accept": "application/rss+xml, application/xml, text/xml"})
        except httpx.TimeoutException as exc:
            return self._rss_failure(ProviderHealth.NETWORK_ERROR, f"timeout: {exc}", started)
        except httpx.HTTPError as exc:
            return self._rss_failure(ProviderHealth.NETWORK_ERROR, f"http error: {exc}", started)
        if response.status_code == 429:
            return self._rss_failure(ProviderHealth.RATE_LIMITED, "provider rate limited", started)
        if response.status_code >= 400:
            return self._rss_failure(ProviderHealth.DEGRADED, f"http {response.status_code}", started)
        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as exc:
            return self._rss_failure(ProviderHealth.PARSE_ERROR, f"xml parse error: {exc}", started)
        items = _rss_items(root, response.content, self.config)
        return FetchResult(
            items=items,
            cursor=_max_published_cursor(items) or cursor,
            fetched_at=datetime.now(UTC),
            health=ProviderHealth.HEALTHY,
            latency_ms=(time.monotonic() - started) * 1000.0,
        )

    def _rss_failure(self, health: ProviderHealth, error: str, started: float) -> FetchResult:
        self.last_health = health
        self.last_error = error
        return FetchResult(
            items=[],
            cursor=None,
            fetched_at=datetime.now(UTC),
            health=health,
            error=error,
            latency_ms=(time.monotonic() - started) * 1000.0,
        )


def build_provider(config: NewsProviderConfig, *, client: httpx.AsyncClient | None = None) -> NewsProvider:
    if config.kind == "OKX_ANNOUNCEMENTS":
        return OKXAnnouncementsProvider(config, client=client)
    if config.kind == "RSS":
        return RSSNewsProvider(config, client=client)
    raise ValueError(f"unknown news provider kind: {config.kind}")


# ---------------------------------------------------------------------------
# parsing helpers
# ---------------------------------------------------------------------------


def _okx_items(payload: dict[str, Any], config: NewsProviderConfig) -> list[ProviderItem]:
    items: list[ProviderItem] = []
    blocks = payload.get("data") or []
    if not isinstance(blocks, list):
        return items
    for block in blocks:
        if not isinstance(block, dict):
            continue
        details = block.get("details") or []
        if not isinstance(details, list):
            continue
        for detail in details:
            if not isinstance(detail, dict):
                continue
            title = sanitize_external_text(detail.get("title"), max_len=2000)
            url = canonicalize_url(detail.get("url"))
            p_time_ms = _int_or_none(detail.get("pTime"))
            business_ms = _int_or_none(detail.get("businessPTime"))
            provider_timestamp = _from_epoch_ms(p_time_ms)
            published_at = _from_epoch_ms(business_ms) or provider_timestamp
            provider_item_id = url or _hash_parts(title, str(p_time_ms or ""))
            items.append(
                ProviderItem(
                    provider_id=config.provider_id,
                    provider_item_id=provider_item_id,
                    canonical_url=url,
                    source_domain=config.source_domain,
                    source_name=config.source_name,
                    source_type=config.source_type,
                    source_class=SourceClass(config.source_class),
                    title=title,
                    summary="",
                    language="en",
                    published_at=published_at,
                    provider_timestamp=provider_timestamp,
                    author="OKX",
                    raw_payload={
                        "annType": detail.get("annType"),
                        "pTime": detail.get("pTime"),
                        "businessPTime": detail.get("businessPTime"),
                        "url": detail.get("url"),
                        "title": detail.get("title"),
                    },
                    metadata={"ann_type": detail.get("annType")},
                )
            )
    return items


def _rss_items(root: ET.Element, content: bytes, config: NewsProviderConfig) -> list[ProviderItem]:
    entries: list[ET.Element] = []
    root_name = _tag(root)
    if root_name == "rss":
        channel = root.find("channel")
        if channel is not None:
            entries = [child for child in channel if _tag(child) == "item"]
    elif root_name == "feed":
        entries = [child for child in root if _tag(child) == "entry"]
    items: list[ProviderItem] = []
    for entry in entries[:200]:
        title = sanitize_external_text(_text(entry, "title"), max_len=2000)
        link = _link_from_entry(entry)
        guid = _text(entry, "guid") or _text(entry, "id") or link or _hash_parts(title, str(len(content)))
        summary = sanitize_external_text(
            _text(entry, "description") or _text(entry, "summary") or _text(entry, "content"),
            max_len=8000,
        )
        published_raw = (
            _text(entry, "pubDate") or _text(entry, "published") or _text(entry, "updated")
        )
        published_at = _parse_datetime(published_raw)
        items.append(
            ProviderItem(
                provider_id=config.provider_id,
                provider_item_id=canonicalize_url(guid) or guid,
                canonical_url=canonicalize_url(link),
                source_domain=config.source_domain,
                source_name=config.source_name,
                source_type=config.source_type,
                source_class=SourceClass(config.source_class),
                title=title,
                summary=summary,
                language="und",
                published_at=published_at,
                provider_timestamp=published_at,
                author=_text(entry, "author"),
                raw_payload={"feed_url": config.url, "guid": guid, "description": summary},
                metadata={"entry_tag": _tag(entry)},
            )
        )
    return items


def _tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1].lower()


def _text(element: ET.Element, name: str) -> str:
    for child in element:
        if _tag(child) == name:
            return " ".join(child.itertext()).strip()
    return ""


def _link_from_entry(entry: ET.Element) -> str | None:
    for child in entry:
        if _tag(child) != "link":
            continue
        href = child.attrib.get("href")
        if href:
            return href
        if child.text:
            return child.text.strip()
    return None


def _parse_datetime(raw: str | None) -> datetime | None:
    if not raw:
        return None
    text = raw.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(text)
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _from_epoch_ms(value: int | None) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(value / 1000.0, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _hash_parts(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:32]


def _max_published_cursor(items: list[ProviderItem]) -> str | None:
    published = [item.published_at for item in items if item.published_at is not None]
    if not published:
        return None
    newest = max(published)
    return json.dumps({"newest_published_at": newest.isoformat()})
