"""Growth Experience Retrieval utilization metrics (Phase D-A).

Read-only aggregation over durable card traces.  Provider prompt cache and
market-data cache are deliberately not mixed in.
"""

from __future__ import annotations

from sqlalchemy import func, select

from crypto_trader.learning.growth_models import GrowthCardDecisionTraceORM
from crypto_trader.learning.growth_v2_contracts import RETRIEVABLE_STATUSES
from crypto_trader.persistence.models import AICompressedExperienceORM


def _rate(numerator: int, denominator: int) -> float | None:
    return (numerator / denominator) if denominator > 0 else None


async def load_growth_utilization_metrics(
    session_factory, *, account_id: str = "default", mode: str = "PAPER"
) -> dict:
    """Return factual Growth retrieval metrics.

    ``retrieval_hit_rate`` is ``None`` when there are no eligible retrieval
    calls; callers must render that as NO_ELIGIBLE_CALLS, not 0%.
    """
    try:
        async with session_factory() as session:
            available = (
                await session.scalar(
                    select(
                        func.count(func.distinct(AICompressedExperienceORM.rule_id))
                    ).where(
                        AICompressedExperienceORM.account_id == account_id,
                        AICompressedExperienceORM.mode == mode,
                        AICompressedExperienceORM.status.in_(
                            tuple(RETRIEVABLE_STATUSES)
                        ),
                    )
                )
                or 0
            )
            traces = (
                await session.execute(
                    select(GrowthCardDecisionTraceORM).where(
                        GrowthCardDecisionTraceORM.account_id == account_id,
                        GrowthCardDecisionTraceORM.mode == mode,
                    )
                )
            ).scalars().all()
    except Exception:
        return {
            "status": "UNKNOWN",
            "reason": "METRICS_READ_FAILED",
            "growth_experience_cards_available": None,
            "growth_experience_retrieval_calls": None,
            "growth_experience_retrieval_hits": None,
            "growth_experience_retrieval_misses": None,
            "growth_experience_retrieval_hit_rate": None,
            "growth_cards_candidates_seen": None,
            "growth_cards_filtered": None,
            "growth_cards_selected": None,
            "growth_card_refs_returned": None,
            "growth_card_refs_cited_by_decisions": None,
            "growth_decisions_with_card_evidence": None,
            "growth_decisions_without_card_evidence": None,
            "growth_card_trace_attach_success": None,
            "growth_card_trace_attach_failure": None,
            "exclusion_reason_counts": {},
        }

    calls = len(traces)
    hits = 0
    misses = 0
    candidates_seen = 0
    filtered = 0
    selected = 0
    refs_returned = 0
    cited = 0
    decisions_with: set[str] = set()
    decisions_without: set[str] = set()
    attach_success = 0
    attach_failure = 0
    exclusion_counts: dict[str, int] = {}
    for trace in traces:
        selected_count = int(trace.selected_count or 0)
        candidates_seen += int(trace.candidate_count or 0)
        filtered += int(trace.filtered_count or 0)
        selected += selected_count
        refs = list(trace.selected_card_refs_json or [])
        refs_returned += len(refs)
        if trace.decision_id:
            attach_success += 1
            if selected_count > 0:
                cited += len(refs)
        else:
            attach_failure += 1
        if selected_count > 0:
            hits += 1
            if trace.decision_id:
                decisions_with.add(str(trace.decision_id))
        else:
            misses += 1
            if trace.decision_id:
                decisions_without.add(str(trace.decision_id))
        for reasons in (trace.excluded_reasons_json or {}).values():
            for reason in reasons or []:
                key = str(reason).split(":", 1)[0]
                exclusion_counts[key] = exclusion_counts.get(key, 0) + 1

    hit_rate = _rate(hits, calls)
    decision_denominator = len(decisions_with) + len(decisions_without)
    return {
        "status": "KNOWN" if calls > 0 else "UNKNOWN",
        "reason": None if calls > 0 else "NO_ELIGIBLE_CALLS",
        "growth_experience_cards_available": int(available),
        "growth_experience_retrieval_calls": calls,
        "growth_experience_retrieval_hits": hits,
        "growth_experience_retrieval_misses": misses,
        "growth_experience_retrieval_hit_rate": hit_rate,
        "growth_cards_candidates_seen": candidates_seen,
        "growth_cards_filtered": filtered,
        "growth_cards_selected": selected,
        "growth_card_refs_returned": refs_returned,
        "growth_card_refs_cited_by_decisions": cited,
        "growth_decisions_with_card_evidence": len(decisions_with),
        "growth_decisions_without_card_evidence": len(decisions_without),
        "growth_card_trace_attach_success": attach_success,
        "growth_card_trace_attach_failure": attach_failure,
        "growth_decision_utilization_rate": _rate(
            len(decisions_with), decision_denominator
        ),
        "exclusion_reason_counts": dict(sorted(exclusion_counts.items())),
    }
