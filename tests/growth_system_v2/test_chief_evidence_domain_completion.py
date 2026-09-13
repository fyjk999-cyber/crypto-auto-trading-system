"""Mission B: explicit domains, immutable trace, and pure rendering."""

from __future__ import annotations

import re
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256

from sqlalchemy import func, select

from crypto_trader.learning.growth_card_retrieval import (
    CardDecisionTraceStore,
    CardRankingPolicy,
    ExperienceCardRetriever,
    render_experience_domains,
)
from crypto_trader.learning.growth_domains import DOMAIN_WEIGHT_CAPS
from crypto_trader.learning.growth_models import (
    GrowthCardDecisionTraceORM,
    GrowthToolSelectionORM,
)
from crypto_trader.learning.growth_retrieval import GrowthContextLoader
from crypto_trader.llm.tools.registry import LLMToolRegistry
from crypto_trader.llm_chief.engine import ChiefTraderEngine
from crypto_trader.llm_chief.tool_orchestrator import ToolDrivenChiefTrader
from crypto_trader.persistence.models import (
    AICompressedExperienceORM,
    FillORM,
    OrderORM,
    TradeEpisodeORM,
)
from tests.growth_system_v2.conftest import AS_OF, market_context, seed_card, trigger
from tests.growth_system_v2.test_chief_card_integration import (
    ScriptedProvider,
    _context,
    _tool_context,
)


async def _set_confidence(v2_db, rule_id: str, confidence: str) -> None:
    async with v2_db.session_factory() as session:
        row = (
            await session.execute(
                select(AICompressedExperienceORM).where(
                    AICompressedExperienceORM.rule_id == rule_id
                )
            )
        ).scalar_one()
        row.confidence = Decimal(confidence)
        await session.commit()


async def test_explicit_backtest_visibility_keeps_domains_separate(v2_db):
    await seed_card(v2_db, rule_id="paper-explicit", mode="PAPER")
    await seed_card(v2_db, rule_id="backtest-explicit", mode="BACKTEST")
    await seed_card(v2_db, rule_id="live-hidden", mode="LIVE")
    retriever = ExperienceCardRetriever(
        v2_db.session_factory,
        policy=CardRankingPolicy(
            top_k=3,
            allowed_evidence_domains=("PAPER", "BACKTEST"),
        ),
    )

    result = await retriever.retrieve(
        trigger=trigger(),
        context=market_context(),
        as_of=AS_OF,
        account_id="default",
        mode="PAPER",
    )

    selected = {item.rule_id: item.card.mode for item in result.selected}
    assert selected == {
        "backtest-explicit": "BACKTEST",
        "paper-explicit": "PAPER",
    }
    assert "live-hidden" not in selected


async def test_explicit_backtest_visibility_preserves_account_isolation(v2_db):
    await seed_card(
        v2_db,
        rule_id="backtest-acct-a",
        mode="BACKTEST",
        account_id="acct-a",
    )
    await seed_card(
        v2_db,
        rule_id="backtest-acct-b",
        mode="BACKTEST",
        account_id="acct-b",
    )
    retriever = ExperienceCardRetriever(
        v2_db.session_factory,
        policy=CardRankingPolicy(
            allowed_evidence_domains=("PAPER", "BACKTEST")
        ),
    )

    result = await retriever.retrieve(
        trigger=trigger(),
        context=market_context(),
        as_of=AS_OF,
        account_id="acct-a",
        mode="PAPER",
    )

    assert [item.rule_id for item in result.selected] == ["backtest-acct-a"]


async def test_selected_evidence_trace_is_exact_and_reconstructable(v2_db):
    await seed_card(v2_db, rule_id="paper-trace", mode="PAPER")
    await _set_confidence(v2_db, "paper-trace", "0.8")
    policy = CardRankingPolicy()
    result = await ExperienceCardRetriever(
        v2_db.session_factory,
        policy=policy,
    ).retrieve(
        trigger=trigger(),
        context=market_context(),
        as_of=AS_OF,
        account_id="default",
        mode="PAPER",
    )
    trace = await CardDecisionTraceStore(v2_db.session_factory).record(
        result,
        decision_id="decision-mission-b",
        evidence_package_id="package-mission-b",
    )

    snapshot = trace.selected_evidence_json[0]
    assert snapshot == {
        "schema_version": 1,
        "evidence_ref": "card:paper-trace:v1",
        "card_id": "paper-trace",
        "card_version": 1,
        "evidence_domain": "PAPER",
        "runtime_validated": True,
        "internal_confidence": 0.8,
        "domain_weight": 0.75,
        "effective_weight": 0.6,
        "ranking_score": result.selected[0].score,
        "policy_fingerprint": policy.fingerprint(),
    }
    async with v2_db.session_factory() as session:
        stored = await session.get(GrowthCardDecisionTraceORM, trace.trace_id)
    assert stored.selected_evidence_json == [snapshot]


def test_policy_fingerprint_binds_domain_caps(monkeypatch):
    before = CardRankingPolicy().fingerprint()
    monkeypatch.setitem(DOMAIN_WEIGHT_CAPS, "BACKTEST", 0.39)
    after = CardRankingPolicy().fingerprint()
    assert after != before


def test_domain_renderer_is_pure_and_deterministic():
    cards = [
        {
            "evidence_ref": "card:z-backtest:v2",
            "rule_id": "z-backtest",
            "version": 2,
            "source_evidence_domain": "BACKTEST",
            "runtime_validated": False,
            "internal_confidence": 1.0,
            "domain_weight": 0.4,
            "effective_weight": 0.4,
            "ranking_score": 0.9,
        },
        {
            "evidence_ref": "card:a-paper:v1",
            "rule_id": "a-paper",
            "version": 1,
            "source_evidence_domain": "PAPER",
            "runtime_validated": True,
            "internal_confidence": 0.7,
            "domain_weight": 0.75,
            "effective_weight": 0.525,
            "ranking_score": 0.8,
        },
    ]
    original = [dict(item) for item in cards]

    rendered = render_experience_domains(list(reversed(cards)))

    assert cards == original
    assert "CURRENT_RUNTIME_EXPERIENCE" in rendered
    assert "HISTORICAL_BACKTEST_EVIDENCE" in rendered
    assert "NOT_RUNTIME_VALIDATED" in rendered
    assert "card:a-paper:v1" in rendered
    assert "card:z-backtest:v2" in rendered
    assert rendered == render_experience_domains(cards)


def _prompt_card_refs(prompt: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"card:[A-Za-z0-9_-]+:v\d+", prompt)))


async def _invoke_actual_chief(
    v2_db,
    *,
    mode: str,
    policy: CardRankingPolicy,
):
    from crypto_trader.learning.growth_card_retrieval import (
        CardDecisionTraceStore,
        ExperienceCardRetriever,
        register_experience_card_tool,
    )

    registry = LLMToolRegistry()
    trace_store = CardDecisionTraceStore(v2_db.session_factory)
    register_experience_card_tool(
        registry,
        ExperienceCardRetriever(v2_db.session_factory, policy=policy),
        trace_store=trace_store,
    )
    provider = ScriptedProvider(["experience_cards"])
    recorder = GrowthContextLoader(
        v2_db.session_factory,
        account_id="default",
        mode=mode,
    )
    chief = ToolDrivenChiefTrader(
        ChiefTraderEngine(provider=provider),
        registry,
        selection_recorder=recorder,
        card_trace_store=trace_store,
    )
    tool_context = {**_tool_context(), "mode": mode}
    decision, package = await chief.decide(
        _context(),
        tool_context=tool_context,
        now=AS_OF,
    )
    return decision, package, provider


async def test_actual_paper_chief_prompt_trace_and_tool_selection_match(v2_db):
    await seed_card(v2_db, rule_id="paper-chief", mode="PAPER")
    await seed_card(v2_db, rule_id="backtest-hidden-chief", mode="BACKTEST")

    decision, package, provider = await _invoke_actual_chief(
        v2_db,
        mode="PAPER",
        policy=CardRankingPolicy(),
    )

    assert package is not None
    prompt = provider.calls[-1]["prompt"]
    prompt_refs = _prompt_card_refs(prompt)
    assert prompt_refs == ["card:paper-chief:v1"]
    assert "backtest-hidden-chief" not in prompt
    async with v2_db.session_factory() as session:
        trace = (await session.execute(select(GrowthCardDecisionTraceORM))).scalar_one()
        selection = (await session.execute(select(GrowthToolSelectionORM))).scalar_one()
        orders = await session.scalar(select(func.count()).select_from(OrderORM))
        fills = await session.scalar(select(func.count()).select_from(FillORM))
        episodes = await session.scalar(select(func.count()).select_from(TradeEpisodeORM))
    assert trace.selected_card_refs_json == prompt_refs
    assert trace.decision_id == decision.decision_id
    assert selection.decision_id == decision.decision_id
    assert selection.returned_refs_json == prompt_refs
    assert selection.prompt_hash == sha256(prompt.encode()).hexdigest()
    assert orders == fills == episodes == 0


async def test_actual_live_chief_default_is_live_only(v2_db):
    await seed_card(v2_db, rule_id="live-chief", mode="LIVE")
    await seed_card(v2_db, rule_id="paper-hidden-live-chief", mode="PAPER")
    await seed_card(v2_db, rule_id="backtest-hidden-live-chief", mode="BACKTEST")

    _decision, package, provider = await _invoke_actual_chief(
        v2_db,
        mode="LIVE",
        policy=CardRankingPolicy(),
    )

    assert package is not None
    prompt = provider.calls[-1]["prompt"]
    assert _prompt_card_refs(prompt) == ["card:live-chief:v1"]
    assert "paper-hidden-live-chief" not in prompt
    assert "backtest-hidden-live-chief" not in prompt


async def test_actual_paper_chief_renders_explicit_backtest_separately(v2_db):
    await seed_card(v2_db, rule_id="paper-current", mode="PAPER")
    await seed_card(v2_db, rule_id="backtest-history", mode="BACKTEST")

    decision, package, provider = await _invoke_actual_chief(
        v2_db,
        mode="PAPER",
        policy=CardRankingPolicy(
            top_k=3,
            allowed_evidence_domains=("PAPER", "BACKTEST"),
        ),
    )

    assert package is not None
    prompt = provider.calls[-1]["prompt"]
    assert "CURRENT_RUNTIME_EXPERIENCE" in prompt
    assert "HISTORICAL_BACKTEST_EVIDENCE" in prompt
    assert "NOT_RUNTIME_VALIDATED" in prompt
    prompt_refs = _prompt_card_refs(prompt)
    async with v2_db.session_factory() as session:
        trace = (await session.execute(select(GrowthCardDecisionTraceORM))).scalar_one()
        selection = (await session.execute(select(GrowthToolSelectionORM))).scalar_one()
    assert prompt_refs == trace.selected_card_refs_json
    assert prompt_refs == selection.returned_refs_json
    assert trace.decision_id == selection.decision_id == decision.decision_id
    assert {item["evidence_domain"] for item in trace.selected_evidence_json} == {
        "PAPER",
        "BACKTEST",
    }
    assert next(
        item
        for item in trace.selected_evidence_json
        if item["evidence_domain"] == "BACKTEST"
    )["effective_weight"] <= 0.4


async def test_policy_and_domain_cap_changes_rekey_trace(v2_db, monkeypatch):
    await seed_card(v2_db, rule_id="trace-policy-card", mode="PAPER")
    store = CardDecisionTraceStore(v2_db.session_factory)

    default_result = await ExperienceCardRetriever(
        v2_db.session_factory,
        policy=CardRankingPolicy(),
    ).retrieve(
        trigger=trigger(),
        context=market_context(),
        as_of=AS_OF,
    )
    original = await store.record(
        default_result,
        decision_id=None,
        evidence_package_id=None,
        trace_id_override="mission-b-trace-override",
    )
    repeated = await store.record(
        default_result,
        decision_id=None,
        evidence_package_id=None,
        trace_id_override="mission-b-trace-override",
    )
    assert repeated.trace_id == original.trace_id

    explicit_result = await ExperienceCardRetriever(
        v2_db.session_factory,
        policy=CardRankingPolicy(allowed_evidence_domains=("PAPER",)),
    ).retrieve(
        trigger=trigger(),
        context=market_context(),
        as_of=AS_OF,
    )
    explicit = await store.record(
        explicit_result,
        decision_id=None,
        evidence_package_id=None,
        trace_id_override="mission-b-trace-override",
    )
    assert explicit.trace_id != original.trace_id

    monkeypatch.setitem(DOMAIN_WEIGHT_CAPS, "PAPER", 0.7)
    cap_result = await ExperienceCardRetriever(
        v2_db.session_factory,
        policy=CardRankingPolicy(),
    ).retrieve(
        trigger=trigger(),
        context=market_context(),
        as_of=AS_OF,
    )
    cap_changed = await store.record(
        cap_result,
        decision_id=None,
        evidence_package_id=None,
        trace_id_override="mission-b-trace-override",
    )
    assert cap_changed.trace_id not in {original.trace_id, explicit.trace_id}
    assert cap_changed.selected_evidence_json[0]["domain_weight"] == 0.7


async def test_high_confidence_backtest_never_escapes_historical_cap(v2_db):
    await seed_card(v2_db, rule_id="paper-lower-confidence", mode="PAPER")
    await seed_card(v2_db, rule_id="backtest-high-confidence", mode="BACKTEST")
    await _set_confidence(v2_db, "paper-lower-confidence", "0.5")
    await _set_confidence(v2_db, "backtest-high-confidence", "1")
    result = await ExperienceCardRetriever(
        v2_db.session_factory,
        policy=CardRankingPolicy(
            top_k=3,
            allowed_evidence_domains=("PAPER", "BACKTEST"),
        ),
    ).retrieve(
        trigger=trigger(),
        context=market_context(),
        as_of=AS_OF,
    )
    trace = await CardDecisionTraceStore(v2_db.session_factory).record(
        result,
        decision_id="decision-domain-cap",
        evidence_package_id=None,
    )
    by_domain = {
        item["evidence_domain"]: item for item in trace.selected_evidence_json
    }
    assert by_domain["BACKTEST"]["internal_confidence"] == 1.0
    assert by_domain["BACKTEST"]["effective_weight"] == 0.4
    assert by_domain["PAPER"]["effective_weight"] == 0.375
    assert by_domain["BACKTEST"]["runtime_validated"] is False


async def test_historical_replay_uses_visible_card_version_deterministically(v2_db):
    await seed_card(v2_db, rule_id="historical-card", mode="PAPER")
    async with v2_db.session_factory() as session:
        row = (
            await session.execute(
                select(AICompressedExperienceORM).where(
                    AICompressedExperienceORM.rule_id == "historical-card"
                )
            )
        ).scalar_one()
        row.version = 2
        row.guidance_json = {"summary": "future update", "direction": "SHORT"}
        row.updated_at = AS_OF + timedelta(days=1)
        row.known_at = AS_OF + timedelta(days=1)
        await session.commit()

    retriever = ExperienceCardRetriever(v2_db.session_factory)
    first = await retriever.retrieve(
        trigger=trigger(),
        context=market_context(),
        as_of=AS_OF,
    )
    second = await retriever.retrieve(
        trigger=trigger(),
        context=market_context(),
        as_of=AS_OF,
    )

    def replay_identity(result):
        return [
            (
                item.rule_id,
                item.version,
                item.score,
                item.card.mode,
                item.card.guidance,
            )
            for item in result.selected
        ]

    assert replay_identity(first) == replay_identity(second)
    assert replay_identity(first) == [
        (
            "historical-card",
            1,
            first.selected[0].score,
            "PAPER",
            {
                "summary": "Funding extreme in bull regime",
                "direction": "LONG",
                "evidence_domain": "PAPER",
            },
        )
    ]
