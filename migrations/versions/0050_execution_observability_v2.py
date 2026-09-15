"""execution observability v2 — entry evidence without touching execution behaviour

Why this migration exists: the system currently records what it DECIDED but not
what the market actually offered at the moment it tried to execute. Measured
facts that motivated it: 57 historical entry orders, full_fill_rate 3.5%, zero_fill
rate 45.6%, weighted fill ratio 1.48%, and an exposure realization ratio of about
2.6% (requested 672,549 USDT vs actually opened 17,431 USDT).

Phase E0 is deliberately OBSERVATION ONLY. Nothing here is read on any decision
path, so the behavioural trading diff is zero: same ChiefTrader decisions, same
Sizer, same Risk, same TTL, same order logic. These tables are append-only
evidence so a later phase can answer "how much exposure can the market actually
absorb now" from facts instead of from a new unvalidated heuristic.

``market_snapshots`` already exists and is deliberately reused rather than
duplicated - it had ZERO writers anywhere in the codebase at the time of writing,
so adding a nullable column to it cannot change any behaviour.

Revision ID: 0050_execution_observability_v2
Revises: 0049_ledger_fill_event_uniqueness
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0050_execution_observability_v2"
down_revision = "0049_ledger_fill_event_uniqueness"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    bind = op.get_bind()
    return set(sa.inspect(bind).get_table_names())


def upgrade() -> None:
    tables = _tables()

    # --- extend the existing (writer-less) market_snapshots ------------------
    # Computed orderbook metrics live beside the raw levels the table already
    # stores. Nullable so pre-existing rows - there are none today - stay valid.
    if "orders" in tables:
        ocols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("orders")}
        for name in (
            "cancel_confirmed_at",
            "cancel_requested_at",
            "last_fill_at",
            "first_fill_at",
        ):
            if name in ocols:
                op.drop_column("orders", name)
    if "market_snapshots" in tables:
        cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("market_snapshots")}
        if "metrics_json" not in cols:
            op.add_column(
                "market_snapshots",
                sa.Column("metrics_json", sa.JSON(), nullable=True),
            )

    # --- factual order lifecycle instants (§16) ------------------------------
    # Recorded, never read on a decision path, so they cannot change behaviour.
    if "orders" in tables:
        ocols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("orders")}
        for column in (
            sa.Column("first_fill_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_fill_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("cancel_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        ):
            if column.name not in ocols:
                op.add_column("orders", column)

    # --- entry execution evidence: one row per ENTRY intent ------------------
    if "entry_execution_evidence" not in tables:
        op.create_table(
            "entry_execution_evidence",
            sa.Column("evidence_id", sa.String(64), primary_key=True),
            sa.Column("decision_id", sa.String(64), nullable=True, index=True),
            sa.Column("trade_plan_id", sa.String(64), nullable=True, index=True),
            sa.Column("order_id", sa.String(64), nullable=True, index=True),
            sa.Column("run_id", sa.String(64), nullable=True),
            sa.Column("symbol", sa.String(32), nullable=False, index=True),
            sa.Column("side", sa.String(8), nullable=True),
            sa.Column("chief_direction", sa.String(16), nullable=True),

            # The three exposures must never be conflated (§14).
            sa.Column("target_quantity", sa.String(64), nullable=True),
            sa.Column("target_notional", sa.String(64), nullable=True),
            sa.Column("risk_approved_max_quantity", sa.String(64), nullable=True),
            sa.Column("risk_approved_max_notional", sa.String(64), nullable=True),
            sa.Column("requested_order_quantity", sa.String(64), nullable=True),
            sa.Column("requested_order_notional", sa.String(64), nullable=True),
            sa.Column("actual_opened_quantity", sa.String(64), nullable=True),
            sa.Column("actual_opened_notional", sa.String(64), nullable=True),

            sa.Column("exposure_realization_ratio", sa.String(64), nullable=True),
            sa.Column("leverage", sa.String(32), nullable=True),
            sa.Column("limit_price", sa.String(64), nullable=True),

            # Pre-submit orderbook snapshot id (market_snapshots.id), when taken.
            sa.Column("pre_submit_snapshot_id", sa.Integer(), nullable=True),
            sa.Column("pre_submit_metrics_json", sa.JSON(), nullable=True),
            # Depth on the side this entry would CONSUME, recorded beside the
            # metrics so executability can be studied without a stale book.
            sa.Column("executable_side", sa.String(8), nullable=True),
            sa.Column("executable_depth_l1", sa.String(64), nullable=True),
            sa.Column("executable_depth_l5", sa.String(64), nullable=True),
            sa.Column("executable_depth_l10", sa.String(64), nullable=True),

            sa.Column("quality", sa.String(16), nullable=False, default="OK"),
            sa.Column("reason_codes_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )

    # --- post-submit orderbook sampling -------------------------------------
    if "entry_orderbook_samples" not in tables:
        op.create_table(
            "entry_orderbook_samples",
            sa.Column("sample_id", sa.String(64), primary_key=True),
            sa.Column("evidence_id", sa.String(64), nullable=False, index=True),
            sa.Column("symbol", sa.String(32), nullable=False, index=True),
            sa.Column("offset_seconds", sa.Integer(), nullable=False),
            sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("source", sa.String(32), nullable=False),
            sa.Column("source_timestamp", sa.DateTime(timezone=True), nullable=True),
            sa.Column("quality", sa.String(16), nullable=False, default="OK"),
            sa.Column("best_bid", sa.String(64), nullable=True),
            sa.Column("best_ask", sa.String(64), nullable=True),
            sa.Column("mid", sa.String(64), nullable=True),
            sa.Column("spread_bps", sa.String(32), nullable=True),
            sa.Column("bids_json", sa.JSON(), nullable=True),
            sa.Column("asks_json", sa.JSON(), nullable=True),
            sa.Column("bid_depth_l1", sa.String(64), nullable=True),
            sa.Column("ask_depth_l1", sa.String(64), nullable=True),
            sa.Column("bid_depth_l5", sa.String(64), nullable=True),
            sa.Column("ask_depth_l5", sa.String(64), nullable=True),
            sa.Column("bid_depth_l10", sa.String(64), nullable=True),
            sa.Column("ask_depth_l10", sa.String(64), nullable=True),
            sa.Column("microprice", sa.String(64), nullable=True),
            sa.Column("orderbook_imbalance", sa.String(32), nullable=True),
            sa.Column("executable_side", sa.String(8), nullable=True),
            sa.Column("executable_depth_l1", sa.String(64), nullable=True),
            sa.Column("executable_depth_l5", sa.String(64), nullable=True),
            sa.Column("executable_depth_l10", sa.String(64), nullable=True),
            sa.Column("our_limit_price", sa.String(64), nullable=True),
            sa.Column("our_remaining_quantity", sa.String(64), nullable=True),
            sa.Column("cumulative_fill_quantity", sa.String(64), nullable=True),
            sa.Column("market_traded_volume", sa.String(64), nullable=True),
            sa.Column("queue_ahead", sa.String(64), nullable=True),
            sa.Column("queue_ahead_quality", sa.String(16), nullable=True),
            sa.UniqueConstraint(
                "evidence_id",
                "offset_seconds",
                name="uq_entry_orderbook_samples_evidence_offset",
            ),
        )


def downgrade() -> None:
    tables = _tables()
    # Drop the observability columns THIS migration added to pre-existing tables
    # first, so a re-upgrade from 0049 applies them again cleanly.
    if "orders" in tables:
        ocols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("orders")}
        for name in (
            "cancel_confirmed_at",
            "cancel_requested_at",
            "last_fill_at",
            "first_fill_at",
        ):
            if name in ocols:
                op.drop_column("orders", name)
    if "entry_orderbook_samples" in tables:
        op.drop_table("entry_orderbook_samples")
    if "entry_execution_evidence" in tables:
        op.drop_table("entry_execution_evidence")
    if "market_snapshots" in tables:
        cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("market_snapshots")}
        if "metrics_json" in cols:
            op.drop_column("market_snapshots", "metrics_json")
