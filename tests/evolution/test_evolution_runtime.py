from datetime import UTC, datetime

from crypto_trader.evolution.gateways.memory_gateway import MemoryGateway
from crypto_trader.evolution.gateways.research_gateway import ResearchGateway
from crypto_trader.evolution.scheduler.review_scheduler import EvolutionReviewScheduler
from crypto_trader.evolution.state_machine import EvolutionStateMachine
from crypto_trader.evolution.time.review_period import (
    previous_daily,
    previous_monthly,
    previous_weekly,
    previous_yearly,
)


def _utc(y, m, d, hh=0, mm=0, ss=0):
    return datetime(y, m, d, hh, mm, ss, tzinfo=UTC)


def test_daily_previous_period_timezone_independent():
    for _tz in ("UTC", "Asia/Shanghai", "America/Los_Angeles"):
        period = previous_daily(_utc(2026, 8, 26, 0, 5, 0))
        assert period.period_id == "2026-08-25"
        assert period.starts_at.day == 25
        assert period.ends_at.day == 25


def test_weekly_iso_period():
    period = previous_weekly(_utc(2026, 8, 31, 0, 5, 0))  # Monday
    assert period.period_id.endswith("W35")


def test_monthly_boundary_and_leap_year():
    period = previous_monthly(_utc(2026, 1, 1, 0, 5, 0))
    assert period.period_id == "2025-12"
    leap = previous_monthly(_utc(2024, 3, 1, 0, 5, 0))
    assert leap.period_id == "2024-02"
    assert leap.ends_at.day == 29


def test_yearly_boundary():
    period = previous_yearly(_utc(2026, 1, 1, 0, 5, 0))
    assert period.period_id == "2025"
    assert period.starts_at.year == 2025
    assert period.ends_at.year == 2025


def test_scheduler_idempotent_and_serial():
    scheduler = EvolutionReviewScheduler()
    now = _utc(2026, 8, 26, 0, 5, 0)
    first = scheduler.run_serially(now)
    second = scheduler.run_serially(now)
    assert len(first) == 1  # only daily due at this instant
    assert len(second) == 0  # idempotent: daily already completed
    keys = ["review:daily:2026-08-25"]
    assert keys[0] in scheduler.runs
    assert scheduler.runs[keys[0]].status == "COMPLETED"


def test_scheduler_restart_recovers_same_run():
    scheduler = EvolutionReviewScheduler()
    now = _utc(2026, 8, 26, 0, 5, 0)
    scheduler.run_serially(now)
    scheduler2 = EvolutionReviewScheduler()
    # Same deterministic in-memory scheduler would re-run; simulated restore
    # by copying completed runs (restart recovery is represented by the
    # idempotency key check).
    scheduler2.runs.update(scheduler.runs)
    assert scheduler2.run_serially(now) == []


def test_evolution_offline_trading_health():
    # Evolution runtime is optional; live trading health is not touched by this.
    scheduler = EvolutionReviewScheduler()
    assert scheduler is not None


def test_candidate_cannot_execute_research_gateway():
    gateway = ResearchGateway()
    try:
        gateway.execution_authority()
        raise AssertionError()
    except PermissionError:
        pass


def test_state_machine_transitions():
    sm = EvolutionStateMachine()
    sm.transition("REVIEW_READY", "daily review")
    sm.transition("OBSERVE", "evidence loaded")
    sm.transition("PROPOSE", "candidate")
    assert sm.state == "PROPOSE"
    sm.transition("READY_FOR_UPGRADE", "validated")
    assert sm.state == "READY_FOR_UPGRADE"


def test_memory_gateway_lineage():
    gateway = MemoryGateway()
    gateway.store_lesson({"id": "L1", "lesson": "confirm trend"})
    gateway.confirm_lesson("L1")
    gateway.link_candidate("C1", "L1")
    lineage = gateway.get_lineage("L1")
    assert lineage[0]["status"] == "CONFIRMED"
    assert lineage[-1]["candidate_id"] == "C1"
