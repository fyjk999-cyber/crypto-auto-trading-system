"""Opportunity-discovery audit lineage on llm_decisions
(MASTER DIRECTIVE §29/§30).

Adds nullable, server-side-recorded lineage columns so every ChiefTrader
decision durably records where its review symbol came from and whether
factor evidence was present:

  - opportunity_source: FACTOR_SCANNER | MARKET_OBSERVER |
    DEEPSEEK_SELECTION | POSITION_REVIEW | LEGACY_SINGLE_SYMBOL
  - triggered_factors_json: factual triggered factor observations
  - factor_evidence_present: true/false — makes "traded without factor
    evidence" provable without exposing chain-of-thought
  - nominated_reason: bounded scanner nomination text

This metadata is observability only; it never gates or alters authority
(RISK/EXECUTION authority unchanged; FACTOR_REQUIRED_FOR_TRADE stays FALSE).

Revision ID: 0023_opportunity_lineage
Revises: 0022_episode_risk_lineage
"""

import sqlalchemy as sa
from alembic import op

revision = "0023_opportunity_lineage"
down_revision = "0022_episode_risk_lineage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("llm_decisions", sa.Column("opportunity_source", sa.String(40), nullable=True))
    op.add_column("llm_decisions", sa.Column("triggered_factors_json", sa.JSON(), nullable=True))
    op.add_column(
        "llm_decisions", sa.Column("factor_evidence_present", sa.Boolean(), nullable=True)
    )
    op.add_column("llm_decisions", sa.Column("nominated_reason", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("llm_decisions", "nominated_reason")
    op.drop_column("llm_decisions", "factor_evidence_present")
    op.drop_column("llm_decisions", "triggered_factors_json")
    op.drop_column("llm_decisions", "opportunity_source")
