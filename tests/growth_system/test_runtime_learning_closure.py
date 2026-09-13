"""Runtime learning closure tests: structured review -> canonical knowledge."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from crypto_trader.governance.factual_learning import FactualEpisodeLearning
from crypto_trader.governance.trade_episode import FactualTradeEpisode
from crypto_trader.learning.growth_models import (
    GrowthLessonORM,
    GrowthPatternORM,
    GrowthReviewAttemptORM,
    create_growth_schema,
)
from crypto_trader.learning.growth_runtime_learning import (
    GrowthRuntimeLearningService,
    GrowthRuntimeReport,
    normalize_regime,
    runtime_status,
)
from crypto_trader.persistence.models import (
    AICompressedExperienceORM,
    AITradeReviewORM,
    DailyReviewRunORM,
    TradeEpisodeORM,
)
from tests.growth_system.test_review_schema_and_refs import FakeProvider


@pytest.fixture
async def growth_db(database):
    await create_growth_schema(database.engine)
    return database


def _episode(
    episode_id: str,
    *,
    symbol: str = "BTCUSDT",
    regime: str = "TREND",
    direction: str = "LONG",
    net_pnl: str = "1",
) -> FactualTradeEpisode:
    return FactualTradeEpisode(
        episode_id=episode_id,
        trade_plan_id=f"plan_{episode_id}",
        symbol=symbol,
        direction=direction,
        entry_decision_id=f"d_{episode_id}",
        exit_decision_id=f"x_{episode_id}",
        position_decision_ids=[],
        risk_decision_ids=[],
        order_ids=[f"o_{episode_id}"],
        fill_ids=[f"f_{episode_id}"],
        entry_price=Decimal("100"),
        exit_price=Decimal("101"),
        opened_quantity=Decimal("1"),
        closed_quantity=Decimal("1"),
        leverage=Decimal("1"),
        fees=Decimal("0"),
        funding_pnl=Decimal("0"),
        gross_pnl=Decimal(net_pnl),
        net_pnl=Decimal(net_pnl),
        holding_time_seconds=60.0,
        entry_market_regime=regime,
        terminal_reason="EXIT",
        opened_at=datetime(2026, 9, 9, 10, tzinfo=UTC),
        closed_at=datetime(2026, 9, 9, 11, tzinfo=UTC),
    )


def _learning_item(episode_id: str, statement: str) -> dict:
    return {
        "statement": statement,
        "evidence_refs": [f"episode:{episode_id}", f"fill:f_{episode_id}"],
        "confidence": "LOW",
        "applicability": {"regime": "TRENDING", "direction": "LONG"},
        "counter_conditions": ["follow-through volume absent"],
    }


def _payload(
    episode_id: str,
    *,
    lessons: list[dict] | None = None,
    mistakes: list[dict] | None = None,
    future_rules: list[dict] | None = None,
) -> dict:
    default_lessons = [
        {
            "statement": "Volume expansion preceded the directional move.",
            "testable_prediction": "Future comparable episodes show the same association.",
            "scope": {
                "scope": "SYMBOL_REGIME",
                "symbols": ["BTCUSDT"],
                "regimes": ["TRENDING"],
            },
            "evidence_refs": [f"episode:{episode_id}"],
            "contrary_refs": [],
            "uncertainty": "candidate",
            "confidence": "LOW",
        }
    ]
    lesson_items = default_lessons if lessons is None else list(lessons)
    return {
        "episode_id": episode_id,
        "observation_facts": [
            {
                "statement": "Episode closed with complete fills.",
                "evidence_refs": [f"episode:{episode_id}"],
            }
        ],
        "testable_lessons": lesson_items,
        "success_factors": [],
        "failure_factors": [],
        "mistakes": mistakes or [],
        "future_rules": future_rules or [],
        "applicability_scope": {
            "scope": "SYMBOL_REGIME",
            "symbols": ["BTCUSDT"],
            "regimes": ["TRENDING"],
        },
        "uncertainty": "",
        "data_gaps": [],
        "risk_rule_changes": [],
    }


async def _seed_episode(growth_db, episode: FactualTradeEpisode) -> None:
    async with growth_db.session_factory() as session:
        session.add(
            TradeEpisodeORM(
                episode_id=episode.episode_id,
                trade_plan_id=episode.trade_plan_id,
                symbol=episode.symbol,
                direction=episode.direction,
                entry_decision_id=episode.entry_decision_id,
                exit_decision_id=episode.exit_decision_id,
                order_ids_json=episode.order_ids,
                fill_ids_json=episode.fill_ids,
                entry_price=episode.entry_price,
                exit_price=episode.exit_price,
                opened_quantity=episode.opened_quantity,
                closed_quantity=episode.closed_quantity,
                leverage=episode.leverage,
                fees=episode.fees,
                funding_pnl=episode.funding_pnl,
                gross_pnl=episode.gross_pnl,
                net_pnl=episode.net_pnl,
                holding_time_seconds=episode.holding_time_seconds,
                entry_market_regime=episode.entry_market_regime,
                terminal_reason=episode.terminal_reason,
                factual=True,
                review_status="PENDING",
                opened_at=episode.opened_at,
                closed_at=episode.closed_at,
            )
        )
        existing_claim = (
            await session.execute(
                select(DailyReviewRunORM).where(
                    DailyReviewRunORM.review_date == "2026-09-09"
                )
            )
        ).scalar_one_or_none()
        if existing_claim is None:
            session.add(
                DailyReviewRunORM(
                    review_date="2026-09-09",
                    status="RUNNING",
                    claim_token="token-r4",
                    owner="worker",
                    claim_deadline_at=datetime.now(UTC) + timedelta(hours=1),
                    attempt_count=1,
                )
            )
        await session.commit()
    await FactualEpisodeLearning(growth_db.session_factory).review_many([episode])


async def _run_service(growth_db, provider, episodes):
    service = GrowthRuntimeLearningService(
        growth_db.session_factory, provider=provider, min_pattern_samples=3
    )
    return await service.run(
        episodes,
        review_date="2026-09-09",
        claim_token="token-r4",
        owner="worker",
        fence=lambda: _true(),
    )


async def _true() -> bool:
    return True


async def test_runtime_structured_review_produces_causal_fields(growth_db):
    episode = _episode("ep_r4_1")
    await _seed_episode(growth_db, episode)
    provider = FakeProvider(
        [
            _payload(
                episode.episode_id,
                mistakes=[_learning_item(episode.episode_id, "Added size after volume faded.")],
                future_rules=[
                    _learning_item(
                        episode.episode_id,
                        "Avoid adding size when breakout extension lacks volume.",
                    )
                ],
            )
        ]
    )
    report = await _run_service(growth_db, provider, [episode])
    assert report.structured_reviews_created == 1
    assert report.reviews_with_future_rules == 1
    assert report.status == "CANDIDATE_LEARNING"
    async with growth_db.session_factory() as session:
        review = (
            await session.execute(
                select(AITradeReviewORM).where(
                    AITradeReviewORM.episode_id == episode.episode_id
                )
            )
        ).scalar_one()
        attempts = (
            await session.execute(select(GrowthReviewAttemptORM))
        ).scalars().all()
    assert review.mistakes_json
    assert review.future_rules_json
    assert len(attempts) == 1 and attempts[0].status == "SUCCEEDED"
    # F5: epistemic known_at is the publication time, never the historical
    # episode close time (2026-09-09).
    async with growth_db.session_factory() as session:
        lessons = (
            await session.execute(select(GrowthLessonORM))
        ).scalars().all()
    assert lessons
    assert all(
        (row.known_at.replace(tzinfo=UTC) if row.known_at.tzinfo is None else row.known_at)
        .date()
        > datetime(2026, 9, 9, tzinfo=UTC).date()
        for row in lessons
    )


async def test_runtime_insufficient_evidence_does_not_fabricate(growth_db):
    episode = _episode("ep_r4_2")
    await _seed_episode(growth_db, episode)
    provider = FakeProvider([_payload(episode.episode_id, lessons=[])])
    report = await _run_service(growth_db, provider, [episode])
    assert report.structured_reviews_created == 1
    assert report.cards_created == 0
    assert report.status == "REVIEW_ONLY"
    async with growth_db.session_factory() as session:
        review = (
            await session.execute(
                select(AITradeReviewORM).where(
                    AITradeReviewORM.episode_id == episode.episode_id
                )
            )
        ).scalar_one()
    assert review.mistakes_json == []
    assert review.future_rules_json == []


async def test_runtime_three_episodes_materialize_canonical_card(growth_db):
    episodes = [_episode(f"ep_r4_card_{i}") for i in range(3)]
    for episode in episodes:
        await _seed_episode(growth_db, episode)
    provider = FakeProvider(
        [_payload(episode.episode_id) for episode in episodes]
    )
    report = await _run_service(growth_db, provider, episodes)
    assert report.status in {"CANDIDATE_LEARNING", "LEARNING", "DEGRADED"}
    async with growth_db.session_factory() as session:
        patterns = (await session.execute(select(GrowthPatternORM))).scalars().all()
        cards = (
            await session.execute(select(AICompressedExperienceORM))
        ).scalars().all()
    assert any(row.status == "VALIDATED" for row in patterns)
    assert cards


async def test_runtime_same_regime_narratives_aggregate_canonically(growth_db):
    regimes = ["trend_up continuation", "TREND_BULL momentum", "trending breakout"]
    episodes = [
        _episode(f"ep_r4_regime_{i}", regime=regime)
        for i, regime in enumerate(regimes)
    ]
    for episode in episodes:
        await _seed_episode(growth_db, episode)
    provider = FakeProvider([_payload(episode.episode_id) for episode in episodes])
    report = await _run_service(growth_db, provider, episodes)
    assert report.structured_reviews_created == 3
    async with growth_db.session_factory() as session:
        patterns = (await session.execute(select(GrowthPatternORM))).scalars().all()
    canonical = {row.regime for row in patterns}
    assert canonical == {"TRENDING"}
    assert any(row.status == "VALIDATED" for row in patterns)


def test_runtime_pf_definition_and_regime_normalization():
    assert normalize_regime("trend_up continuation")[0] == "TRENDING"
    assert normalize_regime("low-liquidity chop")[0] == "RANGING"
    assert normalize_regime("high volatility panic")[0] in {
        "HIGH_VOLATILITY",
        "PANIC",
    }
    assert runtime_status(GrowthRuntimeReport("NO_DATA", "2026-09-09")) == "NO_DATA"
    assert (
        runtime_status(
            GrowthRuntimeReport(
                "REVIEW_ONLY", "2026-09-09", closed_episodes_seen=1
            )
        )
        == "BLOCKED"
    )
    assert (
        runtime_status(
            GrowthRuntimeReport(
                "CANDIDATE_LEARNING",
                "2026-09-09",
                closed_episodes_seen=1,
                structured_reviews_created=1,
                lessons_created=1,
            )
        )
        == "CANDIDATE_LEARNING"
    )


async def test_runtime_future_rule_applicability_does_not_merge(growth_db):
    episodes = [_episode(f"ep_r4_app_{i}") for i in range(3)]
    for episode in episodes:
        await _seed_episode(growth_db, episode)
    applications = [
        {"regime": "TRENDING", "direction": "LONG"},
        {"regime": "RANGING", "direction": "LONG"},
        {"regime": "PANIC", "direction": "LONG"},
    ]
    payloads = []
    for episode, application in zip(episodes, applications):
        rule = _learning_item(episode.episode_id, "Same statement.")
        rule["applicability"] = application
        payload = _payload(
            episode.episode_id, lessons=[], future_rules=[rule]
        )
        payloads.append(payload)
    provider = FakeProvider(payloads)
    report = await _run_service(growth_db, provider, episodes)
    assert report.structured_reviews_created == 3
    patterns = await GrowthRuntimeLearningService(
        growth_db.session_factory, provider=provider
    ).store.current_patterns_for_scope(
        account_id="default", mode="PAPER"
    )
    assert len(patterns) == 3
    assert all(row.sample_count == 1 for row in patterns)
    assert all(row.status == "CANDIDATE" for row in patterns)
