# ruff: noqa: E501
"""Versioned event taxonomy and fact/claim classification.

Unknown stays UNKNOWN. The classifier never forces a category and never
converts a source claim into a confirmed fact by itself.
"""

from __future__ import annotations

import re

from crypto_trader.news.models import EventType, FactClass, SourceClass

_OFFICIAL_FACT_SOURCES = {
    SourceClass.PRIMARY_OFFICIAL,
    SourceClass.REGULATORY_OFFICIAL,
    SourceClass.EXCHANGE_OFFICIAL,
    SourceClass.PROJECT_OFFICIAL,
    SourceClass.STRUCTURED_DATA_PROVIDER,
}

_RULES: list[tuple[EventType, tuple[str, ...]]] = [
    (EventType.DELISTING, ("delist", "remove selected", "suspend selected", "trading pair removal")),
    (EventType.LISTING, ("to list", "will list", "lists ", "new listing", "listing of")),
    (EventType.TRADING_HALT, ("trading halt", "halt trading", "suspended trading", "market halt")),
    (EventType.EXCHANGE_OUTAGE, ("outage", "service disruption", "system maintenance", "temporarily down")),
    (EventType.EXCHANGE_SECURITY_EVENT, ("unauthorized access", "security breach", "account takeover")),
    (EventType.LIQUIDATION_EVENT, ("liquidation", "auto-deleverag", " adl ")),
    (EventType.MARKET_STRUCTURE_CHANGE, ("order book consolidation", "market structure", "tick size", "fee schedule")),
    (EventType.NETWORK_UPGRADE, ("network upgrade", "protocol upgrade")),
    (EventType.MAINNET_LAUNCH, ("mainnet launch", "mainnet goes live", "mainnet is live")),
    (EventType.FORK, ("hard fork", "soft fork", "chain split", " fork")),
    (EventType.EXPLOIT, ("exploit", "hack", "drained", "stolen", "attack")),
    (EventType.SECURITY_INCIDENT, ("security incident", "vulnerabilit", "compromised", "security issue")),
    (EventType.PATCH_RECOVERY, ("patched", "recovery", "recovered", "restored", "resume", "mitigation")),
    (EventType.GOVERNANCE_PROPOSAL, ("governance proposal", "proposal", "puts to a vote")),
    (EventType.GOVERNANCE_RESULT, ("governance vote", "vote passed", "vote rejected", "governance result")),
    (EventType.TOKEN_UNLOCK, ("token unlock", "unlock", "vesting")),
    (EventType.TOKEN_BURN, ("token burn", "burn")),
    (EventType.TOKEN_EMISSION_CHANGE, ("emission", "issuance", "halving")),
    (EventType.TREASURY_ACTION, ("treasury purchase", "treasury sale", "treasury action")),
    (EventType.PARTNERSHIP, ("partnership", "partners with", "collaborat", "integrates with")),
    (EventType.PRODUCT_RELEASE, ("product release", "introduces", "launch")),
    (EventType.ROADMAP_CHANGE, ("roadmap", "delays")),
    (EventType.TEAM_EXECUTIVE_CHANGE, ("ceo", "cto", "steps down", "resign", "appointed")),
    (EventType.REGULATORY_FILING, ("regulatory filing", "filing", "registration statement")),
    (EventType.REGULATORY_APPROVAL, ("approv", "green light", "authoriz")),
    (EventType.REGULATORY_REJECTION, ("reject", "denied", "denies", "turned down")),
    (EventType.ENFORCEMENT, ("enforcement", "charges", "fines", "sues", "lawsuit", "penalty")),
    (EventType.COURT_RULING, ("court ruling", "judge", "verdict", "ruling")),
    (EventType.LEGISLATION, ("bill", "legislation", "law passed", "law signed")),
    (EventType.INVESTIGATION, ("investigat", "probe", "inquiry")),
    (EventType.ETF_FLOW_EVENT, ("etf", "fund flow", "inflow", "outflow")),
    (EventType.FUNDING_ROUND, ("funding round", "series a", "series b", "raises")),
    (EventType.TREASURY_PURCHASE, ("treasury purchase", "buys bitcoin", "purchase btc")),
    (EventType.TREASURY_SALE, ("treasury sale", "sells bitcoin", "sale btc")),
    (EventType.INSTITUTIONAL_ADOPTION, ("institutional adoption", "adds support", "now accepts", "adopt")),
    (EventType.CUSTODY_EVENT, ("custody", "custodian")),
    (EventType.RATE_DECISION, ("rate decision", "rate cut", "rate hike", "interest rate", "fomc")),
    (EventType.CPI, ("cpi", "consumer price index")),
    (EventType.PPI, ("ppi", "producer price index")),
    (EventType.PAYROLLS, ("payroll", "jobs report", "nonfarm")),
    (EventType.GDP, ("gdp", "gross domestic product")),
    (EventType.LIQUIDITY_POLICY, ("quantitative easing", "quantitative tightening", "liquidity policy")),
    (EventType.FX_SHOCK, ("currency shock", "devalu", "fx shock", "currency crisis")),
    (EventType.CREDIT_EVENT, ("default", "bankrupt", "credit event", "downgrade")),
    (EventType.RETRACTION, ("retract", "withdrew the story", "withdrawn story", "withdrawn article")),
    (EventType.CORRECTION, ("correct", "clarif", "earlier report", "updates the story")),
    (EventType.RUMOR, ("rumor", "reportedly", "sources say", "unconfirmed", "speculation")),
]


def classify_event(title: str, summary: str = "") -> EventType:
    haystack = f"{title or ''} {summary or ''}".lower()
    if not haystack.strip():
        return EventType.UNKNOWN
    for event_type, patterns in _RULES:
        if any(pattern in haystack for pattern in patterns):
            return event_type
    return EventType.UNKNOWN


def classify_fact_class(title: str, source_class: SourceClass, event_type: EventType) -> FactClass:
    if event_type == EventType.RUMOR:
        return FactClass.SOURCE_CLAIM
    if source_class in _OFFICIAL_FACT_SOURCES:
        return FactClass.FACT_CONFIRMED
    lowered = f"{title or ''}".lower()
    if "analysis" in lowered or "opinion" in lowered or "editorial" in lowered:
        return FactClass.MARKET_INTERPRETATION
    return FactClass.SOURCE_CLAIM


def is_correction(title: str, summary: str = "") -> bool:
    text = f"{title or ''} {summary or ''}".lower()
    return bool(re.search(r"\bcorrect", text) or "clarif" in text)


def is_retraction(title: str, summary: str = "") -> bool:
    text = f"{title or ''} {summary or ''}".lower()
    return "retract" in text or "withdrawn story" in text or "withdrawn article" in text
