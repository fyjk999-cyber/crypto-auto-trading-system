"""I02: account/mode fail-closed isolation tests."""

from __future__ import annotations

from sqlalchemy import select

from crypto_trader.learning.growth_card_retrieval import ExperienceCardRetriever
from crypto_trader.persistence.models import AICompressedExperienceORM
from tests.growth_system_v2.conftest import AS_OF, market_context, seed_card, trigger


async def test_cross_account_and_cross_mode_cards_are_ineligible(v2_db):
    await seed_card(v2_db, rule_id="card_acct_a", account_id="acct-a", mode="PAPER")
    retriever = ExperienceCardRetriever(v2_db.session_factory)
    for account_id, mode in (
        ("acct-b", "PAPER"),
        ("acct-a", "LIVE"),
        ("acct-b", "LIVE"),
    ):
        result = await retriever.retrieve(
            trigger=trigger(),
            context=market_context(),
            as_of=AS_OF,
            account_id=account_id,
            mode=mode,
        )
        assert result.selected == [], (account_id, mode, result.excluded_reasons)
    same = await retriever.retrieve(
        trigger=trigger(),
        context=market_context(),
        as_of=AS_OF,
        account_id="acct-a",
        mode="PAPER",
    )
    assert [item.rule_id for item in same.selected] == ["card_acct_a"]


async def test_missing_scope_is_unknown_not_global(v2_db):
    await seed_card(v2_db, rule_id="card_missing_scope")
    async with v2_db.session_factory() as session:
        row = (
            await session.execute(
                select(AICompressedExperienceORM).where(
                    AICompressedExperienceORM.rule_id == "card_missing_scope"
                )
            )
        ).scalar_one()
        row.account_id = ""
        row.mode = ""
        row.share_scope = "UNKNOWN"
        await session.commit()
    retriever = ExperienceCardRetriever(v2_db.session_factory)
    result = await retriever.retrieve(
        trigger=trigger(),
        context=market_context(),
        as_of=AS_OF,
        account_id="default",
        mode="PAPER",
    )
    assert result.selected == []
    ref = "card:card_missing_scope:v1"
    assert ref in result.excluded_reasons
    assert any(
        reason in {"ACCOUNT_UNKNOWN", "MODE_UNKNOWN", "SHARE_SCOPE_UNKNOWN:UNKNOWN"}
        for reason in result.excluded_reasons[ref]
    )


async def test_explicit_global_scope_requires_approval_marker(v2_db):
    await seed_card(
        v2_db,
        rule_id="card_global_approved",
        share_scope="GLOBAL_EXPLICIT",
    )
    await seed_card(
        v2_db,
        rule_id="card_global_unapproved",
        share_scope="GLOBAL_EXPLICIT",
    )
    async with v2_db.session_factory() as session:
        approved = (
            await session.execute(
                select(AICompressedExperienceORM).where(
                    AICompressedExperienceORM.rule_id == "card_global_approved"
                )
            )
        ).scalar_one()
        approved.applicability_scope_json = {
            "scope": "GLOBAL",
            "sharing": "GLOBAL_EXPLICIT",
            "approved_by": "integration-owner",
        }
        unapproved = (
            await session.execute(
                select(AICompressedExperienceORM).where(
                    AICompressedExperienceORM.rule_id == "card_global_unapproved"
                )
            )
        ).scalar_one()
        unapproved.applicability_scope_json = {
            "scope": "GLOBAL",
            "sharing": "GLOBAL_EXPLICIT",
        }
        await session.commit()

    result = await ExperienceCardRetriever(v2_db.session_factory).retrieve(
        trigger=trigger(),
        context=market_context(),
        as_of=AS_OF,
        account_id="acct-other",
        mode="LIVE",
    )
    assert [item.rule_id for item in result.selected] == ["card_global_approved"]
    assert "GLOBAL_SCOPE_NOT_APPROVED" in result.excluded_reasons[
        "card:card_global_unapproved:v1"
    ]


async def test_scope_rejection_reasons_direct(v2_db):
    await seed_card(v2_db, rule_id="card_scope_direct", account_id="acct-a", mode="LIVE")
    from crypto_trader.learning.growth_experience import AdaptiveCardStore

    card = await AdaptiveCardStore(v2_db.session_factory).get_card("card_scope_direct")
    retriever = ExperienceCardRetriever(v2_db.session_factory)
    assert retriever._scope_rejection(card, "acct-b", "LIVE") == ["ACCOUNT_MISMATCH"]
    assert retriever._scope_rejection(card, "acct-a", "PAPER") == ["MODE_MISMATCH"]
    assert retriever._scope_rejection(card, "acct-a", "LIVE") == []
