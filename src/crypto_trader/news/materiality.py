# ruff: noqa: E501
"""Novelty, freshness, direction and materiality engines.

All policies are versioned engineering defaults. They can rank evidence and
request a wake-up, but they can never place an order or move an exit.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from crypto_trader.news.models import (
    ContradictionState,
    Direction,
    EventStatus,
    EventType,
    FreshnessState,
    ImpactHorizon,
    MaterialityTier,
    NewsEventSnapshot,
    NoveltyState,
    RelevanceClass,
)

_IMMEDIATE_EVENTS = {
    EventType.EXCHANGE_OUTAGE,
    EventType.TRADING_HALT,
    EventType.EXCHANGE_SECURITY_EVENT,
    EventType.EXPLOIT,
    EventType.SECURITY_INCIDENT,
}

_INTRADAY_EVENTS = {
    EventType.LISTING,
    EventType.DELISTING,
    EventType.LIQUIDATION_EVENT,
    EventType.PATCH_RECOVERY,
}

_STRUCTURAL_EVENTS = {
    EventType.MARKET_STRUCTURE_CHANGE,
    EventType.TOKEN_UNLOCK,
    EventType.TOKEN_BURN,
    EventType.TOKEN_EMISSION_CHANGE,
    EventType.TREASURY_ACTION,
    EventType.NETWORK_UPGRADE,
    EventType.MAINNET_LAUNCH,
    EventType.FORK,
    EventType.GOVERNANCE_PROPOSAL,
    EventType.GOVERNANCE_RESULT,
    EventType.CUSTODY_EVENT,
}

_BULLISH_EVENTS = {
    EventType.LISTING,
    EventType.MAINNET_LAUNCH,
    EventType.NETWORK_UPGRADE,
    EventType.PATCH_RECOVERY,
    EventType.GOVERNANCE_RESULT,
    EventType.TOKEN_BURN,
    EventType.TREASURY_PURCHASE,
    EventType.INSTITUTIONAL_ADOPTION,
    EventType.REGULATORY_APPROVAL,
    EventType.ETF_FLOW_EVENT,
    EventType.PARTNERSHIP,
    EventType.PRODUCT_RELEASE,
}

_BEARISH_EVENTS = {
    EventType.DELISTING,
    EventType.TRADING_HALT,
    EventType.EXCHANGE_OUTAGE,
    EventType.EXCHANGE_SECURITY_EVENT,
    EventType.EXPLOIT,
    EventType.SECURITY_INCIDENT,
    EventType.REGULATORY_REJECTION,
    EventType.ENFORCEMENT,
    EventType.INVESTIGATION,
    EventType.TOKEN_UNLOCK,
    EventType.TREASURY_SALE,
    EventType.CREDIT_EVENT,
    EventType.FX_SHOCK,
}

_HORIZON_EVENTS = {
    ImpactHorizon.IMMEDIATE: _IMMEDIATE_EVENTS,
    ImpactHorizon.INTRADAY: _INTRADAY_EVENTS,
    ImpactHorizon.STRUCTURAL: _STRUCTURAL_EVENTS,
}


def freshness_ttl_seconds(event_type: EventType) -> int:
    if event_type in _IMMEDIATE_EVENTS:
        return 6 * 3600
    if event_type in _INTRADAY_EVENTS:
        return 24 * 3600
    if event_type in _STRUCTURAL_EVENTS:
        return 14 * 86400
    if event_type in {
        EventType.REGULATORY_FILING,
        EventType.REGULATORY_APPROVAL,
        EventType.REGULATORY_REJECTION,
        EventType.COURT_RULING,
        EventType.LEGISLATION,
    }:
        return 7 * 86400
    if event_type in {EventType.RATE_DECISION, EventType.CPI, EventType.PPI, EventType.PAYROLLS, EventType.GDP}:
        return 3 * 86400
    return 24 * 3600


def compute_freshness(
    *,
    event_type: EventType,
    reference_at: datetime | None,
    first_seen_at: datetime,
    now: datetime,
) -> tuple[FreshnessState, float, datetime, str | None]:
    reference = reference_at or first_seen_at
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    ttl = freshness_ttl_seconds(event_type)
    expires_at = reference + timedelta(seconds=ttl)
    discovery_lag = first_seen_at - reference
    if discovery_lag.total_seconds() > ttl:
        return (
            FreshnessState.STALE_DISCOVERY,
            0.0,
            expires_at,
            "PUBLISHED_BEFORE_DISCOVERY_BY_MORE_THAN_TTL",
        )
    age = max(0.0, (now - reference).total_seconds())
    if age >= ttl:
        return FreshnessState.EXPIRED, 0.0, expires_at, "AGE_EXCEEDS_EVENT_TTL"
    score = max(0.0, 1.0 - (age / float(ttl)))
    state = FreshnessState.FRESH if score >= 0.5 else FreshnessState.AGING
    return state, round(score, 6), expires_at, None


def direction_for(
    *,
    event_type: EventType,
    title: str,
    summary: str = "",
    fact_class: str = "SOURCE_CLAIM",
) -> tuple[Direction, float, ImpactHorizon, list[str], list[str], list[str]]:
    lowered = f"{title or ''} {summary or ''}".lower()
    horizon = ImpactHorizon.UNKNOWN
    for candidate, event_types in _HORIZON_EVENTS.items():
        if event_type in event_types:
            horizon = candidate
            break
    if horizon == ImpactHorizon.UNKNOWN and event_type in {
        EventType.REGULATORY_FILING,
        EventType.REGULATORY_APPROVAL,
        EventType.REGULATORY_REJECTION,
        EventType.COURT_RULING,
        EventType.LEGISLATION,
        EventType.RATE_DECISION,
        EventType.CPI,
        EventType.PPI,
        EventType.PAYROLLS,
        EventType.GDP,
    }:
        horizon = ImpactHorizon.MULTIDAY

    support: list[str] = []
    counter: list[str] = []
    uncertainty = ["Headline tone is not market impact.", "Observed market reaction may contradict interpretation."]

    if event_type in _BULLISH_EVENTS:
        direction = Direction.BULLISH
        direction_score = 0.55
        if event_type == EventType.PATCH_RECOVERY and "recovery" not in lowered:
            direction = Direction.MIXED
            direction_score = 0.10
        support.append(f"event class maps to constructive outcome: {event_type.value}")
        counter.append("materiality depends on scale, corroboration and whether it is already priced")
        return direction, direction_score, horizon, support, counter, uncertainty
    if event_type in _BEARISH_EVENTS:
        direction = Direction.BEARISH
        direction_score = -0.60
        if event_type == EventType.PATCH_RECOVERY:
            direction = Direction.MIXED
            direction_score = 0.05
        support.append(f"event class maps to adverse outcome: {event_type.value}")
        counter.append("protective/deterministic exits remain higher authority than News")
        return direction, direction_score, horizon, support, counter, uncertainty
    if event_type in {EventType.CORRECTION, EventType.RETRACTION}:
        return (
            Direction.MIXED,
            0.0,
            ImpactHorizon.UNKNOWN,
            ["prior interpretation may be invalidated"],
            ["correction direction is relative to the earlier claim"],
            uncertainty,
        )
    if "bear" in lowered or "sell pressure" in lowered or "outflow" in lowered:
        return Direction.BEARISH, -0.35, horizon, ["text contains adverse market framing"], ["framing may be non-causal"], uncertainty
    if "bull" in lowered or "buy pressure" in lowered or "inflow" in lowered:
        return Direction.BULLISH, 0.35, horizon, ["text contains constructive market framing"], ["framing may be non-causal"], uncertainty
    return Direction.UNKNOWN, 0.0, horizon, [], [], uncertainty


def compute_novelty(
    *,
    existing: NewsEventSnapshot | None,
    relation: str,
    event_type: EventType,
    direction: Direction,
    title: str,
    summary: str,
    correction: bool,
    retraction: bool,
    first_seen_at: datetime,
    published_at: datetime | None,
    now: datetime,
) -> tuple[NoveltyState, float, list[str]]:
    if existing is None:
        if published_at is not None and first_seen_at - published_at > timedelta(days=7):
            return NoveltyState.STALE_DISCOVERY, 0.05, ["late discovery of an old item"]
        if correction:
            return NoveltyState.CORRECTION, 0.60, ["correction creates new event version"]
        if retraction:
            return NoveltyState.RETRACTION, 0.65, ["retraction creates new event version"]
        return NoveltyState.NEW_EVENT, 1.0, []
    if retraction:
        return NoveltyState.RETRACTION, 0.80, ["retraction is materially new information"]
    if correction:
        return NoveltyState.CORRECTION, 0.75, ["correction is materially new information"]
    if relation == "EXACT_DUPLICATE":
        return NoveltyState.DUPLICATE, 0.0, ["exact duplicate contributes no new information"]
    if relation in {"NEAR_DUPLICATE", "SYNDICATED_COPY"}:
        return NoveltyState.CORROBORATION_ONLY, 0.05, ["syndicated/reposted content is not independent new information"]
    if relation == "INDEPENDENT_CORROBORATION":
        return NoveltyState.CORROBORATION_ONLY, 0.15, ["independent source raises corroboration, not a new event"]
    structural_change = event_type != existing.event_type or direction != existing.direction
    if structural_change:
        return NoveltyState.MATERIAL_UPDATE, 0.65, ["event type or direction materially changed"]
    if _normalized_change(title, existing.canonical_title) or _normalized_change(summary, existing.factual_summary):
        return NoveltyState.MINOR_UPDATE, 0.25, ["headline/summary changed without structural change"]
    return NoveltyState.MINOR_UPDATE, 0.10, ["minor source update"]


def compute_contradiction(
    *,
    existing: NewsEventSnapshot | None,
    event_type: EventType,
    direction: Direction,
    title: str,
    summary: str,
) -> tuple[ContradictionState, float, list[dict]]:
    notes: list[dict] = []
    if existing is None:
        return ContradictionState.NONE, 0.0, notes
    if event_type == EventType.RETRACTION:
        return ContradictionState.RETRACTED, 0.90, [{"type": "RETRACTION", "from_version": existing.event_version}]
    if event_type == EventType.CORRECTION:
        return ContradictionState.CORRECTED, 0.80, [{"type": "CORRECTION", "from_version": existing.event_version}]
    opposite = {
        Direction.BULLISH: Direction.BEARISH,
        Direction.BEARISH: Direction.BULLISH,
    }.get(direction)
    if existing.direction in {Direction.BULLISH, Direction.BEARISH} and opposite == existing.direction:
        notes.append(
            {
                "type": "CONFLICT",
                "existing_direction": existing.direction.value,
                "new_direction": direction.value,
                "from_version": existing.event_version,
            }
        )
        return ContradictionState.CONFLICT, 0.75, notes
    lower = f"{title or ''} {summary or ''}".lower()
    if "denies" in lower or "denied" in lower or "not true" in lower:
        notes.append({"type": "OFFICIAL_DENIAL", "from_version": existing.event_version})
        return ContradictionState.CONFLICT, 0.65, notes
    return existing.contradiction_state, 0.0, notes


def materiality_tier(score: float) -> MaterialityTier:
    if score >= 0.82:
        return MaterialityTier.CRITICAL
    if score >= 0.62:
        return MaterialityTier.HIGH
    if score >= 0.38:
        return MaterialityTier.MEDIUM
    if score >= 0.18:
        return MaterialityTier.LOW
    return MaterialityTier.NOISE


def materiality_score(
    *,
    event_type: EventType,
    relevance_class: RelevanceClass,
    source_reliability: float,
    corroboration: float,
    novelty: NoveltyState,
    freshness_score: float,
    contradiction_score: float,
    direction_score: float,
    uncertainty_count: int,
    mapping_confidence: float,
) -> float:
    event_weight = _event_weight(event_type)
    relevance_weight = _relevance_weight(relevance_class)
    novelty_weight = {
        NoveltyState.NEW_EVENT: 0.18,
        NoveltyState.MATERIAL_UPDATE: 0.16,
        NoveltyState.CORRECTION: 0.13,
        NoveltyState.RETRACTION: 0.14,
        NoveltyState.CORROBORATION_ONLY: 0.05,
        NoveltyState.MINOR_UPDATE: 0.04,
        NoveltyState.DUPLICATE: 0.0,
        NoveltyState.STALE_DISCOVERY: 0.02,
    }.get(novelty, 0.04)
    uncertainty_penalty = min(0.18, 0.03 * max(0, uncertainty_count))
    score = (
        0.30 * event_weight
        + 0.20 * relevance_weight
        + novelty_weight
        + 0.10 * max(0.0, min(1.0, source_reliability))
        + 0.10 * max(0.0, min(1.0, corroboration))
        + 0.08 * max(0.0, min(1.0, freshness_score))
        + 0.04 * min(1.0, abs(direction_score))
        + 0.08 * max(0.0, min(1.0, mapping_confidence))
        - 0.15 * max(0.0, min(1.0, contradiction_score))
        - uncertainty_penalty
    )
    return round(max(0.0, min(1.0, score)), 6)


def trigger_eligible(
    *,
    tier: MaterialityTier,
    novelty: NoveltyState,
    freshness: FreshnessState,
    relevance_class: RelevanceClass,
    mapping_confidence: float,
) -> bool:
    if tier not in {MaterialityTier.CRITICAL, MaterialityTier.HIGH}:
        return False
    if novelty not in {
        NoveltyState.NEW_EVENT,
        NoveltyState.MATERIAL_UPDATE,
        NoveltyState.CORRECTION,
        NoveltyState.RETRACTION,
    }:
        return False
    if freshness not in {FreshnessState.FRESH, FreshnessState.AGING}:
        return False
    if relevance_class == RelevanceClass.UNKNOWN:
        return False
    return mapping_confidence >= 0.55


def event_status_for(novelty: NoveltyState, event_type: EventType) -> EventStatus:
    if novelty == NoveltyState.CORRECTION or event_type == EventType.CORRECTION:
        return EventStatus.CORRECTED
    if novelty == NoveltyState.RETRACTION or event_type == EventType.RETRACTION:
        return EventStatus.RETRACTED
    if event_type in {EventType.PATCH_RECOVERY, EventType.COURT_RULING, EventType.GOVERNANCE_RESULT}:
        return EventStatus.RESOLVED
    if event_type == EventType.EXCHANGE_OUTAGE:
        return EventStatus.OPEN
    return EventStatus.UPDATED


def _event_weight(event_type: EventType) -> float:
    if event_type in {
        EventType.EXCHANGE_OUTAGE,
        EventType.EXCHANGE_SECURITY_EVENT,
        EventType.EXPLOIT,
        EventType.SECURITY_INCIDENT,
        EventType.TRADING_HALT,
    }:
        return 1.0
    if event_type in {
        EventType.DELISTING,
        EventType.REGULATORY_REJECTION,
        EventType.ENFORCEMENT,
        EventType.INVESTIGATION,
        EventType.CREDIT_EVENT,
        EventType.FX_SHOCK,
        EventType.RATE_DECISION,
        EventType.CPI,
    }:
        return 0.80
    if event_type in {
        EventType.LISTING,
        EventType.LIQUIDATION_EVENT,
        EventType.MARKET_STRUCTURE_CHANGE,
        EventType.REGULATORY_FILING,
        EventType.REGULATORY_APPROVAL,
        EventType.COURT_RULING,
        EventType.LEGISLATION,
        EventType.ETF_FLOW_EVENT,
        EventType.TOKEN_UNLOCK,
        EventType.GDP,
        EventType.PAYROLLS,
        EventType.PPI,
    }:
        return 0.60
    if event_type == EventType.UNKNOWN:
        return 0.10
    return 0.35


def _relevance_weight(relevance_class: RelevanceClass) -> float:
    return {
        RelevanceClass.DIRECT_SYMBOL: 1.0,
        RelevanceClass.DIRECT_PROJECT: 0.85,
        RelevanceClass.EXCHANGE: 0.65,
        RelevanceClass.MARKET_STRUCTURE: 0.75,
        RelevanceClass.MACRO: 0.70,
        RelevanceClass.SECTOR: 0.45,
        RelevanceClass.PORTFOLIO: 0.60,
        RelevanceClass.UNKNOWN: 0.0,
    }.get(relevance_class, 0.0)


def _normalized_change(left: str, right: str) -> bool:
    from crypto_trader.news.normalization import normalize_for_compare

    return normalize_for_compare(left) != normalize_for_compare(right)
