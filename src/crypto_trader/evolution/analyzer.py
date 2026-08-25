"""Error analysis -> proposals. No direct parameter mutation."""

from __future__ import annotations

from crypto_trader.evolution.proposal import EvolutionProposal, create_proposal


def propose_from_error(
    proposal_id: str, error_category: str, symbol_category: str
) -> EvolutionProposal:
    if error_category == "FALSE_LONG" and symbol_category == "MEME":
        return create_proposal(
            proposal_id,
            "Reduce Momentum weight for Meme",
            {"momentum_weight_meme": "0.10"},
            "Momentum false longs on Meme coins",
        )
    if error_category == "FALSE_SHORT":
        return create_proposal(
            proposal_id,
            "Reduce Short confidence in RANGE regime",
            {"short_confidence_range": "0.05"},
            "FALSE_SHORT in RANGE",
        )
    return create_proposal(proposal_id, "No change", {}, "No actionable error pattern")
