"""Hard evidence-domain isolation for Growth knowledge.

BACKTEST, PAPER and LIVE evidence may share engines but never share pattern
identity, validation state, confidence, metrics or experience cards.
"""

from __future__ import annotations

from typing import Any

EVIDENCE_DOMAIN_BACKTEST = "BACKTEST"
EVIDENCE_DOMAIN_PAPER = "PAPER"
EVIDENCE_DOMAIN_LIVE = "LIVE"
EVIDENCE_DOMAINS = (
    EVIDENCE_DOMAIN_BACKTEST,
    EVIDENCE_DOMAIN_PAPER,
    EVIDENCE_DOMAIN_LIVE,
)

BACKTEST_PROVENANCE_FIELDS = (
    "backtest_run_id",
    "strategy_version",
    "strategy_hash",
    "dataset_hash",
    "date_range",
    "symbol",
    "timeframe",
    "fee_model",
    "slippage_model",
    "funding_model",
    "execution_model",
    "parameter_set_hash",
)


class EvidenceDomainError(ValueError):
    pass


class BacktestProvenanceError(EvidenceDomainError):
    pass


def domain_for_mode(mode: str | None) -> str:
    upper = str(mode or "PAPER").upper()
    if upper == EVIDENCE_DOMAIN_BACKTEST:
        return EVIDENCE_DOMAIN_BACKTEST
    if upper == EVIDENCE_DOMAIN_LIVE:
        return EVIDENCE_DOMAIN_LIVE
    return EVIDENCE_DOMAIN_PAPER


def validate_domain_mode(mode: str | None, evidence_domain: str | None) -> str:
    domain = str(evidence_domain or domain_for_mode(mode)).upper()
    if domain not in EVIDENCE_DOMAINS:
        raise EvidenceDomainError(f"unknown evidence_domain: {domain}")
    mode_domain = domain_for_mode(mode)
    if mode_domain != domain:
        raise EvidenceDomainError(
            f"execution mode {mode!r} cannot carry evidence_domain {domain!r}"
        )
    return domain


def validate_backtest_provenance(provenance: dict[str, Any] | None) -> None:
    missing = [
        field
        for field in BACKTEST_PROVENANCE_FIELDS
        if not str((provenance or {}).get(field) or "").strip()
    ]
    if missing:
        raise BacktestProvenanceError(
            "BACKTEST_KNOWLEDGE_PUBLISH_BLOCKED_MISSING:"
            + ",".join(missing)
        )
