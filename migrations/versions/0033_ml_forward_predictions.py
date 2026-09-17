"""M4: true-forward ML predictions persisted before outcome maturity.

Adds the learning-only forward prediction store. Historical replay never
writes to this table; rows require snapshot time > training cutoff and
prediction_created_at < mature label-v2 availability.

Revision ID: 0033_ml_forward_predictions
Revises: 0032_ml_label_v2_fields
"""

import sqlalchemy as sa
from alembic import op

revision = "0033_ml_forward_predictions"
down_revision = "0032_ml_label_v2_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ml_forward_predictions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("prediction_id", sa.String(64), nullable=False),
        sa.Column("model_id", sa.String(64), nullable=False),
        sa.Column("model_version", sa.String(64), nullable=False),
        sa.Column("artifact_hash", sa.String(128), nullable=False, server_default=""),
        sa.Column("snapshot_id", sa.String(64), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("horizon", sa.String(8), nullable=False, server_default="15m"),
        sa.Column("snapshot_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("prediction_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("training_cutoff_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("probability", sa.Float(), nullable=False),
        sa.Column("direction", sa.String(16), nullable=False, server_default="NEUTRAL"),
        sa.Column("expected_edge", sa.Float(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("feature_version", sa.String(64), nullable=False, server_default=""),
        sa.Column("model21_probability", sa.Float(), nullable=True),
        sa.Column("label_version", sa.String(32), nullable=False, server_default="label-v2"),
        sa.Column("state", sa.String(24), nullable=False, server_default="PENDING_OUTCOME"),
        sa.Column("outcome_label", sa.String(16), nullable=True),
        sa.Column("outcome_net_bps", sa.Float(), nullable=True),
        sa.Column("outcome_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("maturity_quality", sa.String(32), nullable=True),
        sa.Column("authority", sa.String(24), nullable=False, server_default="LEARNING_ONLY"),
        sa.Column("is_order", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("prediction_id", name="uq_ml_forward_predictions_prediction_id"),
        sa.UniqueConstraint(
            "model_id",
            "model_version",
            "snapshot_id",
            name="uq_ml_forward_predictions_model_snapshot",
        ),
    )
    op.create_index("ix_ml_forward_predictions_model_id", "ml_forward_predictions", ["model_id"])
    op.create_index(
        "ix_ml_forward_predictions_model_version", "ml_forward_predictions", ["model_version"]
    )
    op.create_index(
        "ix_ml_forward_predictions_snapshot_id", "ml_forward_predictions", ["snapshot_id"]
    )
    op.create_index(
        "ix_ml_forward_predictions_model_state",
        "ml_forward_predictions",
        ["model_id", "model_version", "state"],
    )


def downgrade() -> None:
    op.drop_index("ix_ml_forward_predictions_model_state", table_name="ml_forward_predictions")
    op.drop_index("ix_ml_forward_predictions_snapshot_id", table_name="ml_forward_predictions")
    op.drop_index("ix_ml_forward_predictions_model_version", table_name="ml_forward_predictions")
    op.drop_index("ix_ml_forward_predictions_model_id", table_name="ml_forward_predictions")
    op.drop_table("ml_forward_predictions")
