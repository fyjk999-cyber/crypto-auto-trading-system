from crypto_trader.learning.lifecycle_reviews import (
    PROVENANCE_LABEL,
    REVIEW_TYPES,
    LifecycleReviewEngine,
)


def _events():
    return [
        {"event_id": "e1", "kind": "ADD"},
        {"event_id": "e2", "kind": "HEDGE"},
        {"event_id": "e3", "kind": "BASE_EXIT_MODIFIED"},
        {"event_id": "e4", "kind": "FAST_PROFIT"},
        {"event_id": "e5", "kind": "REENTRY"},
        {"event_id": "e6", "kind": "RISK_L2"},
        {"event_id": "e7", "kind": "LLM_DECISION"},
    ]


async def test_seven_types_collision_safe_and_restart(database):
    engine = LifecycleReviewEngine(database.session_factory)
    assert await engine.ingest_events("ep1", _events(), decision_id="d1") == 7
    assert await engine.ingest_events("ep1", _events()) == 0  # restart/idempotent
    reviews = await engine.list_reviews(episode_id="ep1")
    assert len(reviews) == 7
    assert {r["review_type"] for r in reviews} == set(REVIEW_TYPES)
    assert all(r["status"] == "PENDING" for r in reviews)
    assert all(r["authority"] == "LEARNING_ONLY" and r["is_order"] is False for r in reviews)
    assert len({r["review_id"] for r in reviews}) == 7


async def test_same_type_same_day_does_not_collide_and_multi_review_episode(database):
    engine = LifecycleReviewEngine(database.session_factory)
    events = [
        {"event_id": "add-1", "kind": "ADD"},
        {"event_id": "add-2", "kind": "ADD"},
        {"event_id": "exit-1", "kind": "BASE_EXIT_MODIFIED"},
    ]
    assert await engine.ingest_events("ep2", events) == 3
    reviews = await engine.list_reviews(episode_id="ep2")
    assert len(reviews) == 3
    assert sorted(r["source_event_id"] for r in reviews) == ["add-1", "add-2", "exit-1"]


async def test_maturity_inconclusive_and_counterfactual_provenance(database):
    engine = LifecycleReviewEngine(database.session_factory)
    await engine.ingest_events(
        "ep3",
        [{"event_id": "a1", "kind": "ADD"}, {"event_id": "r1", "kind": "RISK_L1"}],
        trade_plan_id="plan-1",
    )
    reviews = await engine.list_reviews(episode_id="ep3")
    add_review = next(r for r in reviews if r["review_type"] == "ADD_REVIEW")
    risk_review = next(r for r in reviews if r["review_type"] == "RISK_REVIEW")
    assert add_review["counterfactual_json"]["provenance"] == PROVENANCE_LABEL
    assert "without the ADD" in add_review["counterfactual_json"]["definition"]
    assert add_review["trade_plan_id"] == "plan-1"

    matured = await engine.mature(
        add_review["review_id"],
        actual_net_bps=30.0,
        counterfactual_net_bps=10.0,
        verdict="HELPFUL",
        confidence=0.7,
        mfe_bps=45.0,
        mae_bps=-8.0,
        cost_bps=22.0,
        maturity_horizon="1h",
    )
    assert matured["status"] == "MATURE" and matured["delta_bps"] == 20.0
    again = await engine.mature(
        add_review["review_id"],
        actual_net_bps=999.0,
        counterfactual_net_bps=0.0,
        verdict="X",
        confidence=0.1,
    )
    assert again["delta_bps"] == 20.0  # mature reviews are immutable/idempotent

    inconclusive = await engine.mark_inconclusive(risk_review["review_id"], "missing_factual_path")
    assert inconclusive["status"] == "INCONCLUSIVE"
    assert inconclusive["verdict"] == "missing_factual_path"


async def test_resolve_maturity_never_guesses_and_requires_facts(database):
    engine = LifecycleReviewEngine(database.session_factory)
    await engine.ingest_events("ep-m", [{"event_id": "m1", "kind": "ADD"}])
    review = (await engine.list_reviews(episode_id="ep-m"))[0]
    inconclusive = await engine.resolve_maturity(review["review_id"], {})
    assert inconclusive["status"] == "INCONCLUSIVE"
    assert inconclusive["verdict"] == "INSUFFICIENT_FACTUAL_INPUTS"

    await engine.ingest_events("ep-m2", [{"event_id": "m2", "kind": "ADD"}])
    second = (await engine.list_reviews(episode_id="ep-m2"))[0]
    matured = await engine.resolve_maturity(
        second["review_id"],
        {
            "actual_net_bps": 25.0,
            "counterfactual_net_bps": 10.0,
            "confidence": 0.8,
            "maturity_horizon": "1h",
        },
    )
    assert matured["status"] == "MATURE"
    assert matured["verdict"] == "HELPFUL" and matured["delta_bps"] == 15.0
