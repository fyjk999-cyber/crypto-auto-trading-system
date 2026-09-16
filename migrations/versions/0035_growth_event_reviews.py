"""Event-level factual lifecycle counterfactual reviews.

Revision ID: 0035_growth_event_reviews
Revises: 0034_growth_memory_speeds
"""

import sqlalchemy as sa
from alembic import op

revision = "0035_growth_event_reviews"
down_revision = "0034_growth_memory_speeds"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "growth_event_reviews",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("review_id", sa.String(64), nullable=False),
        sa.Column("episode_id", sa.String(64), nullable=False),
        sa.Column("source_event_id", sa.String(64), nullable=False),
        sa.Column("decision_id", sa.String(64)),
        sa.Column("trade_plan_id", sa.String(64)),
        sa.Column("review_type", sa.String(32), nullable=False),
        sa.Column("review_version", sa.String(16), server_default="review-v1"),
        sa.Column("status", sa.String(16), server_default="PENDING"),
        sa.Column("actual_json", sa.JSON()),
        sa.Column("counterfactual_json", sa.JSON()),
        sa.Column("actual_net_bps", sa.Float()),
        sa.Column("counterfactual_net_bps", sa.Float()),
        sa.Column("delta_bps", sa.Float()),
        sa.Column("mfe_bps", sa.Float()),
        sa.Column("mae_bps", sa.Float()),
        sa.Column("cost_bps", sa.Float()),
        sa.Column("fees", sa.Float()),
        sa.Column("slippage_bps", sa.Float()),
        sa.Column("funding_bps", sa.Float()),
        sa.Column("maturity_horizon", sa.String(16)),
        sa.Column("matured_at", sa.DateTime(timezone=True)),
        sa.Column("verdict", sa.String(32)),
        sa.Column("confidence", sa.Float()),
        sa.Column("source_refs_json", sa.JSON()),
        sa.Column("authority", sa.String(24), server_default="LEARNING_ONLY"),
        sa.Column("is_order", sa.Boolean(), server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "episode_id", "source_event_id", "review_type", "review_version",
            name="uq_growth_event_reviews_identity",
        ),
    )
    op.create_index("ix_growth_event_reviews_review_id", "growth_event_reviews", ["review_id"])
    op.create_index("ix_growth_event_reviews_episode_id", "growth_event_reviews", ["episode_id"])
    op.create_index("ix_growth_event_reviews_review_type", "growth_event_reviews", ["review_type"])
    op.create_index("ix_growth_event_reviews_status", "growth_event_reviews", ["status"])


def downgrade() -> None:
    for name in (
        "ix_growth_event_reviews_status",
        "ix_growth_event_reviews_review_type",
        "ix_growth_event_reviews_episode_id",
        "ix_growth_event_reviews_review_id",
    ):
        op.drop_index(name, table_name="growth_event_reviews")
    op.drop_table("growth_event_reviews")
