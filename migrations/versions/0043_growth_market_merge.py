"""merge growth v2 and market intelligence migration branches

Two independently reviewed lines both fork at 0039_applicability:

    0039_applicability -> 0040_runtime_settings -> 0041_market_selection
                       -> 0042_selection_exploration        (Market Intelligence)
    0039_applicability -> 0040_growth_v2_cards              (Growth V2)

This revision is a pure graph convergence: both branches are already applied
independently and neither is renamed or rewritten. It performs NO schema or data
mutation of its own.

Revision ID: 0043_growth_market_merge
Revises: 0042_selection_exploration, 0040_growth_v2_cards
Create Date: 2026-09-11
"""

from __future__ import annotations

revision = "0043_growth_market_merge"
down_revision = ("0042_selection_exploration", "0040_growth_v2_cards")
branch_labels = None
depends_on = None

# Convergence only: both parents own their schema. Alembic merge revisions must
# not perform unrelated DDL, so the upgrade/downgrade bodies stay empty.
# ``alembic upgrade`` applies whichever branch is still missing, then records
# this revision; ``alembic downgrade`` simply unmerges the two heads again.


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
