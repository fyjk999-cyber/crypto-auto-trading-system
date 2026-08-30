"""Runtime hot-reloadable PAPER policy store (directive Phase 2, §21-§28).

Single canonical truth source for the bounded, AI-adjustable runtime policy.
Safety parameters (risk limits, kill switch, execution checks, duplicate
prevention, reconciliation, lease) are FORBIDDEN here by design - they are
not AI policy and are not adjustable online.

Revision ID: 0020_runtime_policy
Revises: 0019_okx_instrument_registry
"""
import sqlalchemy as sa
from alembic import op

revision = "0020_runtime_policy"
down_revision = "0019_okx_instrument_registry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "runtime_policy",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("params_json", sa.JSON(), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("changed_by", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("calibration_window", sa.String(length=64), nullable=True),
        sa.Column("rollback_of", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version", name="uq_runtime_policy_version"),
    )
    op.create_index(
        "ix_runtime_policy_version", "runtime_policy", ["version"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_runtime_policy_version", table_name="runtime_policy")
    op.drop_table("runtime_policy")
