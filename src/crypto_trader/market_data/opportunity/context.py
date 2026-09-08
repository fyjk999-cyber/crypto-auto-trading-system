"""Compact DeepSeek opportunity context (MASTER DIRECTIVE §16).

Builds the bounded candidate/observation summary handed to the Chief Trader
for the symbol under review. Both admission paths are first-class:

    PATH A  FactorCandidate from the factor scanner (factor evidence present)
    PATH B  DeepSeek-selected symbol with zero factor triggers

The context reinforces the permanent authority rules: factor evidence is
optional, is never a trade signal, and never constrains DeepSeek's direction
(§3/§7). Everything here is factual and bounded — no chain-of-thought, no
secrets.
"""

from __future__ import annotations

from crypto_trader.market_data.opportunity.board import OpportunityBoard
from crypto_trader.market_data.opportunity.scanner import (
    CANDIDATE_SOURCE_DEEPSEEK_SELECTION,
    CANDIDATE_SOURCE_MARKET_OBSERVER,
    FactorCandidate,
)

_MAX_TRIGGERED_IN_CONTEXT = 3
_MAX_FACTS_PER_FACTOR = 6
_MAX_MOVERS = 8

AUTHORITY_NOTE = (
    "Factor evidence is OPTIONAL. A factor trigger is not a trade signal, does "
    "not imply any direction, and its absence never prevents trading. You may "
    "contradict factor appearance with factual evidence; you decide direction."
)


def build_opportunity_context(
    *,
    symbol: str,
    candidate: FactorCandidate | None,
    board: OpportunityBoard | None = None,
    deepseek_selected: bool = False,
) -> dict:
    if candidate is not None:
        source = candidate.source
        triggered = [
            {
                "factor": o.factor,
                "strength": o.strength,
                "facts": dict(list(o.facts.items())[:_MAX_FACTS_PER_FACTOR]),
            }
            for o in candidate.triggered[:_MAX_TRIGGERED_IN_CONTEXT]
        ]
        market_facts = dict(candidate.context)
        nominated_reason = candidate.nominated_reason
        factor_evidence_present = candidate.factor_evidence_present
        factor_trigger_count = candidate.factor_trigger_count
    else:
        source = (
            CANDIDATE_SOURCE_DEEPSEEK_SELECTION
            if deepseek_selected
            else CANDIDATE_SOURCE_MARKET_OBSERVER
        )
        triggered = []
        market_facts = {}
        nominated_reason = (
            "DeepSeek selected this symbol from broad-market context; no factor trigger"
            if deepseek_selected
            else "routine broad-market review; no factor trigger"
        )
        factor_evidence_present = False
        factor_trigger_count = 0

    movers: list[dict] = []
    if board is not None:
        movers = (board.broad_market or {}).get("top_abs_movers_24h", [])[:_MAX_MOVERS]

    return {
        "symbol": symbol,
        "candidate_source": source,
        "factor_evidence_present": factor_evidence_present,
        "factor_trigger_count": factor_trigger_count,
        "triggered_factors": triggered,
        "market_facts": market_facts,
        "nominated_reason": nominated_reason,
        "broad_market_top_movers": movers,
        "authority_note": AUTHORITY_NOTE,
    }


def render_opportunity_context_block(ctx: dict) -> str:
    """Render the bounded OPPORTUNITY_CONTEXT prompt block (§16 format)."""
    lines = [
        "OPPORTUNITY_CONTEXT (evidence only — never a trade signal):",
        f"- candidate_source: {ctx.get('candidate_source')}",
        f"- factor_evidence_present: {ctx.get('factor_evidence_present')}",
        f"- factor_trigger_count: {ctx.get('factor_trigger_count')}",
        f"- nominated_reason: {ctx.get('nominated_reason')}",
    ]
    for t in ctx.get("triggered_factors", []):
        strength = t.get("strength")
        lines.append(
            f"- triggered_factor: {t['factor']} (strength {strength}) facts={t.get('facts')}"
        )
    mf = ctx.get("market_facts") or {}
    if mf:
        lines.append(f"- market_facts: {mf}")
    movers = ctx.get("broad_market_top_movers") or []
    if movers:
        lines.append(
            "- broad_market_top_movers_24h: "
            + ", ".join(f"{m['symbol']} {m['price_change_24h_pct']}%" for m in movers)
        )
    lines.append(f"- authority_note: {ctx.get('authority_note')}")
    return "\n".join(lines)
