"""M7: persist the #21 artifact lineage used by #25 true-forward predictions.

Additive nullable columns; existing #21 forward rows are untouched.

Revision ID: 0034_ml_forward_model21_lineage
Revises: 0033_ml_forward_predictions
"""

import sqlalchemy as sa
from alembic import op

revision = "0034_ml_forward_model21_lineage"
down_revision = "0033_ml_forward_predictions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ml_forward_predictions", sa.Column("model21_version", sa.String(64), nullable=True)
    )
    op.add_column(
        "ml_forward_predictions", sa.Column("model21_artifact_hash", sa.String(128), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("ml_forward_predictions", "model21_artifact_hash")
    op.drop_column("ml_forward_predictions", "model21_version")
