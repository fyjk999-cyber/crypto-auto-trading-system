"""TEST_ONLY fixtures for Growth System V2 (cards / trigger / retrieval)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from crypto_trader.learning.growth_models import create_growth_schema
from crypto_trader.learning.growth_v2_contracts import (
    STATUS_ACTIVE,
    CardUpdateProposal,
    ContextSignature,
    TriggerSignature,
)
from crypto_trader.learning.growth_v2_migration import upgrade_experience_card_schema
from tests.growth_system.conftest import assert_test_database_path  # noqa: F401

AS_OF = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)


@pytest.fixture
async def v2_db(database):
    await create_growth_schema(database.engine)
    await upgrade_experience_card_schema(database.engine)
    return database


def trigger(
    *,
    funding: str = "EXTREME_HIGH",
    oi: str = "RISING",
    definition_version: str = "funding-def-v1",
    as_of: datetime = AS_OF,
) -> TriggerSignature:
    return TriggerSignature.from_factor_states(
        [
            {
                "factor_id": "funding_rate",
                "state": funding,
                "definition_version": definition_version,
            },
            {
                "factor_id": "open_interest",
                "state": oi,
                "definition_version": "oi-def-v1",
            },
        ],
        as_of=as_of,
    )


def market_context(
    *,
    symbol: str = "BTCUSDT",
    regime: str = "BULL",
    direction: str = "LONG",
    as_of: datetime = AS_OF,
    instrument_class: str = "LINEAR_PERP",
    timeframe: str = "1h",
) -> ContextSignature:
    return ContextSignature.from_market_state(
        {
            "symbol": symbol,
            "instrument_class": instrument_class,
            "regime": regime,
            "trend_state": "UP",
            "volatility_state": "HIGH",
            "liquidity_state": "DEEP",
            "direction": direction,
            "timeframe": timeframe,
        },
        as_of=as_of,
        symbol=symbol,
    )


async def seed_card(
    database,
    *,
    rule_id: str = "card_test_v1",
    status: str = STATUS_ACTIVE,
    trigger_signature: TriggerSignature | None = None,
    context: ContextSignature | None = None,
    guidance: dict | None = None,
    source_ids: list[str] | None = None,
    support_ids: list[str] | None = None,
    contrary_ids: list[str] | None = None,
    version: int = 1,
    account_id: str = "default",
    mode: str = "PAPER",
    share_scope: str = "ACCOUNT_MODE",
    symbol: str | None = None,
    updated_at: datetime | None = AS_OF,
):
    from crypto_trader.learning.growth_experience import AdaptiveCardStore

    store = AdaptiveCardStore(database.session_factory)
    trigger_signature = trigger_signature or trigger()
    context = context or market_context()
    proposal = CardUpdateProposal(
        operation="CREATE",
        rationale="TEST_ONLY_SEED",
        card_rule_id=rule_id,
        account_id=account_id,
        mode=mode,
        share_scope=share_scope,
        source_episode_ids=source_ids or ["ep_1", "ep_2", "ep_3"],
        supporting_episode_ids=support_ids or source_ids or ["ep_1", "ep_2", "ep_3"],
        contradicting_episode_ids=contrary_ids or [],
        proposed_trigger=trigger_signature.to_json(),
        proposed_context=context.to_json(),
        proposed_guidance=guidance
        or {"summary": "Funding extreme in bull regime", "direction": "LONG"},
        proposed_status=status,
    ).finalize()
    result = await store.apply(proposal)
    if version > 1 or updated_at is not None or symbol is not None:
        from sqlalchemy import select

        from crypto_trader.persistence.models import AICompressedExperienceORM

        async with database.session_factory() as session:
            row = (
                await session.execute(
                    select(AICompressedExperienceORM).where(
                        AICompressedExperienceORM.rule_id == result.rule_id
                    )
                )
            ).scalar_one()
            row.version = version
            if updated_at is not None:
                row.updated_at = updated_at
                row.known_at = updated_at
                row.last_validated_at = updated_at
                from crypto_trader.learning.growth_models import GrowthCardVersionORM

                journals = (
                    await session.execute(
                        select(GrowthCardVersionORM).where(
                            GrowthCardVersionORM.card_rule_id == result.rule_id
                        )
                    )
                ).scalars().all()
                for journal in journals:
                    journal.created_at = updated_at
                    if isinstance(journal.snapshot_json, dict):
                        snapshot = dict(journal.snapshot_json)
                        snapshot["known_at"] = updated_at.isoformat()
                        snapshot["updated_at"] = updated_at.isoformat()
                        snapshot["last_validated_at"] = updated_at.isoformat()
                        journal.snapshot_json = snapshot
            if symbol is not None:
                row.symbol = symbol
            await session.commit()
    return result
