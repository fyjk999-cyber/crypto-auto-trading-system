"""trade episode learning lineage columns (versioned, replaces runtime DDL)

Revision ID: 0018_trade_episode_lineage
Revises: 0017_domain_model_evidence
Create Date: 2026-08-29

P2 correction (CS-20260829-135700-P2-EPISODE-MAPPING): the episode lineage
columns are now owned by this versioned migration. Runtime ALTER TABLE calls
were removed from crypto_trader.governance.trade_episodes.ensure_columns.
The migration is idempotent (pragma-checked) because an earlier unversioned
runtime ALTER may have already added the columns to an existing database.
"""

from __future__ import annotations

from alembic import op

revision = "0018_trade_episode_lineage"
down_revision = "0017_domain_model_evidence"
branch_labels = None
depends_on = None

COLUMNS = (
    ("market_type", "VARCHAR(16) NOT NULL DEFAULT 'SPOT'"),
    ("direction", "VARCHAR(8) NOT NULL DEFAULT 'LONG'"),
    ("exit_reason", "VARCHAR(32)"),
    ("lineage_json", "JSON"),
    ("gross_pnl", "DECIMAL(30,12)"),
    ("fees", "DECIMAL(30,12)"),
    ("net_pnl", "DECIMAL(30,12)"),
)


def _existing_columns() -> set[str]:
    conn = op.get_bind()
    rows = conn.exec_driver_sql("PRAGMA table_info(ai_trade_episodes)").fetchall()
    return {r[1] for r in rows}


def upgrade() -> None:
    existing = _existing_columns()
    if not existing:
        # table not present in this environment; nothing to extend
        return
    for name, ddl in COLUMNS:
        if name not in existing:
            op.execute(f"ALTER TABLE ai_trade_episodes ADD COLUMN {name} {ddl}")


def downgrade() -> None:
    # Column removal is not performed: derived lineage columns are inert and
    # dropping them would destroy learning evidence on downgrade.
    return None
