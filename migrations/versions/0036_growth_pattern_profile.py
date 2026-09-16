"""Pattern identity, coin profile and compressed experience extensions.

Revision ID: 0036_growth_pattern_profile
Revises: 0035_growth_event_reviews
"""

import sqlalchemy as sa
from alembic import op

revision = "0036_growth_pattern_profile"
down_revision = "0035_growth_event_reviews"
branch_labels = None
depends_on = None


PATTERN_COLUMNS = (
    ("pattern_key", sa.String(64)),
    ("asset", sa.String(32)),
    ("horizon", sa.String(8)),
    ("wins", sa.Integer()),
    ("losses", sa.Integer()),
    ("setup_signature", sa.String(64)),
    ("direction", sa.String(8)),
    ("post_cost_expectancy_bps", sa.Float()),
    ("mean_mfe_bps", sa.Float()),
    ("mean_mae_bps", sa.Float()),
    ("contradiction_count", sa.Integer()),
    ("sample_tier", sa.String(32)),
    ("memory_speed", sa.String(32)),
    ("quality", sa.Float()),
    ("source_refs_json", sa.JSON()),
    ("updated_at", sa.DateTime(timezone=True)),
)
PROFILE_COLUMNS = (
    ("post_cost_expectancy_bps", sa.Float()),
    ("sample_tier", sa.String(32)),
    ("quality_confidence", sa.Float()),
    ("first_sample_at", sa.DateTime(timezone=True)),
    ("last_sample_at", sa.DateTime(timezone=True)),
    ("extended_json", sa.JSON()),
)
COMPRESSION_COLUMNS = (
    ("source_pattern_ids_json", sa.JSON()),
    ("sample_tier", sa.String(32)),
    ("regime_coverage", sa.Integer()),
    ("post_cost_expectancy_bps", sa.Float()),
    ("stability", sa.Float()),
    ("contradictions", sa.Integer()),
    ("policy_version", sa.String(32)),
    ("updated_at", sa.DateTime(timezone=True)),
)


def upgrade() -> None:
    for name, column_type in PATTERN_COLUMNS:
        op.add_column("ai_market_patterns", sa.Column(name, column_type))
    op.create_index("ix_ai_market_patterns_pattern_key", "ai_market_patterns", ["pattern_key"])
    for name, column_type in PROFILE_COLUMNS:
        op.add_column("ai_coin_profiles", sa.Column(name, column_type))
    for name, column_type in COMPRESSION_COLUMNS:
        op.add_column("ai_compressed_experience", sa.Column(name, column_type))


def downgrade() -> None:
    for name, _ in reversed(COMPRESSION_COLUMNS):
        op.drop_column("ai_compressed_experience", name)
    for name, _ in reversed(PROFILE_COLUMNS):
        op.drop_column("ai_coin_profiles", name)
    op.drop_index("ix_ai_market_patterns_pattern_key", table_name="ai_market_patterns")
    for name, _ in reversed(PATTERN_COLUMNS):
        op.drop_column("ai_market_patterns", name)
