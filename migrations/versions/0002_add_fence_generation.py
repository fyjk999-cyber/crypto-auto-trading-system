"""add fence generation to runtime leases

Revision ID: 0002addfence
Revises: 43c806e64582
Create Date: 2026-08-24
"""

import sqlalchemy as sa
from alembic import op

revision = "0002addfence"
down_revision = "43c806e64582"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "runtime_leases",
        sa.Column("fence_generation", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("runtime_leases", "fence_generation")
