# ruff: noqa: E501
"""Canonical entity and symbol mapping for News events.

Explicit and versioned. Ambiguous tickers degrade and can never alone trigger
a high-confidence symbol reassessment.
"""

from __future__ import annotations

import re

from crypto_trader.news.models import (
    ENTITY_MAP_VERSION,
    EntityLink,
    EventType,
    MappingMethod,
    RelevanceClass,
)

_TOKEN_ALIASES: dict[str, tuple[str, str, str | None, RelevanceClass]] = {
    "bitcoin": ("crypto:BTC", "TOKEN", "BTCUSDT", RelevanceClass.DIRECT_SYMBOL),
    "btc": ("crypto:BTC", "TOKEN", "BTCUSDT", RelevanceClass.DIRECT_SYMBOL),
    "ethereum": ("crypto:ETH", "TOKEN", "ETHUSDT", RelevanceClass.DIRECT_SYMBOL),
    "ether": ("crypto:ETH", "TOKEN", "ETHUSDT", RelevanceClass.DIRECT_SYMBOL),
    "eth": ("crypto:ETH", "TOKEN", "ETHUSDT", RelevanceClass.DIRECT_SYMBOL),
    "solana": ("crypto:SOL", "TOKEN", "SOLUSDT", RelevanceClass.DIRECT_SYMBOL),
    "ripple": ("crypto:XRP", "TOKEN", "XRPUSDT", RelevanceClass.DIRECT_SYMBOL),
    "xrp": ("crypto:XRP", "TOKEN", "XRPUSDT", RelevanceClass.DIRECT_SYMBOL),
    "dogecoin": ("crypto:DOGE", "TOKEN", "DOGEUSDT", RelevanceClass.DIRECT_SYMBOL),
    "cardano": ("crypto:ADA", "TOKEN", "ADAUSDT", RelevanceClass.DIRECT_SYMBOL),
    "avalanche": ("crypto:AVAX", "TOKEN", "AVAXUSDT", RelevanceClass.DIRECT_SYMBOL),
    "chainlink": ("crypto:LINK", "TOKEN", "LINKUSDT", RelevanceClass.DIRECT_SYMBOL),
    "tether": ("stable:USDT", "STABLECOIN", None, RelevanceClass.PORTFOLIO),
    "usdt": ("stable:USDT", "STABLECOIN", None, RelevanceClass.PORTFOLIO),
    "usdc": ("stable:USDC", "STABLECOIN", None, RelevanceClass.PORTFOLIO),
    "okx": ("exchange:OKX", "EXCHANGE", None, RelevanceClass.EXCHANGE),
    "binance": ("exchange:BINANCE", "EXCHANGE", None, RelevanceClass.EXCHANGE),
    "coinbase": ("exchange:COINBASE", "EXCHANGE", None, RelevanceClass.EXCHANGE),
    "kraken": ("exchange:KRAKEN", "EXCHANGE", None, RelevanceClass.EXCHANGE),
    "bybit": ("exchange:BYBIT", "EXCHANGE", None, RelevanceClass.EXCHANGE),
    "sec": ("regulator:SEC", "REGULATOR", None, RelevanceClass.MARKET_STRUCTURE),
    "cftc": ("regulator:CFTC", "REGULATOR", None, RelevanceClass.MARKET_STRUCTURE),
    "federal reserve": ("regulator:FED", "REGULATOR", None, RelevanceClass.MACRO),
    "fomc": ("regulator:FED", "REGULATOR", None, RelevanceClass.MACRO),
    "etf": ("theme:ETF", "ETF_FUND", None, RelevanceClass.SECTOR),
    "defi": ("sector:DEFI", "SECTOR", None, RelevanceClass.SECTOR),
    "stablecoin": ("sector:STABLECOIN", "SECTOR", None, RelevanceClass.PORTFOLIO),
}

_SYMBOL_ALIASES: dict[str, str] = {
    "btcusdt": "BTCUSDT",
    "btcusd": "BTCUSDT",
    "ethusdt": "ETHUSDT",
    "ethusd": "ETHUSDT",
    "solusdt": "SOLUSDT",
    "xrpusdt": "XRPUSDT",
    "dogeusdt": "DOGEUSDT",
    "adausdt": "ADAUSDT",
    "avaxusdt": "AVAXUSDT",
}

_AMBIGUOUS_TICKERS = {"OP", "AR", "ONE", "MASK", "GRT", "APE", "ENS"}

_MACRO_PATTERNS = (
    "rate decision",
    "interest rate",
    "cpi",
    "ppi",
    "payroll",
    "gdp",
    "inflation",
    "quantitative easing",
    "credit event",
    "default",
)


def map_entities(
    title: str,
    summary: str = "",
    event_type: EventType = EventType.UNKNOWN,
) -> list[EntityLink]:
    text = f"{title or ''} {summary or ''}"
    lowered = text.lower()
    links: list[EntityLink] = []
    seen: set[tuple[str, str | None, RelevanceClass]] = set()

    def add(link: EntityLink) -> None:
        key = (link.entity_id, link.symbol, link.relevance_class)
        if key in seen:
            return
        seen.add(key)
        links.append(link)

    for alias, (entity_id, entity_type, symbol, relevance) in _TOKEN_ALIASES.items():
        if _alias_present(alias, lowered):
            add(
                EntityLink(
                    entity_id=entity_id,
                    entity_type=entity_type,
                    symbol=symbol,
                    relevance_class=relevance,
                    confidence=0.90 if symbol else 0.72,
                    mapping_method=MappingMethod.EXACT_ALIAS,
                    evidence_span=alias,
                    reason=f"explicit alias match: {alias}",
                    mapping_policy_version=ENTITY_MAP_VERSION,
                )
            )

    for symbol_alias, symbol in _SYMBOL_ALIASES.items():
        if _alias_present(symbol_alias, lowered):
            entity = symbol.replace("USDT", "")
            add(
                EntityLink(
                    entity_id=f"crypto:{entity}",
                    entity_type="TOKEN",
                    symbol=symbol,
                    relevance_class=RelevanceClass.DIRECT_SYMBOL,
                    confidence=0.97,
                    mapping_method=MappingMethod.SYMBOL_TOKEN,
                    evidence_span=symbol_alias,
                    reason=f"canonical pair token: {symbol_alias}",
                    mapping_policy_version=ENTITY_MAP_VERSION,
                )
            )

    for ticker in _AMBIGUOUS_TICKERS:
        if _alias_present(ticker.lower(), lowered):
            add(
                EntityLink(
                    entity_id=f"ambiguous:{ticker}",
                    entity_type="AMBIGUOUS_TICKER",
                    symbol=f"{ticker}USDT",
                    relevance_class=RelevanceClass.UNKNOWN,
                    confidence=0.30,
                    mapping_method=MappingMethod.INFERRED,
                    ambiguous=True,
                    evidence_span=ticker,
                    reason="ambiguous ticker requires disambiguation",
                    mapping_policy_version=ENTITY_MAP_VERSION,
                )
            )

    broad_relevance = None
    if any(pattern in lowered for pattern in _MACRO_PATTERNS):
        broad_relevance = RelevanceClass.MACRO
    elif event_type in {EventType.EXCHANGE_OUTAGE, EventType.TRADING_HALT}:
        broad_relevance = RelevanceClass.MARKET_STRUCTURE
    if broad_relevance is not None:
        add(
            EntityLink(
                entity_id=f"broad:{broad_relevance.value}",
                entity_type="BROAD_MARKET",
                symbol=None,
                relevance_class=broad_relevance,
                confidence=0.70,
                mapping_method=MappingMethod.TAXONOMY_BROAD,
                evidence_span=str(event_type),
                reason="broad relevance inferred from event taxonomy",
                mapping_policy_version=ENTITY_MAP_VERSION,
            )
        )

    if not links:
        add(
            EntityLink(
                entity_id="unmapped:UNKNOWN",
                entity_type="UNKNOWN",
                symbol=None,
                relevance_class=RelevanceClass.UNKNOWN,
                confidence=0.0,
                mapping_method=MappingMethod.UNMAPPED,
                reason="no canonical entity alias matched",
                mapping_policy_version=ENTITY_MAP_VERSION,
            )
        )
    return links


def direct_symbol_links(links: list[EntityLink]) -> list[EntityLink]:
    return [
        link
        for link in links
        if link.symbol
        and link.relevance_class == RelevanceClass.DIRECT_SYMBOL
        and not link.ambiguous
        and link.confidence >= 0.55
    ]


def _alias_present(alias: str, lowered_text: str) -> bool:
    if " " in alias:
        return alias in lowered_text
    tokens = set(re.findall(r"[a-z0-9]+", lowered_text))
    return alias in tokens
