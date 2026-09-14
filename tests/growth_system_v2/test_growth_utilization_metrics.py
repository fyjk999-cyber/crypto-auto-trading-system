"""Phase D-A: Growth experience retrieval utilization metrics."""

from __future__ import annotations

from crypto_trader.learning.growth_card_retrieval import (
    CardDecisionTraceStore,
    ExperienceCardRetriever,
)
from crypto_trader.learning.growth_utilization_metrics import (
    load_growth_utilization_metrics,
)
from tests.growth_system_v2.conftest import AS_OF, market_context, seed_card, trigger


async def test_growth_utilization_metrics_count_hit_and_miss(v2_db):
    await seed_card(v2_db, rule_id="card_metric", status="ACTIVE")
    retriever = ExperienceCardRetriever(v2_db.session_factory)
    trace_store = CardDecisionTraceStore(v2_db.session_factory)

    hit = await retriever.retrieve(
        trigger=trigger(), context=market_context(), as_of=AS_OF
    )
    await trace_store.record(
        hit,
        decision_id="decision_metric_hit",
        evidence_package_id="pkg_metric_hit",
        account_id="default",
        mode="PAPER",
    )
    miss = await retriever.retrieve(
        trigger=trigger(),
        context=market_context(regime="RANGE"),
        as_of=AS_OF,
    )
    await trace_store.record(
        miss,
        decision_id="decision_metric_miss",
        evidence_package_id="pkg_metric_miss",
        account_id="default",
        mode="PAPER",
    )

    metrics = await load_growth_utilization_metrics(v2_db.session_factory)
    assert metrics["growth_experience_cards_available"] == 1
    assert metrics["growth_experience_retrieval_calls"] == 2
    assert metrics["growth_experience_retrieval_hits"] == 1
    assert metrics["growth_experience_retrieval_misses"] == 1
    assert metrics["growth_experience_retrieval_hit_rate"] == 0.5
    assert metrics["growth_cards_selected"] == 1
    assert metrics["growth_card_refs_returned"] == 1
    assert metrics["growth_card_refs_cited_by_decisions"] == 1
    assert metrics["growth_decisions_with_card_evidence"] == 1
    assert metrics["growth_decisions_without_card_evidence"] == 1
    assert metrics["growth_card_trace_attach_success"] == 2
    assert metrics["growth_card_trace_attach_failure"] == 0
    assert "CONTEXT_MISMATCH" in metrics["exclusion_reason_counts"]


async def test_growth_utilization_metrics_no_eligible_calls_is_unknown(v2_db):
    metrics = await load_growth_utilization_metrics(v2_db.session_factory)
    assert metrics["status"] == "UNKNOWN"
    assert metrics["reason"] == "NO_ELIGIBLE_CALLS"
    assert metrics["growth_experience_retrieval_hit_rate"] is None
