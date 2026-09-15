"""Low-Risk V2 per-leg quantities (Phase 4D dual-side tracking).

Adds quantity/remaining_quantity to `position_legs` so LONG and SHORT legs on
the same symbol are tracked independently instead of only as a net position.

Additive, nullable: existing legs remain readable.

Revision ID: 0026_position_leg_quantities
Revises: 0025_position_legs
"""

import sqlalchemy as sa
from alembic import op

revision = "0026_position_leg_quantities"
down_revision = "0025_position_legs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("position_legs", sa.Column("quantity", sa.String(80), nullable=True))
    op.add_column("position_legs", sa.Column("remaining_quantity", sa.String(80), nullable=True))


def downgrade() -> None:
    op.drop_column("position_legs", "remaining_quantity")
    op.drop_column("position_legs", "quantity")
