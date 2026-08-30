"""P2-1 repair: enforce the exact-decimal storage contract on episodes.

ROOT CAUSE (directive Phase 4 live finding): migration 0018 / the original
episode table created the exact-decimal columns with NUMERIC/DECIMAL
affinity while the ORM contract (ExactDecimal) is canonical-string storage
(String(80)). SQLite's NUMERIC affinity silently coerced every exact decimal
string (e.g. "0.00362258") into a binary REAL on write. Reads then hit
``Decimal(binary_float)`` rejections -> the LiveMemoryProvider failed 100%
of retrievals (DecimalError, journaled by the Phase 4 tool journal: 32/32
ERROR). Root fix = rebuild the table with String affinity and canonicalize
every stored numeric through Decimal(repr(x)) (exact round-trip for floats),
then normalize to the canonical format. No masking, no reader weakening.

Revision ID: 0022_episodes_decimal_contract
Revises: 0021_tool_invocations
"""
from alembic import op
import sqlalchemy as sa
from decimal import Decimal

revision = "0022_episodes_decimal_contract"
down_revision = "0021_tool_invocations"
branch_labels = None
depends_on = None

# Columns violating the contract -> canonical string storage.
DECIMAL_COLUMNS = (
    "entry_price", "exit_price", "position_size", "leverage",
    "pnl", "mfe", "mae", "gross_pnl", "fees", "net_pnl",
)


def _canon(value):
    if value is None:
        return None
    if isinstance(value, float):
        d = Decimal(repr(value))
    else:
        d = Decimal(str(value))
    text = format(d, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT * FROM ai_trade_episodes")).mappings().all()
    op.create_table(
        "ai_trade_episodes_new",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("episode_id", sa.String(length=64), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("market_regime", sa.String(length=16), nullable=False),
        sa.Column("market_snapshot_json", sa.JSON(), nullable=True),
        sa.Column("quant_evidence_json", sa.JSON(), nullable=True),
        sa.Column("strategy_selected", sa.String(length=200), nullable=False),
        sa.Column("llm_reasoning", sa.String(length=2000), nullable=False),
        sa.Column("entry_price", sa.String(length=80), nullable=True),
        sa.Column("exit_price", sa.String(length=80), nullable=True),
        sa.Column("position_size", sa.String(length=80), nullable=False),
        sa.Column("leverage", sa.String(length=80), nullable=False),
        sa.Column("holding_time_seconds", sa.Float(), nullable=False),
        sa.Column("pnl", sa.String(length=80), nullable=False),
        sa.Column("mfe", sa.String(length=80), nullable=False),
        sa.Column("mae", sa.String(length=80), nullable=False),
        sa.Column("result", sa.String(length=16), nullable=False),
        sa.Column("review_status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("market_type", sa.String(length=16), nullable=False,
                  server_default="SPOT"),
        sa.Column("direction", sa.String(length=8), nullable=False,
                  server_default="LONG"),
        sa.Column("exit_reason", sa.String(length=32), nullable=True),
        sa.Column("lineage_json", sa.JSON(), nullable=True),
        sa.Column("gross_pnl", sa.String(length=80), nullable=True),
        sa.Column("fees", sa.String(length=80), nullable=True),
        sa.Column("net_pnl", sa.String(length=80), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("episode_id", name="uq_ai_trade_episodes_episode_id"),
    )
    cols = list(rows[0].keys()) if rows else []
    if rows:
        insert_sql = (
            "INSERT INTO ai_trade_episodes_new ({cols}) VALUES ({ph})".format(
                cols=", ".join(cols), ph=", ".join(f":{c}" for c in cols)
            )
        )
        for row in rows:
            record = dict(row)
            for col in DECIMAL_COLUMNS:
                if col in record:
                    record[col] = _canon(record[col])
            conn.execute(sa.text(insert_sql), record)
    op.drop_table("ai_trade_episodes")
    op.rename_table("ai_trade_episodes_new", "ai_trade_episodes")
    op.create_index(
        "ix_ai_trade_episodes_symbol", "ai_trade_episodes", ["symbol"]
    )
    op.create_index(
        "ix_ai_trade_episodes_created", "ai_trade_episodes", ["created_at"]
    )


def downgrade() -> None:
    # Not restorable to the coercing NUMERIC affinity without re-corrupting
    # the exact-decimal contract. Kept as a no-op marker.
    raise RuntimeError(
        "downgrade would restore NUMERIC affinity and re-break the exact "
        "decimal storage contract; refusing"
    )
