"""B1A: default evidence-domain isolation for Chief card retrieval."""
from __future__ import annotations

from crypto_trader.learning.growth_card_retrieval import (
    CardRankingPolicy,
    ExperienceCardRetriever,
)
from crypto_trader.learning.growth_v2_contracts import AdaptiveExperienceCard


def _card(rule_id, mode, account_id="default"):
    return AdaptiveExperienceCard(
        rule_id=rule_id, title=rule_id, content=rule_id,
        account_id=account_id, mode=mode, status="ACTIVE",
    )


def _reject(card, *, account_id="default", mode):
    return ExperienceCardRetriever(None, policy=CardRankingPolicy())._scope_rejection(
        card, account_id, mode
    )


def test_paper_default_rejects_live_and_backtest_cards():
    assert _reject(_card("card-paper", "PAPER"), mode="PAPER") == []
    assert _reject(_card("card-live", "LIVE"), mode="PAPER")
    assert _reject(_card("card-backtest", "BACKTEST"), mode="PAPER")


def test_live_default_rejects_paper_and_backtest_cards():
    assert _reject(_card("card-live", "LIVE"), mode="LIVE") == []
    assert _reject(_card("card-paper", "PAPER"), mode="LIVE")
    assert _reject(_card("card-backtest", "BACKTEST"), mode="LIVE")


def test_backtest_default_is_own_domain_and_account_isolated():
    assert _reject(_card("card-backtest", "BACKTEST"), mode="BACKTEST") == []
    assert _reject(_card("card-paper", "PAPER"), mode="BACKTEST")
    other = _card("card-paper-other", "PAPER", account_id="acct-b")
    assert _reject(other, account_id="acct-a", mode="PAPER") == [
        "ACCOUNT_MISMATCH"
    ]


def test_canonical_domain_weight_caps_are_enforced():
    from crypto_trader.learning.growth_domains import (
        domain_weight_cap,
        effective_evidence_weight,
    )

    assert domain_weight_cap("BACKTEST") == 0.40
    assert domain_weight_cap("PAPER") == 0.75
    assert domain_weight_cap("LIVE") == 1.00
    assert effective_evidence_weight(1.0, "BACKTEST") <= 0.40
    assert effective_evidence_weight(1.0, "PAPER") <= 0.75
    assert effective_evidence_weight(1.0, "LIVE") <= 1.00


async def test_b1a_paper_real_retriever_and_tool_path(v2_db):
    from decimal import Decimal

    from sqlalchemy import select

    from crypto_trader.learning.growth_card_retrieval import (
        CardRankingPolicy,
        ExperienceCardRetriever,
        register_experience_card_tool,
    )
    from crypto_trader.llm.tools.registry import LLMToolRegistry
    from crypto_trader.persistence.models import AICompressedExperienceORM
    from tests.growth_system_v2.conftest import (
        AS_OF,
        market_context,
        seed_card,
        trigger,
    )
    from tests.growth_system_v2.test_chief_card_integration import (
        _context,
        _tool_context,
    )

    rule_id = "card-b1a-paper-real"
    await seed_card(
        v2_db,
        rule_id=rule_id,
        account_id="default",
        mode="PAPER",
    )

    async with v2_db.session_factory() as session:
        row = (
            await session.execute(
                select(AICompressedExperienceORM).where(
                    AICompressedExperienceORM.rule_id == rule_id
                )
            )
        ).scalar_one()
        row.confidence = Decimal("1")
        await session.commit()

    async with v2_db.session_factory() as session:
        row = (
            await session.execute(
                select(AICompressedExperienceORM).where(
                    AICompressedExperienceORM.rule_id == rule_id
                )
            )
        ).scalar_one()
        before = {
            "rule_id": row.rule_id,
            "version": row.version,
            "status": row.status,
            "mode": row.mode,
            "account_id": row.account_id,
            "guidance_json": dict(row.guidance_json or {}),
            "support_count": row.support_count,
            "contradiction_count": row.contradiction_count,
            "source_episode_ids_json": list(row.source_episode_ids_json or []),
        }

    retriever = ExperienceCardRetriever(
        v2_db.session_factory,
        policy=CardRankingPolicy(),
    )
    result = await retriever.retrieve(
        trigger=trigger(),
        context=market_context(),
        as_of=AS_OF,
        account_id="default",
        mode="PAPER",
    )
    assert [item.rule_id for item in result.selected] == [rule_id]
    assert result.selected[0].card is not None
    assert result.selected[0].card.mode == "PAPER"

    registry = LLMToolRegistry()
    register_experience_card_tool(registry, retriever)
    tool_context = {
        **_tool_context(),
        "mode": "PAPER",
        "account_id": "default",
        "chief_context": _context(),
    }
    evidence = await registry.call(
        "experience_cards",
        "BTCUSDT",
        tool_context,
    )

    assert evidence.source_refs == [f"card:{rule_id}:v1"]
    assert evidence.data_quality == "FACTUAL_PUBLISHED"
    assert evidence.confidence_of_measurement == 1.0
    assert evidence.features["card_evidence_available"] is True

    cards = evidence.features["cards"]
    assert len(cards) == 1
    card = cards[0]
    assert card["rule_id"] == rule_id
    assert card["version"] == 1
    assert card["source_evidence_domain"] == "PAPER"
    assert card["runtime_validated"] is True
    assert card["domain_weight"] == 0.75
    assert card["effective_weight"] == 0.75
    assert card["evidence_only"] is True
    assert card["can_emit_direction"] is False

    groups = evidence.features["domain_groups"]
    assert "PAPER EXPERIENCE" in groups
    assert "HISTORICAL BACKTEST RESEARCH" not in groups

    async with v2_db.session_factory() as session:
        row = (
            await session.execute(
                select(AICompressedExperienceORM).where(
                    AICompressedExperienceORM.rule_id == rule_id
                )
            )
        ).scalar_one()
        after = {
            "rule_id": row.rule_id,
            "version": row.version,
            "status": row.status,
            "mode": row.mode,
            "account_id": row.account_id,
            "guidance_json": dict(row.guidance_json or {}),
            "support_count": row.support_count,
            "contradiction_count": row.contradiction_count,
            "source_episode_ids_json": list(row.source_episode_ids_json or []),
        }

    assert after == before

async def test_b1a_live_real_retriever_and_tool_path(v2_db):
    from decimal import Decimal

    from sqlalchemy import select

    from crypto_trader.learning.growth_card_retrieval import (
        CardRankingPolicy,
        ExperienceCardRetriever,
        register_experience_card_tool,
    )
    from crypto_trader.llm.tools.registry import LLMToolRegistry
    from crypto_trader.persistence.models import AICompressedExperienceORM
    from tests.growth_system_v2.conftest import (
        AS_OF,
        market_context,
        seed_card,
        trigger,
    )
    from tests.growth_system_v2.test_chief_card_integration import (
        _context,
        _tool_context,
    )

    rule_id = "card-b1a-live-real"
    await seed_card(
        v2_db,
        rule_id=rule_id,
        account_id="default",
        mode="LIVE",
    )

    async with v2_db.session_factory() as session:
        row = (
            await session.execute(
                select(AICompressedExperienceORM).where(
                    AICompressedExperienceORM.rule_id == rule_id
                )
            )
        ).scalar_one()
        row.confidence = Decimal("1")
        await session.commit()

    async with v2_db.session_factory() as session:
        row = (
            await session.execute(
                select(AICompressedExperienceORM).where(
                    AICompressedExperienceORM.rule_id == rule_id
                )
            )
        ).scalar_one()
        before = {
            "rule_id": row.rule_id,
            "version": row.version,
            "status": row.status,
            "mode": row.mode,
            "account_id": row.account_id,
            "guidance_json": dict(row.guidance_json or {}),
            "support_count": row.support_count,
            "contradiction_count": row.contradiction_count,
            "source_episode_ids_json": list(row.source_episode_ids_json or []),
        }

    retriever = ExperienceCardRetriever(
        v2_db.session_factory,
        policy=CardRankingPolicy(),
    )
    result = await retriever.retrieve(
        trigger=trigger(),
        context=market_context(),
        as_of=AS_OF,
        account_id="default",
        mode="LIVE",
    )
    assert [item.rule_id for item in result.selected] == [rule_id]
    assert result.selected[0].card is not None
    assert result.selected[0].card.mode == "LIVE"

    registry = LLMToolRegistry()
    register_experience_card_tool(registry, retriever)
    tool_context = {
        **_tool_context(),
        "mode": "LIVE",
        "account_id": "default",
        "chief_context": _context(),
    }
    evidence = await registry.call(
        "experience_cards",
        "BTCUSDT",
        tool_context,
    )

    assert evidence.source_refs == [f"card:{rule_id}:v1"]
    assert evidence.data_quality == "FACTUAL_PUBLISHED"
    assert evidence.confidence_of_measurement == 1.0
    assert evidence.features["card_evidence_available"] is True

    cards = evidence.features["cards"]
    assert len(cards) == 1
    card = cards[0]
    assert card["rule_id"] == rule_id
    assert card["version"] == 1
    assert card["source_evidence_domain"] == "LIVE"
    assert card["runtime_validated"] is True
    assert card["domain_weight"] == 1.0
    assert card["effective_weight"] == 1.0
    assert card["evidence_only"] is True
    assert card["can_emit_direction"] is False

    groups = evidence.features["domain_groups"]
    assert "LIVE EXPERIENCE" in groups
    assert "HISTORICAL BACKTEST RESEARCH" not in groups

    async with v2_db.session_factory() as session:
        row = (
            await session.execute(
                select(AICompressedExperienceORM).where(
                    AICompressedExperienceORM.rule_id == rule_id
                )
            )
        ).scalar_one()
        after = {
            "rule_id": row.rule_id,
            "version": row.version,
            "status": row.status,
            "mode": row.mode,
            "account_id": row.account_id,
            "guidance_json": dict(row.guidance_json or {}),
            "support_count": row.support_count,
            "contradiction_count": row.contradiction_count,
            "source_episode_ids_json": list(row.source_episode_ids_json or []),
        }

    assert after == before


async def test_b1a_backtest_real_retriever_and_tool_path(v2_db):
    from decimal import Decimal

    from sqlalchemy import select

    from crypto_trader.learning.growth_card_retrieval import (
        CardRankingPolicy,
        ExperienceCardRetriever,
        register_experience_card_tool,
    )
    from crypto_trader.llm.tools.registry import LLMToolRegistry
    from crypto_trader.persistence.models import AICompressedExperienceORM
    from tests.growth_system_v2.conftest import (
        AS_OF,
        market_context,
        seed_card,
        trigger,
    )
    from tests.growth_system_v2.test_chief_card_integration import (
        _context,
        _tool_context,
    )

    rule_id = "card-b1a-backtest-real"
    await seed_card(
        v2_db,
        rule_id=rule_id,
        account_id="default",
        mode="BACKTEST",
    )

    async with v2_db.session_factory() as session:
        row = (
            await session.execute(
                select(AICompressedExperienceORM).where(
                    AICompressedExperienceORM.rule_id == rule_id
                )
            )
        ).scalar_one()
        row.confidence = Decimal("1")
        await session.commit()

    async with v2_db.session_factory() as session:
        row = (
            await session.execute(
                select(AICompressedExperienceORM).where(
                    AICompressedExperienceORM.rule_id == rule_id
                )
            )
        ).scalar_one()
        before = {
            "rule_id": row.rule_id,
            "version": row.version,
            "status": row.status,
            "mode": row.mode,
            "account_id": row.account_id,
            "guidance_json": dict(row.guidance_json or {}),
            "support_count": row.support_count,
            "contradiction_count": row.contradiction_count,
            "source_episode_ids_json": list(row.source_episode_ids_json or []),
        }

    retriever = ExperienceCardRetriever(
        v2_db.session_factory,
        policy=CardRankingPolicy(),
    )
    result = await retriever.retrieve(
        trigger=trigger(),
        context=market_context(),
        as_of=AS_OF,
        account_id="default",
        mode="BACKTEST",
    )
    assert [item.rule_id for item in result.selected] == [rule_id]
    assert result.selected[0].card is not None
    assert result.selected[0].card.mode == "BACKTEST"

    registry = LLMToolRegistry()
    register_experience_card_tool(registry, retriever)
    tool_context = {
        **_tool_context(),
        "mode": "BACKTEST",
        "account_id": "default",
        "chief_context": _context(),
    }
    evidence = await registry.call(
        "experience_cards",
        "BTCUSDT",
        tool_context,
    )

    assert evidence.source_refs == [f"card:{rule_id}:v1"]
    assert evidence.data_quality == "FACTUAL_PUBLISHED"
    assert evidence.confidence_of_measurement == 1.0
    assert evidence.features["card_evidence_available"] is True

    cards = evidence.features["cards"]
    assert len(cards) == 1
    card = cards[0]
    assert card["rule_id"] == rule_id
    assert card["version"] == 1
    assert card["source_evidence_domain"] == "BACKTEST"
    assert card["runtime_validated"] is False
    assert card["domain_weight"] == 0.40
    assert card["effective_weight"] == 0.40
    assert card["evidence_only"] is True
    assert card["can_emit_direction"] is False

    groups = evidence.features["domain_groups"]
    assert "HISTORICAL BACKTEST RESEARCH" in groups
    assert "NOT_RUNTIME_VALIDATED" in groups
    assert "RUNTIME EXPERIENCE" not in groups

    async with v2_db.session_factory() as session:
        row = (
            await session.execute(
                select(AICompressedExperienceORM).where(
                    AICompressedExperienceORM.rule_id == rule_id
                )
            )
        ).scalar_one()
        after = {
            "rule_id": row.rule_id,
            "version": row.version,
            "status": row.status,
            "mode": row.mode,
            "account_id": row.account_id,
            "guidance_json": dict(row.guidance_json or {}),
            "support_count": row.support_count,
            "contradiction_count": row.contradiction_count,
            "source_episode_ids_json": list(row.source_episode_ids_json or []),
        }

    assert after == before

async def test_b1a_real_account_isolation(v2_db):
    from crypto_trader.learning.growth_card_retrieval import (
        CardRankingPolicy,
        ExperienceCardRetriever,
        register_experience_card_tool,
    )
    from crypto_trader.llm.tools.registry import LLMToolRegistry
    from tests.growth_system_v2.conftest import (
        AS_OF,
        market_context,
        seed_card,
        trigger,
    )
    from tests.growth_system_v2.test_chief_card_integration import (
        _context,
        _tool_context,
    )

    await seed_card(
        v2_db,
        rule_id="card-b1a-acct-a",
        account_id="acct-a",
        mode="PAPER",
    )
    await seed_card(
        v2_db,
        rule_id="card-b1a-acct-b",
        account_id="acct-b",
        mode="PAPER",
    )

    retriever = ExperienceCardRetriever(
        v2_db.session_factory,
        policy=CardRankingPolicy(),
    )
    result = await retriever.retrieve(
        trigger=trigger(),
        context=market_context(),
        as_of=AS_OF,
        account_id="acct-a",
        mode="PAPER",
    )
    assert [item.rule_id for item in result.selected] == [
        "card-b1a-acct-a"
    ]

    registry = LLMToolRegistry()
    register_experience_card_tool(registry, retriever)
    tool_context = {
        **_tool_context(),
        "mode": "PAPER",
        "account_id": "acct-a",
        "chief_context": _context(),
    }
    evidence = await registry.call(
        "experience_cards",
        "BTCUSDT",
        tool_context,
    )

    assert evidence.source_refs == ["card:card-b1a-acct-a:v1"]
    assert all(
        "card-b1a-acct-b" not in ref
        for ref in evidence.source_refs
    )

