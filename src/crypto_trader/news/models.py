"""Canonical News domain objects (frozen News 31).

News is EVIDENCE ONLY. None of these objects can place an order, move a Base
Exit, or change Risk/Execution authority. A News trigger is a wake-up only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

# ---------------------------------------------------------------------------
# Versioned policy identifiers. These are persisted on every derived row so an
# as-of replay can name the exact policy that produced an evidence snapshot.
# ---------------------------------------------------------------------------
SOURCE_POLICY_VERSION = "news.source.v1"
TAXONOMY_VERSION = "news.taxonomy.v1"
DEDUP_POLICY_VERSION = "news.dedup.v1"
CLUSTERING_POLICY_VERSION = "news.cluster.v1"
MATERIALITY_POLICY_VERSION = "news.materiality.v1"
FRESHNESS_POLICY_VERSION = "news.freshness.v1"
ENTITY_MAP_VERSION = "news.entity.v1"
EVIDENCE_SCHEMA_VERSION = "news.evidence.v1"
CLUSTERING_OVERLAP_SECONDS = 12 * 3600
PROVIDER_BACKOFF_BASE_SECONDS = 15.0
PROVIDER_MAX_BACKOFF_SECONDS = 1800.0
PROVIDER_CIRCUIT_ERRORS = 5
BROAD_SYMBOL = "UNIVERSE"


class SourceClass(StrEnum):
    PRIMARY_OFFICIAL = "PRIMARY_OFFICIAL"
    REGULATORY_OFFICIAL = "REGULATORY_OFFICIAL"
    EXCHANGE_OFFICIAL = "EXCHANGE_OFFICIAL"
    PROJECT_OFFICIAL = "PROJECT_OFFICIAL"
    STRUCTURED_DATA_PROVIDER = "STRUCTURED_DATA_PROVIDER"
    ESTABLISHED_NEWS = "ESTABLISHED_NEWS"
    SECONDARY_MEDIA = "SECONDARY_MEDIA"
    SOCIAL_OFFICIAL = "SOCIAL_OFFICIAL"
    SOCIAL_UNVERIFIED = "SOCIAL_UNVERIFIED"
    UNKNOWN = "UNKNOWN"


class ProviderHealth(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    RATE_LIMITED = "RATE_LIMITED"
    AUTH_ERROR = "AUTH_ERROR"
    NETWORK_ERROR = "NETWORK_ERROR"
    PARSE_ERROR = "PARSE_ERROR"
    DISABLED = "DISABLED"
    STALE = "STALE"


class AggregateHealth(StrEnum):
    HEALTHY = "HEALTHY"
    PARTIAL_NEWS_AVAILABLE = "PARTIAL_NEWS_AVAILABLE"
    NO_NEWS_AVAILABLE = "NO_NEWS_AVAILABLE"


class FactClass(StrEnum):
    FACT_CONFIRMED = "FACT_CONFIRMED"
    SOURCE_CLAIM = "SOURCE_CLAIM"
    MARKET_INTERPRETATION = "MARKET_INTERPRETATION"
    SYSTEM_INFERENCE = "SYSTEM_INFERENCE"


class Direction(StrEnum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    MIXED = "MIXED"
    NEUTRAL = "NEUTRAL"
    UNKNOWN = "UNKNOWN"


class ImpactHorizon(StrEnum):
    IMMEDIATE = "IMMEDIATE"
    INTRADAY = "INTRADAY"
    MULTIDAY = "MULTIDAY"
    STRUCTURAL = "STRUCTURAL"
    UNKNOWN = "UNKNOWN"


class EventStatus(StrEnum):
    OPEN = "OPEN"
    UPDATED = "UPDATED"
    RECOVERING = "RECOVERING"
    RESOLVED = "RESOLVED"
    CORRECTED = "CORRECTED"
    RETRACTED = "RETRACTED"
    CLOSED = "CLOSED"


class NoveltyState(StrEnum):
    NEW_EVENT = "NEW_EVENT"
    MATERIAL_UPDATE = "MATERIAL_UPDATE"
    MINOR_UPDATE = "MINOR_UPDATE"
    CORROBORATION_ONLY = "CORROBORATION_ONLY"
    DUPLICATE = "DUPLICATE"
    RETRACTION = "RETRACTION"
    CORRECTION = "CORRECTION"
    STALE_DISCOVERY = "STALE_DISCOVERY"


class FreshnessState(StrEnum):
    FRESH = "FRESH"
    AGING = "AGING"
    EXPIRED = "EXPIRED"
    STALE_DISCOVERY = "STALE_DISCOVERY"


class ContradictionState(StrEnum):
    NONE = "NONE"
    CONFLICT = "CONFLICT"
    CORRECTED = "CORRECTED"
    RETRACTED = "RETRACTED"
    RESOLVED = "RESOLVED"


class RelevanceClass(StrEnum):
    DIRECT_SYMBOL = "DIRECT_SYMBOL"
    DIRECT_PROJECT = "DIRECT_PROJECT"
    SECTOR = "SECTOR"
    EXCHANGE = "EXCHANGE"
    MARKET_STRUCTURE = "MARKET_STRUCTURE"
    MACRO = "MACRO"
    PORTFOLIO = "PORTFOLIO"
    UNKNOWN = "UNKNOWN"


class MaterialityTier(StrEnum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    NOISE = "NOISE"


class MappingMethod(StrEnum):
    EXACT_ALIAS = "EXACT_ALIAS"
    SYMBOL_TOKEN = "SYMBOL_TOKEN"
    ENTITY_ALIAS = "ENTITY_ALIAS"
    TAXONOMY_BROAD = "TAXONOMY_BROAD"
    MANUAL = "MANUAL"
    INFERRED = "INFERRED"
    UNMAPPED = "UNMAPPED"


class DuplicateRelation(StrEnum):
    EXACT_DUPLICATE = "EXACT_DUPLICATE"
    NEAR_DUPLICATE = "NEAR_DUPLICATE"
    SYNDICATED_COPY = "SYNDICATED_COPY"
    SOURCE_UPDATE = "SOURCE_UPDATE"
    INDEPENDENT_CORROBORATION = "INDEPENDENT_CORROBORATION"
    RELATED_DISTINCT_EVENT = "RELATED_DISTINCT_EVENT"


class ReassessmentStatus(StrEnum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    SUPPRESSED = "SUPPRESSED"
    STALE = "STALE"
    FAILED = "FAILED"
    SKIPPED_FLAT = "SKIPPED_FLAT"


class EventType(StrEnum):
    LISTING = "LISTING"
    DELISTING = "DELISTING"
    TRADING_HALT = "TRADING_HALT"
    EXCHANGE_OUTAGE = "EXCHANGE_OUTAGE"
    EXCHANGE_SECURITY_EVENT = "EXCHANGE_SECURITY_EVENT"
    LIQUIDATION_EVENT = "LIQUIDATION_EVENT"
    MARKET_STRUCTURE_CHANGE = "MARKET_STRUCTURE_CHANGE"
    NETWORK_UPGRADE = "NETWORK_UPGRADE"
    MAINNET_LAUNCH = "MAINNET_LAUNCH"
    FORK = "FORK"
    EXPLOIT = "EXPLOIT"
    SECURITY_INCIDENT = "SECURITY_INCIDENT"
    PATCH_RECOVERY = "PATCH_RECOVERY"
    GOVERNANCE_PROPOSAL = "GOVERNANCE_PROPOSAL"
    GOVERNANCE_RESULT = "GOVERNANCE_RESULT"
    TOKEN_UNLOCK = "TOKEN_UNLOCK"
    TOKEN_BURN = "TOKEN_BURN"
    TOKEN_EMISSION_CHANGE = "TOKEN_EMISSION_CHANGE"
    TREASURY_ACTION = "TREASURY_ACTION"
    PARTNERSHIP = "PARTNERSHIP"
    PRODUCT_RELEASE = "PRODUCT_RELEASE"
    ROADMAP_CHANGE = "ROADMAP_CHANGE"
    TEAM_EXECUTIVE_CHANGE = "TEAM_EXECUTIVE_CHANGE"
    REGULATORY_FILING = "REGULATORY_FILING"
    REGULATORY_APPROVAL = "REGULATORY_APPROVAL"
    REGULATORY_REJECTION = "REGULATORY_REJECTION"
    ENFORCEMENT = "ENFORCEMENT"
    COURT_RULING = "COURT_RULING"
    LEGISLATION = "LEGISLATION"
    INVESTIGATION = "INVESTIGATION"
    ETF_FLOW_EVENT = "ETF_FLOW_EVENT"
    FUNDING_ROUND = "FUNDING_ROUND"
    TREASURY_PURCHASE = "TREASURY_PURCHASE"
    TREASURY_SALE = "TREASURY_SALE"
    INSTITUTIONAL_ADOPTION = "INSTITUTIONAL_ADOPTION"
    CUSTODY_EVENT = "CUSTODY_EVENT"
    RATE_DECISION = "RATE_DECISION"
    CPI = "CPI"
    PPI = "PPI"
    PAYROLLS = "PAYROLLS"
    GDP = "GDP"
    LIQUIDITY_POLICY = "LIQUIDITY_POLICY"
    FX_SHOCK = "FX_SHOCK"
    CREDIT_EVENT = "CREDIT_EVENT"
    RUMOR = "RUMOR"
    CORRECTION = "CORRECTION"
    RETRACTION = "RETRACTION"
    UNKNOWN = "UNKNOWN"


@dataclass(slots=True)
class ProviderItem:
    provider_id: str
    provider_item_id: str
    canonical_url: str | None
    source_domain: str
    source_name: str
    source_type: str
    source_class: SourceClass
    title: str
    summary: str = ""
    language: str = "und"
    published_at: datetime | None = None
    provider_timestamp: datetime | None = None
    updated_at: datetime | None = None
    author: str | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RawNewsItem:
    raw_item_id: str
    provider_id: str
    provider_item_id: str
    canonical_url: str | None
    source_domain: str
    source_name: str
    source_type: str
    source_class: SourceClass
    title: str
    summary_snippet: str
    raw_language: str
    published_at: datetime | None
    provider_timestamp: datetime | None
    first_seen_at: datetime
    ingested_at: datetime
    updated_at: datetime | None
    author: str | None
    source_payload_hash: str
    normalized_text_hash: str
    normalized_text: str
    retrieval_status: str
    parse_status: str
    schema_version: str = EVIDENCE_SCHEMA_VERSION
    source_metadata: dict[str, Any] = field(default_factory=dict)
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class EntityLink:
    entity_id: str
    entity_type: str
    symbol: str | None
    relevance_class: RelevanceClass
    confidence: float
    mapping_method: MappingMethod
    ambiguous: bool = False
    evidence_span: str = ""
    reason: str = ""
    mapping_policy_version: str = ENTITY_MAP_VERSION


@dataclass(slots=True)
class NewsEventSnapshot:
    event_id: str
    event_version: int
    available_at: datetime
    event_type: EventType
    fact_class: FactClass
    canonical_title: str
    factual_summary: str
    earliest_published_at: datetime | None
    latest_update_at: datetime | None
    first_seen_at: datetime
    event_status: EventStatus
    primary_source_item_id: str | None
    entities: list[str] = field(default_factory=list)
    symbols: list[str] = field(default_factory=list)
    sectors: list[str] = field(default_factory=list)
    geography: list[str] = field(default_factory=list)
    source_count: int = 0
    independent_source_count: int = 0
    contradiction_state: ContradictionState = ContradictionState.NONE
    contradictions: list[dict[str, Any]] = field(default_factory=list)
    novelty_state: NoveltyState = NoveltyState.NEW_EVENT
    freshness_state: FreshnessState = FreshnessState.FRESH
    materiality_score: float = 0.0
    materiality_tier: MaterialityTier = MaterialityTier.NOISE
    direction: Direction = Direction.UNKNOWN
    direction_score: float = 0.0
    impact_horizon: ImpactHorizon = ImpactHorizon.UNKNOWN
    confidence: float = 0.0
    uncertainty_notes: list[str] = field(default_factory=list)
    correction_of_version: int | None = None
    expires_at: datetime | None = None
    taxonomy_version: str = TAXONOMY_VERSION
    clustering_policy_version: str = CLUSTERING_POLICY_VERSION
    materiality_policy_version: str = MATERIALITY_POLICY_VERSION
    freshness_policy_version: str = FRESHNESS_POLICY_VERSION
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SourceProfile:
    source_domain: str
    source_name: str
    source_class: SourceClass
    source_policy_version: str = SOURCE_POLICY_VERSION
    provenance_quality: float = 0.5
    timestamp_quality: float = 0.5
    correction_rate: float = 0.0
    duplicate_rate: float = 0.0
    corroboration_tendency: float = 0.5
    machine_readability: float = 0.5
    factual_error_indicator: float = 0.0
    notes: str = ""

    @property
    def reliability_score(self) -> float:
        score = (
            0.30 * self.provenance_quality
            + 0.20 * self.timestamp_quality
            + 0.10 * max(0.0, 1.0 - self.correction_rate)
            + 0.10 * max(0.0, 1.0 - self.duplicate_rate)
            + 0.15 * self.corroboration_tendency
            + 0.10 * self.machine_readability
            + 0.05 * max(0.0, 1.0 - self.factual_error_indicator)
        )
        return max(0.0, min(1.0, score))


@dataclass(slots=True)
class NewsEvidence:
    news_evidence_id: str
    event_id: str
    event_version: int
    evidence_version: int
    symbol: str
    relevance_class: RelevanceClass
    relevance_score: float
    relevance_reason: str
    direction: Direction
    direction_score: float
    impact_horizon: ImpactHorizon
    materiality_score: float
    materiality_tier: MaterialityTier
    novelty_state: NoveltyState
    novelty_score: float
    source_reliability_score: float
    corroboration_score: float
    freshness_score: float
    contradiction_score: float
    contradiction_state: ContradictionState
    data_quality: str
    factual_summary: str
    support_points: list[str] = field(default_factory=list)
    counter_points: list[str] = field(default_factory=list)
    uncertainty: list[str] = field(default_factory=list)
    source_refs: list[dict[str, Any]] = field(default_factory=list)
    raw_item_refs: list[str] = field(default_factory=list)
    trigger_eligible: bool = False
    available_at: datetime | None = None
    first_seen_at: datetime | None = None
    expires_at: datetime | None = None
    source_policy_version: str = SOURCE_POLICY_VERSION
    freshness_policy_version: str = FRESHNESS_POLICY_VERSION
    materiality_policy_version: str = MATERIALITY_POLICY_VERSION
    dedup_policy_version: str = DEDUP_POLICY_VERSION


@dataclass(slots=True)
class ProviderState:
    provider_id: str
    cursor: str | None = None
    last_success_at: datetime | None = None
    last_attempt_at: datetime | None = None
    last_item_at: datetime | None = None
    consecutive_errors: int = 0
    next_retry_at: datetime | None = None
    checkpoint_version: int = 1
    status: ProviderHealth = ProviderHealth.HEALTHY
    last_error: str | None = None
    last_latency_ms: float | None = None
    items_ingested: int = 0
    rate_limit_state: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class NewsReassessmentRequest:
    request_id: str
    event_id: str
    event_version: int
    news_evidence_id: str
    symbol: str | None
    dedup_key: str
    priority: str
    materiality_tier: MaterialityTier
    reason: str
    position_state: str
    requested_at: datetime
    status: ReassessmentStatus = ReassessmentStatus.PENDING
    leg_id: str | None = None
    state_version: str | None = None
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class NewsOutcomeReview:
    review_id: str
    news_evidence_id: str
    event_id: str
    event_version: int
    symbol: str
    horizon: str
    due_at: datetime
    status: str = "PENDING"
    observed_at: datetime | None = None
    price_return: float | None = None
    mfe: float | None = None
    mae: float | None = None
    realized_volatility: float | None = None
    rvol: float | None = None
    spread_change: float | None = None
    oi_change: float | None = None
    funding_change: float | None = None
    llm_called: bool | None = None
    decision_id: str | None = None
    trade_plan_id: str | None = None
    position_existed: bool | None = None
    post_cost_result: float | None = None
    causal_claim: bool = False
    counterfactual_label: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class NewsCycleMetrics:
    providers_polled: int = 0
    provider_errors: int = 0
    items_seen: int = 0
    items_ingested: int = 0
    duplicates_exact: int = 0
    duplicates_near: int = 0
    duplicates_syndicated: int = 0
    independent_corroborations: int = 0
    events_created: int = 0
    event_updates: int = 0
    corrections: int = 0
    retractions: int = 0
    evidence_created: int = 0
    material_events: int = 0
    reassessment_requests: int = 0
    reassessment_suppressed: int = 0
    stale_discoveries: int = 0
    parse_errors: int = 0
    dropped_or_deferred: int = 0
    provider_health: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        data = {
            field_name: getattr(self, field_name)
            for field_name in self.__dataclass_fields__
            if field_name != "provider_health"
        }
        data["provider_health"] = dict(self.provider_health)
        return data
