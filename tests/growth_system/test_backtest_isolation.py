"""BT01-BT15 hard evidence-domain isolation regressions."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from crypto_trader.learning.growth_backtest import (
    BacktestEpisodeAdapter,
    BacktestTrade,
)
from crypto_trader.learning.growth_card_retrieval import (
    CardDecisionTraceStore,
    CardRankingPolicy,
    ExperienceCardRetriever,
)
from crypto_trader.learning.growth_domains import (
    EVIDENCE_DOMAIN_BACKTEST,
    BacktestProvenanceError,
    domain_for_mode,
)
from crypto_trader.learning.growth_experience import card_rule_id
from crypto_trader.learning.growth_knowledge import (
    GrowthKnowledgePublisher,
    pattern_logical_id,
)
from crypto_trader.learning.growth_models import (
    create_growth_schema,
)
from crypto_trader.learning.growth_v2_contracts import (
    AdaptiveExperienceCard,
    CardRetrievalResult,
    ContextSignature,
    RetrievedCard,
    TriggerSignature,
)
from tests.growth_system.test_round2_publication_semantics import (
    KNOWN_AT,
    REGIME,
    STATEMENT_A,
    STATEMENT_B,
    SYMBOL,
    _attempt,
    _binding,
)

PROVENANCE = {
    "backtest_run_id": "bt-run-1",
    "strategy_version": "v1",
    "strategy_hash": "sha256:strategy",
    "dataset_id": "dataset-1",
    "dataset_hash": "sha256:dataset",
    "date_range": "2024-01-01:2025-01-01",
    "symbol": SYMBOL,
    "timeframe": "1h",
    "fee_model": "taker-0.05%",
    "slippage_model": "bps-2",
    "funding_model": "realized",
    "execution_model": "next-open",
    "parameter_set_hash": "sha256:params",
}


@pytest.fixture
async def growth_db(database):
    await create_growth_schema(database.engine)
    return database


@pytest.fixture
def publisher(growth_db):
    return GrowthKnowledgePublisher(growth_db.session_factory, min_pattern_samples=3)


def _domain_binding(*, mode: str, domain: str, provenance=None):
    binding = _binding()
    return dataclasses.replace(
        binding,
        mode=mode,
        evidence_domain=domain,
        backtest_provenance=provenance,
    )


def _domain_attempt(episode_id: str, *, mode: str, statement: str):
    attempt = _attempt(episode_id, statement=statement)
    return dataclasses.replace(attempt, mode=mode)


async def test_bt01_bt02_bt05_backtest_cannot_merge_or_validate_paper(
    growth_db, publisher
):
    backtest = [
        _domain_attempt(f"bt_{i}", mode="BACKTEST", statement=STATEMENT_A)
        for i in range(3)
    ]
    paper = [
        _domain_attempt(f"paper_{i}", mode="PAPER", statement=STATEMENT_A)
        for i in range(2)
    ]
    for attempt in backtest:
        await publisher.publish_review(
            attempt=attempt,
            binding=_domain_binding(
                mode="BACKTEST", domain=EVIDENCE_DOMAIN_BACKTEST, provenance=PROVENANCE
            ),
            known_at=KNOWN_AT,
        )
    for attempt in paper:
        await publisher.publish_review(
            attempt=attempt,
            binding=_domain_binding(mode="PAPER", domain="PAPER"),
            known_at=KNOWN_AT,
        )
    patterns = (
        await publisher.store.current_patterns_for_scope(
            account_id="default", mode="BACKTEST", symbol=SYMBOL, regime=REGIME
        )
        + await publisher.store.current_patterns_for_scope(
            account_id="default", mode="PAPER", symbol=SYMBOL, regime=REGIME
        )
    )
    assert len({row.pattern_id for row in patterns}) == 2
    by_mode = {row.mode: row for row in patterns}
    assert by_mode["BACKTEST"].status == "VALIDATED"
    assert by_mode["PAPER"].status == "CANDIDATE"
    assert by_mode["BACKTEST"].sample_count == 3
    assert by_mode["PAPER"].sample_count == 2
    assert by_mode["BACKTEST"].pattern_id != by_mode["PAPER"].pattern_id
    assert by_mode["BACKTEST"].scope_json["evidence_domain"] == "BACKTEST"
    assert by_mode["PAPER"].scope_json["evidence_domain"] == "PAPER"


async def test_bt05_logical_ids_include_evidence_domain():
    assert pattern_logical_id(
        "default", "PAPER", SYMBOL, REGIME, "LONG", "prop", "PAPER"
    ) != pattern_logical_id(
        "default", "PAPER", SYMBOL, REGIME, "LONG", "prop", "BACKTEST"
    )


async def test_bt14_backtest_provenance_required(growth_db, publisher):
    attempt = _domain_attempt("bt_missing_prov", mode="BACKTEST", statement=STATEMENT_A)
    with pytest.raises(BacktestProvenanceError):
        await publisher.publish_review(
            attempt=attempt,
            binding=_domain_binding(
                mode="BACKTEST", domain=EVIDENCE_DOMAIN_BACKTEST, provenance={}
            ),
            known_at=KNOWN_AT,
        )
    patterns = await publisher.store.current_patterns_for_scope(
        account_id="default", mode="BACKTEST", symbol=SYMBOL, regime=REGIME
    )
    assert patterns == []


async def test_bt10_bt11_revocation_is_domain_scoped(growth_db, publisher):
    for index in range(3):
        await publisher.publish_review(
            attempt=_domain_attempt(
                f"bt_rev_{index}", mode="BACKTEST", statement=STATEMENT_A
            ),
            binding=_domain_binding(
                mode="BACKTEST", domain=EVIDENCE_DOMAIN_BACKTEST, provenance=PROVENANCE
            ),
            known_at=KNOWN_AT,
        )
    for index in range(3):
        await publisher.publish_review(
            attempt=_domain_attempt(
                f"paper_rev_{index}", mode="PAPER", statement=STATEMENT_A
            ),
            binding=_domain_binding(mode="PAPER", domain="PAPER"),
            known_at=KNOWN_AT,
        )
    backtest = (
        await publisher.store.current_patterns_for_scope(
            account_id="default", mode="BACKTEST", symbol=SYMBOL, regime=REGIME
        )
    )[0]
    await publisher.revoke(
        kind="pattern", logical_id=backtest.pattern_id, reason="BT10", at=KNOWN_AT
    )
    paper = (
        await publisher.store.current_patterns_for_scope(
            account_id="default", mode="PAPER", symbol=SYMBOL, regime=REGIME
        )
    )
    assert paper and paper[0].status == "VALIDATED"


async def test_bt12_compression_never_combines_domains(growth_db, publisher):
    for index in range(3):
        await publisher.publish_review(
            attempt=_domain_attempt(
                f"bt_comp_{index}", mode="BACKTEST", statement=STATEMENT_A
            ),
            binding=_domain_binding(
                mode="BACKTEST", domain=EVIDENCE_DOMAIN_BACKTEST, provenance=PROVENANCE
            ),
            known_at=KNOWN_AT,
        )
    for index in range(3):
        await publisher.publish_review(
            attempt=_domain_attempt(
                f"paper_comp_{index}", mode="PAPER", statement=STATEMENT_B
            ),
            binding=_domain_binding(mode="PAPER", domain="PAPER"),
            known_at=KNOWN_AT,
        )
    paper_compression = await publisher.compress(
        account_id="default", mode="PAPER", symbol=SYMBOL, regime=REGIME
    )
    backtest_compression = await publisher.compress(
        account_id="default", mode="BACKTEST", symbol=SYMBOL, regime=REGIME
    )
    assert STATEMENT_B in paper_compression.content
    assert STATEMENT_A not in paper_compression.content
    assert STATEMENT_A in backtest_compression.content
    assert STATEMENT_B not in backtest_compression.content


def test_bt08_domain_mapping_labels():
    assert domain_for_mode("BACKTEST") == "BACKTEST"
    assert domain_for_mode("PAPER") == "PAPER"
    assert domain_for_mode("LIVE") == "LIVE"
    assert domain_for_mode("SIMULATION") == "PAPER"


def test_bt06_bt07_card_identity_and_retrieval_domain_policy():
    paper_id = card_rule_id(
        experience_type="ADAPTIVE_CARD",
        trigger=None,
        context=None,
        guidance={"summary": "same"},
        namespace="default:PAPER:PAPER",
    )
    backtest_id = card_rule_id(
        experience_type="ADAPTIVE_CARD",
        trigger=None,
        context=None,
        guidance={"summary": "same"},
        namespace="default:BACKTEST:BACKTEST",
    )
    assert paper_id != backtest_id

    retriever = ExperienceCardRetriever(
        None, policy=CardRankingPolicy(allowed_evidence_domains=("PAPER",))
    )
    backtest_card = AdaptiveExperienceCard(
        rule_id="card_bt",
        title="bt",
        content="x",
        account_id="default",
        mode="BACKTEST",
    )
    assert retriever._scope_rejection(backtest_card, "default", "BACKTEST") == [
        "EVIDENCE_DOMAIN_NOT_ALLOWED:BACKTEST"
    ]
    paper_card = AdaptiveExperienceCard(
        rule_id="card_paper",
        title="paper",
        content="x",
        account_id="default",
        mode="PAPER",
    )
    assert retriever._scope_rejection(paper_card, "default", "PAPER") == []


async def test_bt03_bt04_domain_metrics_stay_separate(growth_db, publisher):
    for i in range(3):
        await publisher.publish_review(
            attempt=_domain_attempt(f"bt_metrics_{i}", mode="BACKTEST", statement=STATEMENT_A),
            binding=_domain_binding(
                mode="BACKTEST",
                domain=EVIDENCE_DOMAIN_BACKTEST,
                provenance=PROVENANCE,
            ),
            known_at=KNOWN_AT,
        )
    for i in range(2):
        await publisher.publish_review(
            attempt=_domain_attempt(f"paper_metrics_{i}", mode="PAPER", statement=STATEMENT_A),
            binding=_domain_binding(mode="PAPER", domain="PAPER"),
            known_at=KNOWN_AT,
        )
    bt = (
        await publisher.store.current_patterns_for_scope(
            account_id="default", mode="BACKTEST", symbol=SYMBOL, regime=REGIME
        )
    )[0]
    paper = (
        await publisher.store.current_patterns_for_scope(
            account_id="default", mode="PAPER", symbol=SYMBOL, regime=REGIME
        )
    )[0]
    assert bt.sample_count == 3 and bt.status == "VALIDATED"
    assert paper.sample_count == 2 and paper.status == "CANDIDATE"
    assert bt.support_count == 3 and paper.support_count == 2


def test_bt08_default_policy_excludes_backtest_but_explicit_research_allows_it():
    retriever = ExperienceCardRetriever(None, policy=CardRankingPolicy())
    backtest_card = AdaptiveExperienceCard(
        rule_id="card_bt_research",
        title="bt",
        content="x",
        account_id="default",
        mode="BACKTEST",
    )
    # Default PAPER policy: own domain only.
    assert retriever._scope_rejection(backtest_card, "default", "BACKTEST") == []
    paper_retriever = ExperienceCardRetriever(
        None, policy=CardRankingPolicy(allowed_evidence_domains=("PAPER",))
    )
    assert paper_retriever._scope_rejection(backtest_card, "default", "BACKTEST") == [
        "EVIDENCE_DOMAIN_NOT_ALLOWED:BACKTEST"
    ]
    research_policy = ExperienceCardRetriever(
        None,
        policy=CardRankingPolicy(
            allowed_evidence_domains=("PAPER", "BACKTEST")
        ),
    )
    assert research_policy._scope_rejection(backtest_card, "default", "BACKTEST") == []


async def test_bt13_domain_divergence_keeps_state_separate(growth_db, publisher):
    for i in range(3):
        await publisher.publish_review(
            attempt=_domain_attempt(f"bt_div_{i}", mode="BACKTEST", statement=STATEMENT_A),
            binding=_domain_binding(
                mode="BACKTEST", domain=EVIDENCE_DOMAIN_BACKTEST, provenance=PROVENANCE
            ),
            known_at=KNOWN_AT,
        )
    await publisher.publish_review(
        attempt=_domain_attempt("paper_div_0", mode="PAPER", statement=STATEMENT_A),
        binding=_domain_binding(mode="PAPER", domain="PAPER"),
        known_at=KNOWN_AT,
    )
    bt = (
        await publisher.store.current_patterns_for_scope(
            account_id="default", mode="BACKTEST", symbol=SYMBOL, regime=REGIME
        )
    )[0]
    paper = (
        await publisher.store.current_patterns_for_scope(
            account_id="default", mode="PAPER", symbol=SYMBOL, regime=REGIME
        )
    )[0]
    assert bt.pattern_id != paper.pattern_id
    assert bt.status == "VALIDATED" and paper.status == "CANDIDATE"


async def test_bt15_duplicate_backtest_identity_counts_once(growth_db, publisher):
    identity = "bt_identity_duplicate"
    for i in range(2):
        binding = dataclasses.replace(
            _binding(),
            mode="BACKTEST",
            evidence_domain=EVIDENCE_DOMAIN_BACKTEST,
            backtest_provenance=PROVENANCE,
            backtest_evidence_identity=identity,
        )
        await publisher.publish_review(
            attempt=_domain_attempt(
                f"bt_dup_{i}", mode="BACKTEST", statement=STATEMENT_A
            ),
            binding=binding,
            known_at=KNOWN_AT,
        )
    patterns = await publisher.store.current_patterns_for_scope(
        account_id="default", mode="BACKTEST", symbol=SYMBOL, regime=REGIME
    )
    assert patterns
    assert patterns[0].sample_count == 1
    assert patterns[0].independent_sample_count == 1


async def test_bt09_trace_first_class_domain_provenance(growth_db):
    now = datetime(2026, 9, 13, 12, tzinfo=UTC)
    trigger = TriggerSignature.from_factor_states([], as_of=now)
    context = ContextSignature.from_market_state({}, as_of=now, symbol=SYMBOL)
    card = AdaptiveExperienceCard(
        rule_id="card_trace_domain",
        title="paper",
        content="x",
        account_id="default",
        mode="PAPER",
        confidence=0.5,
    )
    result = CardRetrievalResult(
        as_of=now,
        trigger=trigger,
        context=context,
        selected=[
            RetrievedCard(
                rule_id=card.rule_id,
                version=1,
                status="ACTIVE",
                score=0.5,
                components={},
                why=["TEST"],
                card=card,
            )
        ],
        metrics={"policy_fingerprint": "policy-test"},
    )
    store = CardDecisionTraceStore(growth_db.session_factory)
    trace = await store.record(
        result,
        decision_id=None,
        evidence_package_id=None,
        account_id="default",
        mode="PAPER",
    )
    async with growth_db.session_factory() as session:
        from crypto_trader.learning.growth_models import GrowthCardDecisionTraceORM

        row = await session.get(GrowthCardDecisionTraceORM, trace.trace_id)
    provenance = row.applicability_json["_domain_provenance"]
    assert provenance[0]["evidence_ref"] == "card:card_trace_domain:v1"
    assert provenance[0]["evidence_domain"] == "PAPER"
    assert provenance[0]["domain_weight"] == 0.75
    assert row.applicability_json["_decision_evidence_domain"] == "PAPER"


def test_bt14_backtest_adapter_produces_isolated_canonical_episode():
    trade = BacktestTrade(
        episode_id="bt-trade-1",
        symbol=SYMBOL,
        direction="LONG",
        entry_price=Decimal("100"),
        exit_price=Decimal("101"),
        quantity=Decimal("1"),
        leverage=Decimal("1"),
        fees=Decimal("0"),
        funding_pnl=Decimal("0"),
        gross_pnl=Decimal("1"),
        net_pnl=Decimal("1"),
        holding_time_seconds=60.0,
        entry_market_regime="TREND_UP",
        terminal_reason="EXIT",
        opened_at=KNOWN_AT,
        closed_at=KNOWN_AT,
        provenance=PROVENANCE,
    )
    adapter = BacktestEpisodeAdapter()
    episode = adapter.to_factual_episode(trade)
    binding = adapter.to_binding(trade, canonical_regime="TRENDING")
    assert episode.episode_id == "bt-trade-1"
    assert binding.mode == "BACKTEST"
    assert binding.evidence_domain == "BACKTEST"
    assert adapter.evidence_identity(trade) == adapter.evidence_identity(trade)
    bad = dataclasses.replace(trade, provenance={})
    try:
        adapter.to_factual_episode(bad)
    except BacktestProvenanceError:
        pass
    else:
        raise AssertionError("missing provenance must block BACKTEST publication")
