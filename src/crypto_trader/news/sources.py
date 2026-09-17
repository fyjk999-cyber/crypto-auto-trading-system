# ruff: noqa: E501
"""Versioned source reliability profiles (metadata, never truth)."""

from __future__ import annotations

from crypto_trader.news.models import SOURCE_POLICY_VERSION, SourceClass, SourceProfile

_DOMAIN_CLASSES: dict[str, SourceClass] = {
    "okx.com": SourceClass.EXCHANGE_OFFICIAL,
    "binance.com": SourceClass.EXCHANGE_OFFICIAL,
    "coinbase.com": SourceClass.EXCHANGE_OFFICIAL,
    "kraken.com": SourceClass.EXCHANGE_OFFICIAL,
    "bybit.com": SourceClass.EXCHANGE_OFFICIAL,
    "sec.gov": SourceClass.REGULATORY_OFFICIAL,
    "federalreserve.gov": SourceClass.REGULATORY_OFFICIAL,
    "cointelegraph.com": SourceClass.ESTABLISHED_NEWS,
    "coindesk.com": SourceClass.ESTABLISHED_NEWS,
    "theblock.co": SourceClass.ESTABLISHED_NEWS,
    "reuters.com": SourceClass.ESTABLISHED_NEWS,
    "bloomberg.com": SourceClass.ESTABLISHED_NEWS,
}


def source_class_for(
    source_domain: str, source_name: str = "", explicit: SourceClass | None = None
) -> SourceClass:
    if explicit is not None:
        return explicit
    domain = (source_domain or "").lower()
    for known, source_class in _DOMAIN_CLASSES.items():
        if domain == known or domain.endswith("." + known):
            return source_class
    lowered_name = (source_name or "").lower()
    if "official" in lowered_name:
        return SourceClass.PROJECT_OFFICIAL
    if not domain:
        return SourceClass.UNKNOWN
    return SourceClass.SECONDARY_MEDIA


def default_profile(
    *,
    source_domain: str,
    source_name: str,
    source_class: SourceClass,
) -> SourceProfile:
    quality = {
        SourceClass.PRIMARY_OFFICIAL: 0.98,
        SourceClass.REGULATORY_OFFICIAL: 0.97,
        SourceClass.EXCHANGE_OFFICIAL: 0.96,
        SourceClass.PROJECT_OFFICIAL: 0.90,
        SourceClass.STRUCTURED_DATA_PROVIDER: 0.92,
        SourceClass.ESTABLISHED_NEWS: 0.78,
        SourceClass.SECONDARY_MEDIA: 0.55,
        SourceClass.SOCIAL_OFFICIAL: 0.70,
        SourceClass.SOCIAL_UNVERIFIED: 0.30,
        SourceClass.UNKNOWN: 0.25,
    }.get(source_class, 0.25)
    timestamp_quality = {
        SourceClass.PRIMARY_OFFICIAL: 0.95,
        SourceClass.REGULATORY_OFFICIAL: 0.95,
        SourceClass.EXCHANGE_OFFICIAL: 0.95,
        SourceClass.PROJECT_OFFICIAL: 0.85,
        SourceClass.STRUCTURED_DATA_PROVIDER: 0.95,
        SourceClass.ESTABLISHED_NEWS: 0.80,
        SourceClass.SECONDARY_MEDIA: 0.60,
        SourceClass.SOCIAL_OFFICIAL: 0.55,
        SourceClass.SOCIAL_UNVERIFIED: 0.30,
        SourceClass.UNKNOWN: 0.20,
    }.get(source_class, 0.20)
    return SourceProfile(
        source_domain=source_domain,
        source_name=source_name,
        source_class=source_class,
        source_policy_version=SOURCE_POLICY_VERSION,
        provenance_quality=quality,
        timestamp_quality=timestamp_quality,
        correction_rate=0.05 if source_class in {SourceClass.ESTABLISHED_NEWS, SourceClass.SECONDARY_MEDIA} else 0.01,
        duplicate_rate=0.30 if source_class in {SourceClass.ESTABLISHED_NEWS, SourceClass.SECONDARY_MEDIA} else 0.05,
        corroboration_tendency=0.85 if source_class in {SourceClass.EXCHANGE_OFFICIAL, SourceClass.REGULATORY_OFFICIAL} else 0.50,
        machine_readability=0.95 if source_class in {SourceClass.STRUCTURED_DATA_PROVIDER, SourceClass.EXCHANGE_OFFICIAL} else 0.70,
        factual_error_indicator=0.20 if source_class in {SourceClass.SOCIAL_UNVERIFIED, SourceClass.UNKNOWN} else 0.05,
        notes="engineering default profile; not a truth score",
    )
