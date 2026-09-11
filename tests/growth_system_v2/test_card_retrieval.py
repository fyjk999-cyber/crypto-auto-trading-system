"""G11 runtime retrieval, hard filter, ranking, trace and read-only tests."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

from sqlalchemy import event, select

from crypto_trader.learning.growth_card_retrieval import (
    CardDecisionTraceStore,
    CardRankingPolicy,
    ExperienceCardRetriever,
)
from crypto_trader.learning.growth_models import GrowthCardDecisionTraceORM
from crypto_trader.learning.growth_v2_contracts import (
    STATUS_STALE,
)
from crypto_trader.persistence.models import AICompressedExperienceORM
from tests.growth_system_v2.conftest import AS_OF, market_context, seed_card, trigger


def _retriever(database, **policy_overrides):
    policy = CardRankingPolicy(**policy_overrides)
    return ExperienceCardRetriever(database.session_factory, policy=policy)


@contextmanager
def _track_writes(engine):
    statements: list[str] = []

    def listener(conn, cursor, statement, parameters, context, executemany):
        upper = statement.upper().lstrip()
        if upper.startswith(("INSERT", "UPDATE", "DELETE")):
            statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", listener)
    try:
        yield statements
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", listener)


async def test_retrieval_selects_matching_card_and_reports_metrics(v2_db):
    await seed_card(v2_db, rule_id="card_match", status="ACTIVE")
    with _track_writes(v2_db.engine) as writes:
        result = await _retriever(v2_db).retrieve(
            trigger=trigger(), context=market_context(), as_of=AS_OF, top_k=3
        )
    assert writes == [], f"runtime retrieval must not write: {writes}"
    assert len(result.selected) == 1
    selected = result.selected[0]
    assert selected.rule_id == "card_match"
    assert "TRIGGER_EXACT_MATCH" in selected.why
    assert result.metrics["candidate_card_count"] == 1
    assert result.metrics["filtered_card_count"] == 1
    assert result.metrics["selected_card_count"] == 1
    assert result.metrics["context_tokens_estimate"] > 0
    assert result.metrics["retrieval_ms"] >= 0


async def test_wrong_regime_and_wrong_factor_definition_are_excluded(v2_db):
    await seed_card(v2_db, rule_id="card_wrong_regime", status="ACTIVE")
    result = await _retriever(v2_db).retrieve(
        trigger=trigger(),
        context=market_context(regime="RANGE"),
        as_of=AS_OF,
    )
    assert result.selected == []
    reasons = result.excluded_reasons["card:card_wrong_regime:v1"]
    assert any(reason.startswith("CONTEXT_MISMATCH:regime") for reason in reasons)

    result = await _retriever(v2_db).retrieve(
        trigger=trigger(definition_version="funding-def-v2"),
        context=market_context(),
        as_of=AS_OF,
    )
    assert result.selected == []
    reasons = result.excluded_reasons["card:card_wrong_regime:v1"]
    assert any(reason.startswith("FACTOR_DEFINITION_INCOMPATIBLE") for reason in reasons)


async def test_retired_and_candidate_and_stale_policy(v2_db):
    await seed_card(v2_db, rule_id="card_retired", status="RETIRED")
    await seed_card(v2_db, rule_id="card_candidate", status="CANDIDATE")
    await seed_card(v2_db, rule_id="card_stale", status=STATUS_STALE)

    default_result = await _retriever(v2_db).retrieve(
        trigger=trigger(), context=market_context(), as_of=AS_OF
    )
    assert default_result.selected == []
    assert default_result.excluded_reasons["card:card_retired:v1"] == ["RETIRED"]
    assert default_result.excluded_reasons["card:card_candidate:v1"] == [
        "CANDIDATE_NOT_ACTIVE"
    ]
    assert default_result.excluded_reasons["card:card_stale:v1"] == [
        "STALE_BEYOND_POLICY"
    ]

    stale_policy = await _retriever(v2_db, include_stale=True).retrieve(
        trigger=trigger(), context=market_context(), as_of=AS_OF
    )
    assert [item.rule_id for item in stale_policy.selected] == ["card_stale"]
    assert "STALE_PENALTY" in stale_policy.selected[0].why


async def test_top_k_and_token_budget_are_bounded(v2_db):
    for index in range(5):
        await seed_card(
            v2_db,
            rule_id=f"card_top_{index}",
            status="ACTIVE",
            guidance={"summary": f"candidate {index}", "direction": "LONG"},
        )
    bounded = await _retriever(v2_db, top_k=2).retrieve(
        trigger=trigger(), context=market_context(), as_of=AS_OF
    )
    assert len(bounded.selected) == 2
    assert any(
        "TOP_K_EXCEEDED" in reasons for reasons in bounded.excluded_reasons.values()
    )

    tiny = await _retriever(v2_db, top_k=5, token_budget=1).retrieve(
        trigger=trigger(), context=market_context(), as_of=AS_OF
    )
    assert tiny.selected == []
    assert tiny.metrics["context_tokens_estimate"] == 0
    assert any(
        "TOKEN_BUDGET" in reasons for reasons in tiny.excluded_reasons.values()
    )


async def test_cross_symbol_and_require_symbol_policy(v2_db):
    await seed_card(
        v2_db,
        rule_id="card_cross_symbol",
        status="ACTIVE",
        symbol=None,
    )
    cross = await _retriever(v2_db).retrieve(
        trigger=trigger(),
        context=market_context(symbol="ETHUSDT"),
        as_of=AS_OF,
    )
    assert [item.rule_id for item in cross.selected] == ["card_cross_symbol"]

    # A SYMBOL-scoped card is excluded when the policy requires an exact symbol.
    await seed_card(v2_db, rule_id="card_symbol_scoped", status="ACTIVE")
    async with v2_db.session_factory() as session:
        row = (
            await session.execute(
                select(AICompressedExperienceORM).where(
                    AICompressedExperienceORM.rule_id == "card_symbol_scoped"
                )
            )
        ).scalar_one()
        row.applicability_scope_json = {
            "scope": "SYMBOL",
            "symbols": ["BTCUSDT"],
        }
        await session.commit()
    strict = await _retriever(v2_db, require_symbol_match=True).retrieve(
        trigger=trigger(),
        context=market_context(symbol="ETHUSDT"),
        as_of=AS_OF,
    )
    assert "card:card_symbol_scoped:v1" in strict.excluded_reasons
    assert "SYMBOL_MISMATCH" in strict.excluded_reasons["card:card_symbol_scoped:v1"]


async def test_general_legacy_fallback_respects_policy(v2_db):
    async with v2_db.session_factory() as session:
        session.add(
            AICompressedExperienceORM(
                rule_id="legacy_general",
                symbol=None,
                title="Legacy compressed experience",
                content="Legacy general lesson",
                source_episode_count=5,
                version=1,
                experience_type="COMPRESSED_EXPERIENCE",
                account_id="default",
                mode="PAPER",
                status="WATCH",
                applicability_scope_json={},
                known_at=AS_OF - timedelta(days=1),
                updated_at=AS_OF - timedelta(days=1),
                created_at=AS_OF - timedelta(days=1),
            )
        )
        await session.commit()

    allowed = await _retriever(v2_db).retrieve(
        trigger=trigger(), context=market_context(), as_of=AS_OF
    )
    assert [item.rule_id for item in allowed.selected] == ["legacy_general"]
    assert "GENERAL_FALLBACK" in allowed.selected[0].why

    disabled = await _retriever(v2_db, allow_general_fallback=False).retrieve(
        trigger=trigger(), context=market_context(), as_of=AS_OF
    )
    assert disabled.selected == []
    assert "GENERAL_FALLBACK_DISABLED" in disabled.excluded_reasons[
        "card:legacy_general:v1"
    ]


async def test_future_known_at_is_rejected_by_hard_filter(v2_db):
    from crypto_trader.learning.growth_card_retrieval import evaluate_hard_applicability
    from crypto_trader.learning.growth_experience import AdaptiveCardStore

    await seed_card(v2_db, rule_id="card_future", status="ACTIVE")
    card = await AdaptiveCardStore(v2_db.session_factory).get_card("card_future")
    card.known_at = AS_OF + timedelta(days=1)
    card.last_validated_at = AS_OF + timedelta(days=1)
    result = evaluate_hard_applicability(
        card, trigger(), market_context(), as_of=AS_OF, policy=CardRankingPolicy()
    )
    assert result.allowed is False
    assert "FUTURE_KNOWN_AT" in result.reasons


async def test_decision_trace_records_selected_versions_and_exclusions(v2_db):
    await seed_card(v2_db, rule_id="card_trace", status="ACTIVE")
    await seed_card(v2_db, rule_id="card_trace_retired", status="RETIRED")
    result = await _retriever(v2_db).retrieve(
        trigger=trigger(), context=market_context(), as_of=AS_OF
    )
    trace = await CardDecisionTraceStore(v2_db.session_factory).record(
        result,
        decision_id="decision_1",
        evidence_package_id="package_1",
    )
    assert trace.selected_card_refs_json == ["card:card_trace:v1"]
    assert trace.card_versions_json == {"card:card_trace": 1}
    assert trace.excluded_card_refs_json == ["card:card_trace_retired:v1"]
    assert trace.excluded_reasons_json["card:card_trace_retired:v1"] == ["RETIRED"]
    assert trace.candidate_count >= 2
    assert trace.trigger_signature_json["factors"]
    async with v2_db.session_factory() as session:
        stored = (
            await session.execute(select(GrowthCardDecisionTraceORM))
        ).scalars().all()
    assert len(stored) == 1


def test_retriever_import_graph_does_not_include_write_path():
    import crypto_trader.learning.growth_card_retrieval as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "growth_experience" not in source.split("def ", 1)[0]
