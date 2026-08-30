"""Position review journal for the Shadow Position Manager
(STRATEGY DIRECTIVE §15/§23/§36/§76).

``position_reviews`` records every shadow (and later ACTIVE) position
management review: which position/thesis was reviewed, what evidence was
visible (bounded), what the AI recommended (HOLD/EXIT/REDUCE/SKIP) and why,
and whether the recommendation was executed. In shadow mode ``executed`` is
always 0 — the table is the honest counterfactual record used to compare
AI exits against the TIME_STOP fallback (§77/§78) before any promotion.

No raw prompts or secrets. Every text field is bounded.

Revision ID: 0025_position_reviews
Revises: 0024_tool_lineage_audit
"""
import sqlalchemy as sa
from alembic import op

revision = "0025_position_reviews"
down_revision = "0024_tool_lineage_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "position_reviews",
        sa.Column("review_id", sa.String(64), primary_key=True),
        sa.Column("symbol", sa.String(40), nullable=False),
        sa.Column("market_type", sa.String(20), nullable=False, server_default="SPOT"),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("episode_key", sa.String(80)),
        sa.Column("thesis_decision_id", sa.String(64)),
        sa.Column("review_timestamp", sa.String(40), nullable=False),
        sa.Column("holding_seconds", sa.Float),
        sa.Column("entry_price", sa.String(80)),
        sa.Column("current_price", sa.String(80)),
        sa.Column("unrealized_pnl", sa.String(80)),
        sa.Column("recommended_action", sa.String(10), nullable=False),
        sa.Column("reason_summary", sa.String(400)),
        sa.Column("llm_invocation_id", sa.String(80)),
        sa.Column("executed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("manager_mode", sa.String(10), nullable=False, server_default="SHADOW"),
        sa.Column("created_at", sa.String(40), nullable=False),
    )
    op.create_index(
        "ix_position_reviews_symbol_ts",
        "position_reviews",
        ["symbol", "review_timestamp"],
    )


def downgrade() -> None:
    op.drop_index("ix_position_reviews_symbol_ts", table_name="position_reviews")
    op.drop_table("position_reviews")
