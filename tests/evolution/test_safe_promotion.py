from datetime import UTC, datetime

from crypto_trader.evolution.promotion.contracts import TradingRelease, UpgradeReadinessSnapshot
from crypto_trader.evolution.promotion.coordinator import SafePromotionCoordinator
from crypto_trader.evolution.promotion.entry_gate import NewEntryGate


def make_snapshot(**overrides):
    base = dict(
        timestamp_utc=datetime.now(UTC).isoformat(),
        candidate_id="c1",
        champion_version="v1",
        open_positions=0,
        open_orders=0,
        in_flight_orders=0,
        pending_execution=0,
        recent_entry_count=0,
        market_volatility_state="NORMAL",
        spread_state="NORMAL",
        liquidity_state="NORMAL",
        market_data_health="HEALTHY",
        exchange_health="HEALTHY",
        reconciliation_health="HEALTHY",
        ledger_health="HEALTHY",
        portfolio_health="HEALTHY",
        risk_health="HEALTHY",
        kill_switch_state="OFF",
        runtime_lease_health="HEALTHY",
        critical_incidents=0,
    )
    base.update(overrides)
    return UpgradeReadinessSnapshot(**base)


def make_release(release_id="r1"):
    return TradingRelease(
        release_id=release_id,
        strategy_version="s2",
        factor_set_version="f2",
        prompt_version="p2",
        model_routing_version="m2",
        code_commit="abc",
        config_hash="cfg",
        parent_release_id="r0",
        candidate_id="c1",
        promotion_id="promo1",
    )


def test_safe_window_false_when_position_exists():
    coordinator = SafePromotionCoordinator()
    ok, reasons = coordinator.evaluate_safe_window(make_snapshot(open_positions=1))
    assert ok is False
    assert "OPEN_POSITIONS" in reasons


def test_safe_window_false_when_open_order():
    coordinator = SafePromotionCoordinator()
    ok, reasons = coordinator.evaluate_safe_window(make_snapshot(open_orders=1))
    assert ok is False
    assert "OPEN_ORDERS" in reasons


def test_safe_window_false_when_kill_switch_on():
    coordinator = SafePromotionCoordinator()
    ok, reasons = coordinator.evaluate_safe_window(make_snapshot(kill_switch_state="ON"))
    assert ok is False
    assert "KILL_SWITCH" in reasons


def test_safe_window_true_when_empty_healthy():
    coordinator = SafePromotionCoordinator()
    ok, reasons = coordinator.evaluate_safe_window(make_snapshot())
    assert ok is True
    assert reasons == []


def test_promotion_happy_path_and_lock():
    coordinator = SafePromotionCoordinator()
    result = coordinator.promote(
        promotion_id="promo1",
        candidate_id="c1",
        certified=True,
        snapshot=make_snapshot(),
        target_release=make_release(),
        health_pass=True,
        smoke_pass=True,
    )
    assert result.status == "ACTIVE"
    assert coordinator.active_release.release_id == "r1"
    assert coordinator.records["promo1"].status == "ACTIVE"
    assert coordinator.gate.state == "OPEN"


def test_promotion_uncertified_blocked():
    coordinator = SafePromotionCoordinator()
    result = coordinator.promote(
        promotion_id="promo1",
        candidate_id="c1",
        certified=False,
        snapshot=make_snapshot(),
        target_release=make_release(),
        health_pass=True,
        smoke_pass=True,
    )
    assert result.status == "REJECTED"


def test_promotion_health_fail_rolls_back():
    coordinator = SafePromotionCoordinator()
    result = coordinator.promote(
        promotion_id="promo1",
        candidate_id="c1",
        certified=True,
        snapshot=make_snapshot(),
        target_release=make_release(),
        health_pass=False,
        smoke_pass=True,
    )
    assert result.status == "ROLLED_BACK"
    assert coordinator.gate.state == "OPEN"


def test_rollback_safe_degraded_when_health_fails():
    coordinator = SafePromotionCoordinator()
    coordinator.promote(
        promotion_id="promo1",
        candidate_id="c1",
        certified=True,
        snapshot=make_snapshot(),
        target_release=make_release(),
        health_pass=True,
        smoke_pass=True,
    )
    result = coordinator.rollback(promotion_id="promo1", health_pass=False)
    assert result.status == "SAFE_DEGRADED"
    assert coordinator.gate.state == "BLOCKED_FOR_UPGRADE"


def test_new_entry_gate_blocks_only_risk_increasing():
    gate = NewEntryGate()
    gate.block()
    assert gate.allows(reduce_only=False, action="OPEN_LONG") is False
    assert gate.allows(reduce_only=True, action="REDUCE") is True
    assert gate.allows(reduce_only=False, action="EXIT") is True
    assert gate.allows(reduce_only=False, action="STOP_LOSS") is True
    gate.open()
    assert gate.allows(reduce_only=False, action="OPEN_LONG") is True
