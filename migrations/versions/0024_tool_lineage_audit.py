"""Tool invocation audit fields + episode entry-decision link
(P2 CS-20260830-034530-P4-TOOL-LINEAGE).

1. ``tool_invocations`` gains the bounded audit contract fields: tool
   version, source (pipeline stage), cache state, start/end wall times,
   bounded error, and the evidence-added marker. No raw prompts, payloads
   or secrets are stored -- every new text field is bounded and factual.
2. ``ai_trade_episodes`` gains an immutable ``entry_decision_id`` column,
   populated ONLY from the canonical entry fill payload / existing
   lineage_json (the link recorded at trade time). Historical episodes
   without that fact stay NULL (honest unknown) -- links are never
   guessed or fabricated. Raw orders/fills/ledger/audit rows are not
   touched.

Revision ID: 0024_tool_lineage_audit
Revises: 0023_market_attention_lineage
"""
import sqlalchemy as sa
from alembic import op

revision = "0024_tool_lineage_audit"
down_revision = "0023_market_attention_lineage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tool_invocations",
        sa.Column("tool_version", sa.String(length=32), nullable=False,
                  server_default=""),
    )
    op.add_column(
        "tool_invocations",
        sa.Column("source", sa.String(length=32), nullable=False,
                  server_default=""),
    )
    op.add_column(
        "tool_invocations",
        sa.Column("cache_state", sa.String(length=16), nullable=False,
                  server_default="UNKNOWN"),
    )
    op.add_column(
        "tool_invocations",
        sa.Column("started_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "tool_invocations",
        sa.Column("finished_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "tool_invocations",
        sa.Column("error", sa.String(length=255), nullable=False,
                  server_default=""),
    )
    op.add_column(
        "tool_invocations",
        sa.Column("evidence_added", sa.String(length=16), nullable=False,
                  server_default="UNKNOWN"),
    )
    op.add_column(
        "ai_trade_episodes",
        sa.Column("entry_decision_id", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_ai_trade_episodes_entry_decision",
        "ai_trade_episodes",
        ["entry_decision_id"],
    )
    # Factual backfill: extract the entry decision id that the episode
    # lineage already carries (recorded at trade time from the canonical
    # entry fill payload). Rows without it remain NULL.
    op.execute(
        "UPDATE ai_trade_episodes SET entry_decision_id = "
        "json_extract(lineage_json, '$.entry_decision_id') "
        "WHERE entry_decision_id IS NULL "
        "AND json_extract(lineage_json, '$.entry_decision_id') IS NOT NULL "
        "AND json_extract(lineage_json, '$.entry_decision_id') != ''"
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ai_trade_episodes_entry_decision", table_name="ai_trade_episodes"
    )
    op.drop_column("ai_trade_episodes", "entry_decision_id")
    op.drop_column("tool_invocations", "evidence_added")
    op.drop_column("tool_invocations", "error")
    op.drop_column("tool_invocations", "finished_at")
    op.drop_column("tool_invocations", "started_at")
    op.drop_column("tool_invocations", "cache_state")
    op.drop_column("tool_invocations", "source")
    op.drop_column("tool_invocations", "tool_version")
