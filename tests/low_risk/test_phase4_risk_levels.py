"""Phase 4H tests: Risk L1/L2 protection + Risk Episode lifetime.

L1 = warning + Core LLM reassessment; L2 = forced hard exit; L1 escalates to
forced close immediately when the Core LLM chain is unreachable. ADD never
resets episode history, and an L2 latch survives a favourable recovery.
"""

from __future__ import annotations

import inspect
from decimal import Decimal

from crypto_trader.risk import risk_levels as module
from crypto_trader.risk.risk_levels import (
    PositionRiskEpisode,
    PositionRiskMonitor,
    RiskLevel,
    RiskLevelConfig,
)


def _episode(side: str = "LONG", entry: str = "100") -> PositionRiskEpisode:
    return PositionRiskEpisode(
        leg_id="leg1", symbol="BTCUSDT", side=side, entry_price=Decimal(entry)
    )


def test_l1_warning_requests_llm_without_forced_close() -> None:
    monitor = PositionRiskMonitor()
    decision = monitor.evaluate(_episode(), mark_price=Decimal("97.0"))  # -3%
    assert decision.level == RiskLevel.L1
    assert decision.requires_llm_reassessment is True
    assert decision.force_close is False
    assert "L1_WARNING_LLM_REASSESSMENT" in decision.reason_codes
    assert decision.config_label == "ENGINEERING_CANDIDATE_NOT_FROZEN_STRATEGY_LAW"


def test_l2_forces_hard_exit() -> None:
    monitor = PositionRiskMonitor()
    episode = _episode()
    decision = monitor.evaluate(episode, mark_price=Decimal("94.0"))  # -6%
    assert decision.level == RiskLevel.L2
    assert decision.force_close is True
    assert decision.requires_llm_reassessment is False
    assert episode.forced_close is True
    assert "FORCED_CLOSE_REQUIRED" in decision.reason_codes


def test_short_side_is_mirrored() -> None:
    monitor = PositionRiskMonitor()
    episode = _episode(side="SHORT")
    decision = monitor.evaluate(episode, mark_price=Decimal("103.0"))  # adverse +3%
    assert decision.level == RiskLevel.L1
    l2 = monitor.evaluate(episode, mark_price=Decimal("106.0"))
    assert l2.level == RiskLevel.L2 and l2.force_close is True


def test_account_drawdown_can_trigger_levels() -> None:
    monitor = PositionRiskMonitor()
    l1 = monitor.evaluate(_episode(), mark_price=Decimal("100"), account_drawdown_pct=6.0)
    assert l1.level == RiskLevel.L1
    assert "ACCOUNT_DRAWDOWN_WARNING" in l1.reason_codes
    l2 = monitor.evaluate(_episode(), mark_price=Decimal("100"), account_drawdown_pct=11.0)
    assert l2.level == RiskLevel.L2
    assert "ACCOUNT_DRAWDOWN_LIMIT" in l2.reason_codes


def test_add_does_not_reset_episode_and_latch_is_sticky() -> None:
    monitor = PositionRiskMonitor()
    episode = _episode()
    first = monitor.evaluate(episode, mark_price=Decimal("97.0"))
    assert first.level == RiskLevel.L1
    hits_before = episode.l1_hits
    episode.record_add(reason="LLM_ADD")
    assert episode.add_count == 1
    assert episode.l1_hits == hits_before  # ADD does not reset history

    # Price recovers, but the L1 episode remains latched.
    recovered = monitor.evaluate(episode, mark_price=Decimal("101.0"))
    assert recovered.level == RiskLevel.L1
    assert "RISK_EPISODE_LATCHED" in recovered.reason_codes
    assert episode.l1_hits >= hits_before


def test_l1_escalates_immediately_when_core_llm_unreachable() -> None:
    monitor = PositionRiskMonitor()
    episode = _episode()
    decision = monitor.evaluate(episode, mark_price=Decimal("97.5"))
    assert decision.level == RiskLevel.L1
    escalated = monitor.escalate_l1_to_force_close(episode, decision)
    assert escalated.level == RiskLevel.L2
    assert escalated.force_close is True
    assert "L1_ESCALATED_TO_FORCED_CLOSE" in escalated.reason_codes
    assert episode.latched_level == RiskLevel.L2

    # Escalation is a no-op for a non-L1 decision.
    fresh = _episode()
    none_decision = monitor.evaluate(fresh, mark_price=Decimal("101"))
    assert monitor.escalate_l1_to_force_close(fresh, none_decision) is none_decision


def test_thresholds_are_configurable_engineering_candidates() -> None:
    config = RiskLevelConfig(
        l1_position_loss_pct=1.0, l2_position_loss_pct=2.0, l1_account_drawdown_pct=50
    )
    monitor = PositionRiskMonitor(config)
    assert monitor.evaluate(_episode(), mark_price=Decimal("98.5")).level == RiskLevel.L1
    assert monitor.evaluate(_episode(), mark_price=Decimal("97.5")).level == RiskLevel.L2


def test_risk_layer_has_no_sizing_or_execution_authority() -> None:
    source = inspect.getsource(module)
    for forbidden in (
        "ExecutionAuthority",
        "OrderManager",
        "submit_order",
        "process_signal",
        "SignalIntent",
        "capital_allocation",
        "approved_quantity",
    ):
        assert forbidden not in source
    assert RiskLevel.L1.value == "L1" and RiskLevel.L2.value == "L2"
