# ruff: noqa: E501
"""Canonical News / External Evidence tables.

Revision ID: 0041_news_external_evidence
Revises: 0040_growth_memory_versions

Backward-compatible additive migration only. News is evidence-only and these
tables are never an order, Risk or exit authority.
"""

import sqlalchemy as sa
from alembic import op

revision = "0041_news_external_evidence"
down_revision = "0040_growth_memory_versions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "news_raw_items",
        sa.Column("raw_item_id", sa.String(64), primary_key=True),
        sa.Column("provider_id", sa.String(64), nullable=False),
        sa.Column("provider_item_id", sa.String(255), nullable=False),
        sa.Column("canonical_url", sa.String(1500)),
        sa.Column("source_domain", sa.String(255), nullable=False),
        sa.Column("source_name", sa.String(255), nullable=False),
        sa.Column("source_type", sa.String(64), nullable=False),
        sa.Column("source_class", sa.String(40), nullable=False),
        sa.Column("title", sa.String(2000), nullable=False),
        sa.Column("summary_snippet", sa.String(8000), nullable=False),
        sa.Column("raw_language", sa.String(16), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("provider_timestamp", sa.DateTime(timezone=True)),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.Column("author", sa.String(255)),
        sa.Column("source_payload_hash", sa.String(64), nullable=False),
        sa.Column("normalized_text_hash", sa.String(64), nullable=False),
        sa.Column("retrieval_status", sa.String(32), nullable=False),
        sa.Column("parse_status", sa.String(32), nullable=False),
        sa.Column("source_metadata_json", sa.JSON()),
        sa.Column("raw_payload_ref", sa.String(1500)),
        sa.Column("raw_payload_json", sa.JSON()),
        sa.Column("schema_version", sa.String(32), nullable=False),
        sa.UniqueConstraint(
            "provider_id",
            "provider_item_id",
            "source_payload_hash",
            name="uq_news_raw_provider_item_hash",
        ),
    )
    for column in (
        "provider_id",
        "provider_item_id",
        "source_domain",
        "source_class",
        "published_at",
        "provider_timestamp",
        "source_payload_hash",
        "normalized_text_hash",
    ):
        op.create_index(f"ix_news_raw_items_{column}", "news_raw_items", [column])

    op.create_table(
        "news_events",
        sa.Column("event_id", sa.String(64), primary_key=True),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(48), nullable=False),
        sa.Column("canonical_title", sa.String(2000), nullable=False),
        sa.Column("factual_summary", sa.String(8000), nullable=False),
        sa.Column("earliest_published_at", sa.DateTime(timezone=True)),
        sa.Column("latest_update_at", sa.DateTime(timezone=True)),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_status", sa.String(32), nullable=False),
        sa.Column("primary_source_item_id", sa.String(64)),
        sa.Column("source_count", sa.Integer(), nullable=False),
        sa.Column("independent_source_count", sa.Integer(), nullable=False),
        sa.Column("contradiction_state", sa.String(32), nullable=False),
        sa.Column("novelty_state", sa.String(32), nullable=False),
        sa.Column("freshness_state", sa.String(32), nullable=False),
        sa.Column("materiality_score", sa.Float(), nullable=False),
        sa.Column("materiality_tier", sa.String(16), nullable=False),
        sa.Column("direction", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_json", sa.JSON()),
    )
    op.create_index("ix_news_events_event_type", "news_events", ["event_type"])
    op.create_index("ix_news_events_first_seen_at", "news_events", ["first_seen_at"])
    op.create_index("ix_news_events_primary_source_item_id", "news_events", ["primary_source_item_id"])

    op.create_table(
        "news_event_versions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String(64), nullable=False),
        sa.Column("event_version", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_type", sa.String(48), nullable=False),
        sa.Column("fact_class", sa.String(32), nullable=False),
        sa.Column("canonical_title", sa.String(2000), nullable=False),
        sa.Column("factual_summary", sa.String(8000), nullable=False),
        sa.Column("earliest_published_at", sa.DateTime(timezone=True)),
        sa.Column("latest_update_at", sa.DateTime(timezone=True)),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_status", sa.String(32), nullable=False),
        sa.Column("primary_source_item_id", sa.String(64)),
        sa.Column("entities_json", sa.JSON()),
        sa.Column("symbols_json", sa.JSON()),
        sa.Column("sectors_json", sa.JSON()),
        sa.Column("geography_json", sa.JSON()),
        sa.Column("source_count", sa.Integer(), nullable=False),
        sa.Column("independent_source_count", sa.Integer(), nullable=False),
        sa.Column("contradiction_state", sa.String(32), nullable=False),
        sa.Column("contradictions_json", sa.JSON()),
        sa.Column("novelty_state", sa.String(32), nullable=False),
        sa.Column("freshness_state", sa.String(32), nullable=False),
        sa.Column("materiality_score", sa.Float(), nullable=False),
        sa.Column("materiality_tier", sa.String(16), nullable=False),
        sa.Column("direction", sa.String(16), nullable=False),
        sa.Column("direction_score", sa.Float(), nullable=False),
        sa.Column("impact_horizon", sa.String(16), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("uncertainty_notes", sa.JSON()),
        sa.Column("correction_of_version", sa.Integer()),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("taxonomy_version", sa.String(32), nullable=False),
        sa.Column("clustering_policy_version", sa.String(32), nullable=False),
        sa.Column("materiality_policy_version", sa.String(32), nullable=False),
        sa.Column("freshness_policy_version", sa.String(32), nullable=False),
        sa.Column("payload_json", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("event_id", "event_version", name="uq_news_event_version"),
    )
    op.create_index("ix_news_event_versions_event_id", "news_event_versions", ["event_id"])
    op.create_index("ix_news_event_versions_available_at", "news_event_versions", ["available_at"])
    op.create_index("ix_news_event_versions_event_type", "news_event_versions", ["event_type"])
    op.create_index("ix_news_event_versions_expires_at", "news_event_versions", ["expires_at"])

    op.create_table(
        "news_event_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String(64), nullable=False),
        sa.Column("event_version", sa.Integer(), nullable=False),
        sa.Column("raw_item_id", sa.String(64), nullable=False),
        sa.Column("relation", sa.String(32), nullable=False),
        sa.Column("independent", sa.Boolean(), nullable=False),
        sa.Column("source_domain", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "event_id", "event_version", "raw_item_id", name="uq_news_event_item_version"
        ),
    )
    op.create_index("ix_news_event_items_event_id", "news_event_items", ["event_id"])
    op.create_index("ix_news_event_items_raw_item_id", "news_event_items", ["raw_item_id"])

    op.create_table(
        "news_entity_links",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String(64), nullable=False),
        sa.Column("event_version", sa.Integer(), nullable=False),
        sa.Column("raw_item_id", sa.String(64)),
        sa.Column("entity_id", sa.String(80), nullable=False),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("symbol", sa.String(32)),
        sa.Column("relevance_class", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("mapping_method", sa.String(32), nullable=False),
        sa.Column("ambiguous", sa.Boolean(), nullable=False),
        sa.Column("evidence_span", sa.String(512)),
        sa.Column("reason", sa.String(512), nullable=False),
        sa.Column("mapping_policy_version", sa.String(32), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "event_id",
            "event_version",
            "entity_id",
            "symbol",
            "relevance_class",
            name="uq_news_entity_link_version",
        ),
    )
    for column in ("event_id", "raw_item_id", "entity_id", "symbol", "relevance_class", "available_at"):
        op.create_index(f"ix_news_entity_links_{column}", "news_entity_links", [column])

    op.create_table(
        "news_evidence",
        sa.Column("news_evidence_id", sa.String(64), primary_key=True),
        sa.Column("event_id", sa.String(64), nullable=False),
        sa.Column("event_version", sa.Integer(), nullable=False),
        sa.Column("evidence_version", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("relevance_class", sa.String(32), nullable=False),
        sa.Column("relevance_score", sa.Float(), nullable=False),
        sa.Column("relevance_reason", sa.String(512), nullable=False),
        sa.Column("direction", sa.String(16), nullable=False),
        sa.Column("direction_score", sa.Float(), nullable=False),
        sa.Column("impact_horizon", sa.String(16), nullable=False),
        sa.Column("materiality_score", sa.Float(), nullable=False),
        sa.Column("materiality_tier", sa.String(16), nullable=False),
        sa.Column("novelty_state", sa.String(32), nullable=False),
        sa.Column("novelty_score", sa.Float(), nullable=False),
        sa.Column("source_reliability_score", sa.Float(), nullable=False),
        sa.Column("corroboration_score", sa.Float(), nullable=False),
        sa.Column("freshness_score", sa.Float(), nullable=False),
        sa.Column("contradiction_score", sa.Float(), nullable=False),
        sa.Column("contradiction_state", sa.String(32), nullable=False),
        sa.Column("data_quality", sa.String(32), nullable=False),
        sa.Column("factual_summary", sa.String(8000), nullable=False),
        sa.Column("support_points_json", sa.JSON()),
        sa.Column("counter_points_json", sa.JSON()),
        sa.Column("uncertainty_json", sa.JSON()),
        sa.Column("source_refs_json", sa.JSON()),
        sa.Column("raw_item_refs_json", sa.JSON()),
        sa.Column("trigger_eligible", sa.Boolean(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("source_policy_version", sa.String(32), nullable=False),
        sa.Column("freshness_policy_version", sa.String(32), nullable=False),
        sa.Column("materiality_policy_version", sa.String(32), nullable=False),
        sa.Column("dedup_policy_version", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "event_id",
            "event_version",
            "symbol",
            "evidence_version",
            name="uq_news_evidence_version",
        ),
    )
    for column in ("event_id", "symbol", "available_at", "first_seen_at", "expires_at"):
        op.create_index(f"ix_news_evidence_{column}", "news_evidence", [column])

    op.create_table(
        "news_provider_state",
        sa.Column("provider_id", sa.String(64), primary_key=True),
        sa.Column("cursor", sa.String(4000)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("last_item_at", sa.DateTime(timezone=True)),
        sa.Column("consecutive_errors", sa.Integer(), nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True)),
        sa.Column("checkpoint_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("last_error", sa.String(512)),
        sa.Column("last_latency_ms", sa.Float()),
        sa.Column("items_ingested", sa.Integer(), nullable=False),
        sa.Column("rate_limit_state_json", sa.JSON()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "news_source_profiles",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source_domain", sa.String(255), nullable=False),
        sa.Column("source_name", sa.String(255), nullable=False),
        sa.Column("source_class", sa.String(40), nullable=False),
        sa.Column("source_policy_version", sa.String(32), nullable=False),
        sa.Column("provenance_quality", sa.Float(), nullable=False),
        sa.Column("timestamp_quality", sa.Float(), nullable=False),
        sa.Column("correction_rate", sa.Float(), nullable=False),
        sa.Column("duplicate_rate", sa.Float(), nullable=False),
        sa.Column("corroboration_tendency", sa.Float(), nullable=False),
        sa.Column("machine_readability", sa.Float(), nullable=False),
        sa.Column("factual_error_indicator", sa.Float(), nullable=False),
        sa.Column("notes", sa.String(1000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "source_domain", "source_policy_version", name="uq_news_source_profile_version"
        ),
    )
    op.create_index("ix_news_source_profiles_source_domain", "news_source_profiles", ["source_domain"])

    op.create_table(
        "news_reassessment_events",
        sa.Column("request_id", sa.String(64), primary_key=True),
        sa.Column("event_id", sa.String(64), nullable=False),
        sa.Column("event_version", sa.Integer(), nullable=False),
        sa.Column("news_evidence_id", sa.String(64), nullable=False),
        sa.Column("symbol", sa.String(32)),
        sa.Column("dedup_key", sa.String(255), nullable=False, unique=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("priority", sa.String(16), nullable=False),
        sa.Column("materiality_tier", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(512), nullable=False),
        sa.Column("position_state", sa.String(32), nullable=False),
        sa.Column("leg_id", sa.String(64)),
        sa.Column("state_version", sa.String(128)),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(512)),
        sa.Column("context_json", sa.JSON()),
    )
    for column in ("event_id", "news_evidence_id", "symbol", "status", "leg_id", "requested_at"):
        op.create_index(f"ix_news_reassessment_events_{column}", "news_reassessment_events", [column])
    op.create_index(
        "ix_news_reassessment_events_dedup_key", "news_reassessment_events", ["dedup_key"], unique=True
    )

    op.create_table(
        "news_decision_refs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("decision_id", sa.String(64), nullable=False),
        sa.Column("news_evidence_id", sa.String(64), nullable=False),
        sa.Column("event_id", sa.String(64), nullable=False),
        sa.Column("event_version", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("ref", sa.String(160), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state_version", sa.String(128)),
        sa.Column("context_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "decision_id",
            "news_evidence_id",
            "event_version",
            name="uq_news_decision_ref_version",
        ),
    )
    for column in ("decision_id", "news_evidence_id", "event_id"):
        op.create_index(f"ix_news_decision_refs_{column}", "news_decision_refs", [column])

    op.create_table(
        "news_outcome_reviews",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("review_id", sa.String(64), nullable=False, unique=True),
        sa.Column("news_evidence_id", sa.String(64), nullable=False),
        sa.Column("event_id", sa.String(64), nullable=False),
        sa.Column("event_version", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("horizon", sa.String(16), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True)),
        sa.Column("price_return", sa.Float()),
        sa.Column("mfe", sa.Float()),
        sa.Column("mae", sa.Float()),
        sa.Column("realized_volatility", sa.Float()),
        sa.Column("rvol", sa.Float()),
        sa.Column("spread_change", sa.Float()),
        sa.Column("oi_change", sa.Float()),
        sa.Column("funding_change", sa.Float()),
        sa.Column("llm_called", sa.Boolean()),
        sa.Column("decision_id", sa.String(64)),
        sa.Column("trade_plan_id", sa.String(64)),
        sa.Column("position_existed", sa.Boolean()),
        sa.Column("post_cost_result", sa.Float()),
        sa.Column("causal_claim", sa.Boolean(), nullable=False),
        sa.Column("counterfactual_label", sa.String(32)),
        sa.Column("payload_json", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "news_evidence_id", "horizon", name="uq_news_outcome_evidence_horizon"
        ),
    )
    for column in ("news_evidence_id", "event_id", "symbol", "due_at", "status", "decision_id"):
        op.create_index(f"ix_news_outcome_reviews_{column}", "news_outcome_reviews", [column])


def downgrade() -> None:
    for table, indexes in (
        (
            "news_outcome_reviews",
            ["news_evidence_id", "event_id", "symbol", "due_at", "status", "decision_id"],
        ),
        ("news_decision_refs", ["decision_id", "news_evidence_id", "event_id"]),
        (
            "news_reassessment_events",
            ["event_id", "news_evidence_id", "symbol", "status", "leg_id", "requested_at", "dedup_key"],
        ),
        ("news_source_profiles", ["source_domain"]),
        (
            "news_evidence",
            ["event_id", "symbol", "available_at", "first_seen_at", "expires_at"],
        ),
    ):
        prefix = table
        for column in indexes:
            op.drop_index(f"ix_{prefix}_{column}", table_name=table)
        op.drop_table(table)
    op.drop_index("ix_news_entity_links_available_at", table_name="news_entity_links")
    op.drop_index("ix_news_entity_links_relevance_class", table_name="news_entity_links")
    op.drop_index("ix_news_entity_links_symbol", table_name="news_entity_links")
    op.drop_index("ix_news_entity_links_entity_id", table_name="news_entity_links")
    op.drop_index("ix_news_entity_links_raw_item_id", table_name="news_entity_links")
    op.drop_index("ix_news_entity_links_event_id", table_name="news_entity_links")
    op.drop_table("news_entity_links")
    op.drop_index("ix_news_event_items_raw_item_id", table_name="news_event_items")
    op.drop_index("ix_news_event_items_event_id", table_name="news_event_items")
    op.drop_table("news_event_items")
    op.drop_index("ix_news_event_versions_expires_at", table_name="news_event_versions")
    op.drop_index("ix_news_event_versions_event_type", table_name="news_event_versions")
    op.drop_index("ix_news_event_versions_available_at", table_name="news_event_versions")
    op.drop_index("ix_news_event_versions_event_id", table_name="news_event_versions")
    op.drop_table("news_event_versions")
    op.drop_index("ix_news_events_primary_source_item_id", table_name="news_events")
    op.drop_index("ix_news_events_first_seen_at", table_name="news_events")
    op.drop_index("ix_news_events_event_type", table_name="news_events")
    op.drop_table("news_events")
    for column in (
        "normalized_text_hash",
        "source_payload_hash",
        "provider_timestamp",
        "published_at",
        "source_class",
        "source_domain",
        "provider_item_id",
        "provider_id",
    ):
        op.drop_index(f"ix_news_raw_items_{column}", table_name="news_raw_items")
    op.drop_table("news_raw_items")
