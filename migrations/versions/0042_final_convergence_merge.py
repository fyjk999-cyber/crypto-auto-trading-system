"""Final Low-Risk V2 convergence: merge ML and News migration lines.

Revision ID: 0042_final_convergence_merge
Revises: 0035_ml_label_v2_alignment, 0041_news_external_evidence,
         0041_pre_ml_convergence_merge

Additive convergence only. Each parent line creates distinct tables/additive
columns; no table or data is removed by this merge revision.
"""

from __future__ import annotations

revision = "0042_final_convergence_merge"
down_revision = (
    "0035_ml_label_v2_alignment",
    "0041_news_external_evidence",
    "0041_pre_ml_convergence_merge",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
