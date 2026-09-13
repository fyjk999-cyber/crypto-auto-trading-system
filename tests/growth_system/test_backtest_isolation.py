"""BT01-BT15 hard evidence-domain isolation regressions."""

from __future__ import annotations

import dataclasses

import pytest

from crypto_trader.learning.growth_card_retrieval import (
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
from crypto_trader.learning.growth_v2_contracts import AdaptiveExperienceCard
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
