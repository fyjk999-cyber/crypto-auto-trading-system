"""Phase H tool invocation journal (directive P2-1 Phase 4, §51-§62).

Every tool invocation made by the decision pipeline is journaled with
decision lineage, enabling factual tool-utility learning (advisory only).

Revision ID: 0021_tool_invocations
Revises: 0020_runtime_policy
"""
from alembic import op
import sqlalchemy as sa

revision = "0021_tool_invocations"
down_revision = "0020_runtime_policy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tool_invocations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("invocation_uid", sa.String(length=64), nullable=False),
        sa.Column("tool_name", sa.String(length=64), nullable=False),
        sa.Column("decision_id", sa.String(length=64), nullable=True),
        sa.Column("llm_invocation_id", sa.String(length=64), nullable=True),
        sa.Column("symbol", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("detail", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_tool_invocations_decision", "tool_invocations", ["decision_id"]
    )
    op.create_index(
        "ix_tool_invocations_tool", "tool_invocations", ["tool_name", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_tool_invocations_tool", table_name="tool_invocations")
    op.drop_index("ix_tool_invocations_decision", table_name="tool_invocations")
    op.drop_table("tool_invocations")
