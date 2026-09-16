"""Cross-regime generalized growth knowledge.

Revision ID: 0039_generalized_knowledge
Revises: 0038_outcome_quality_status
"""

import sqlalchemy as sa
from alembic import op

revision = "0039_generalized_knowledge"
down_revision = "0038_outcome_quality_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "growth_generalized_knowledge",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("generalized_id", sa.String(64), nullable=False),
        sa.Column("asset", sa.String(32), nullable=False),
        sa.Column("strategy", sa.String(64), nullable=False),
        sa.Column("horizon", sa.String(8), nullable=False),
        sa.Column("setup_signature", sa.String(64), nullable=False),
        sa.Column("sample_count", sa.Integer()),
        sa.Column("regime_count", sa.Integer()),
        sa.Column("source_pattern_ids_json", sa.JSON()),
        sa.Column("source_regimes_json", sa.JSON()),
        sa.Column("source_episode_count", sa.Integer()),
        sa.Column("post_cost_expectancy_bps", sa.Float()),
        sa.Column("chronological_stability", sa.Boolean()),
        sa.Column("contradictions", sa.Integer()),
        sa.Column("quality", sa.Float()),
        sa.Column("sample_tier", sa.String(32)),
        sa.Column("memory_speed", sa.String(32)),
        sa.Column("version", sa.Integer()),
        sa.Column("available_at", sa.DateTime(timezone=True)),
        sa.Column("policy_version", sa.String(32)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("generalized_id", name="uq_growth_generalized_id"),
    )
    for name in ("generalized_id", "asset", "strategy", "horizon", "setup_signature"):
        op.create_index(f"ix_growth_generalized_{name}", "growth_generalized_knowledge", [name])


def downgrade() -> None:
    for name in ("setup_signature", "horizon", "strategy", "asset", "generalized_id"):
        op.drop_index(f"ix_growth_generalized_{name}", table_name="growth_generalized_knowledge")
    op.drop_table("growth_generalized_knowledge")
