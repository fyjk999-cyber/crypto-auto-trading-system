"""pre-ML convergence: merge Growth and Hedge/PositionLeg migration heads

Revision ID: 0041_pre_ml_convergence_merge
Revises: 0033_position_leg_allocation, 0040_growth_memory_versions
Create Date: 2026-09-16

This is an intentional merge of the two independent migration lines that
existed before the low-risk pre-ML convergence:

* Growth / memory line ending at 0040_growth_memory_versions
* Hedge / PositionLeg line ending at 0033_position_leg_allocation

Both lines branch from 0031_scan_snapshot_labels and are additive. No schema
change is required for the merge itself.
"""

from __future__ import annotations

revision = "0041_pre_ml_convergence_merge"
down_revision = (
    "0033_position_leg_allocation",
    "0040_growth_memory_versions",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
