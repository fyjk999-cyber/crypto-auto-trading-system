"""record versioned domain model on decision evidence

Revision ID: 0017_domain_model_evidence
Revises: 0016_llm_runtime
Create Date: 2026-08-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0017_domain_model_evidence"
down_revision = "0016_llm_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "decision_evidence",
        sa.Column("domain_model_version", sa.String(80), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("decision_evidence", "domain_model_version")
