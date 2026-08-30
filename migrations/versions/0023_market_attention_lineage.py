"""Market Observer AI attention lineage (P1 CS-20260830-034530-P3-AI-ATTENTION).

Durable, inspectable lineage for every Market Observer AI attention
decision: the bounded compressed all-market input (digest id, bucket
counts, Layer-1 batch ids), the AI-selected instruments granted the
bounded non-core rotation slots, and the LLM invocation id. Chief Trader
decision evidence references attention_uid. No order/fill data is stored
or fabricated here.

Revision ID: 0023_market_attention_lineage
Revises: 0022_episodes_decimal_contract
"""
import sqlalchemy as sa
from alembic import op

revision = "0023_market_attention_lineage"
down_revision = "0022_episodes_decimal_contract"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "market_attention_decisions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("attention_uid", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False, server_default=""),
        sa.Column("selected_inst_ids", sa.JSON(), nullable=True),
        sa.Column("pinned_inst_ids", sa.JSON(), nullable=True),
        sa.Column("roster_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("universe_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("buckets_json", sa.JSON(), nullable=True),
        sa.Column("rationale", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("llm_invocation_id", sa.String(length=64), nullable=True),
        sa.Column("input_digest", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cache_state", sa.String(length=16), nullable=False, server_default="UNKNOWN"),
        sa.Column("error", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("layer1_batch_ids", sa.JSON(), nullable=True),
        sa.Column("selector_version", sa.String(length=32), nullable=False, server_default=""),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_market_attention_uid",
        "market_attention_decisions",
        ["attention_uid"],
        unique=True,
    )
    op.create_index(
        "ix_market_attention_created",
        "market_attention_decisions",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_market_attention_created", table_name="market_attention_decisions")
    op.drop_index("ix_market_attention_uid", table_name="market_attention_decisions")
    op.drop_table("market_attention_decisions")
