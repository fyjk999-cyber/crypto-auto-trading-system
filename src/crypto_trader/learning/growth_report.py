"""Growth V2 daily report assembly (Phase 5).

Joins the decision-time-frozen Top-10, the persisted outcome taxonomy, the seven
required lifecycle reviews and any thesis-rationalization verdicts into one
learning report.

Learning/observability only — Growth never trades, and this report grants no
authority over Risk, Execution, model formulas or order flow.
"""

from __future__ import annotations

from crypto_trader.learning.review_taxonomy import review_coverage


async def build_growth_daily_report(
    *,
    trading_day: str,
    freezer,
    outcome_recorder,
    events: list[dict] | None = None,
    rationalization_verdicts: list[dict] | None = None,
) -> dict:
    top10 = await freezer.get(trading_day)
    outcomes = await outcome_recorder.summary(trading_day)
    coverage = review_coverage(list(events or []))
    verdicts = list(rationalization_verdicts or [])
    flagged = [
        verdict
        for verdict in verdicts
        if verdict.get("verdict") == "POSSIBLE_THESIS_RATIONALIZATION"
    ]
    return {
        "trading_day": trading_day,
        "top10": top10,
        "top10_count": len(top10),
        "outcomes": outcomes,
        "reviews": coverage,
        "rationalization": {
            "checks": len(verdicts),
            "flagged": len(flagged),
            "possible_rationalizations": flagged,
        },
        "authority": "LEARNING_ONLY",
        "is_order": False,
        "can_modify_core": False,
    }
