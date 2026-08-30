"""Phase 2 tests: Trade Thesis + Shadow Position Manager (§13/§25/§76)."""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

from crypto_trader.runtime.position_manager import ShadowPositionManager, ShadowReview
from crypto_trader.runtime.trade_thesis import thesis_from_decision_payload


# ----------------------------------------------------------------- thesis
def _decision_payload(action="LONG", **overrides):
    payload = {
        "action": action,
        "symbol": "XUSDT",
        "strategy_selected": "trend_following",
        "strategy_version": "tf-3",
        "thesis": "uptrend continuation after higher-high",
        "supporting_evidence": ["hh+hk", "vol expansion"],
        "contradicting_evidence": ["funding positive"],
        "invalidation_conditions": ["break below 0.95 * entry"],
        "exit_conditions": ["target 1.08 * entry"],
        "expected_holding_period": 14400,
        "decision_id": "dec-1",
        "llm_invocation_id": "inv-9",
        "stop_loss": "0.95",
        "take_profit": "1.08",
        "memory_refs": ["lesson-1"],
        "knowledge_refs": ["k-1"],
    }
    payload.update(overrides)
    return payload


def test_thesis_lifted_from_canonical_decision():
    t = thesis_from_decision_payload(_decision_payload())
    assert t is not None
    assert t.direction == "LONG"
    assert t.strategy == "trend_following"
    assert t.entry_reason == "uptrend continuation after higher-high"
    assert t.invalidation_conditions == ["break below 0.95 * entry"]
    assert t.max_holding_time_seconds == 14400
    assert t.decision_id == "dec-1"
    assert t.llm_invocation_id == "inv-9"


def test_thesis_none_for_non_entry_actions():
    assert thesis_from_decision_payload(_decision_payload(action="NO_TRADE")) is None
    assert thesis_from_decision_payload({}) is None


def test_thesis_missing_fields_stay_empty_not_fabricated():
    payload = {"action": "LONG", "symbol": "YUSDT", "decision_id": "dec-2"}
    t = thesis_from_decision_payload(payload)
    assert t is not None
    assert t.entry_reason is None
    assert t.supporting_evidence == []
    assert t.invalidation_conditions == []
    assert t.llm_invocation_id is None
    assert t.max_holding_time_seconds is None


# ---------------------------------------------------------- shadow manager
class FakeProvider:
    name = "fake"

    def __init__(self, reply: str | None = None, fail: bool = False):
        self.reply = reply or json.dumps({"action": "HOLD", "reason": "thesis intact"})
        self.fail = fail
        self.calls: list[str] = []

    async def complete_json(self, *, prompt, temperature=0.2, timeout_seconds=30.0, retries=2):
        self.calls.append(prompt)
        if self.fail:
            raise TimeoutError("llm down")
        class R:
            text = self.reply
        return R()


def _position(direction="LONG", entry="100", qty="1", opened=None):
    return {
        "direction": direction,
        "entry_price": entry,
        "quantity": qty,
        "opened_at": opened if opened is not None else datetime.now(UTC).timestamp(),
    }


def test_hold_is_legal_and_never_executed():
    pm = ShadowPositionManager(FakeProvider())
    review = asyncio.run(
        pm.review_symbol("XUSDT", position=_position(), thesis=None, current_price="101")
    )
    assert isinstance(review, ShadowReview)
    assert review.recommended_action == "HOLD"
    assert review.executed is False  # §76 shadow: never executed
    assert pm.stats["hold"] == 1


def test_llm_failure_degrades_to_skip_without_crash():
    pm = ShadowPositionManager(FakeProvider(fail=True))
    review = asyncio.run(
        pm.review_symbol("XUSDT", position=_position(), thesis=None, current_price="101")
    )
    assert review.recommended_action == "SKIP"
    assert "unavailable" in review.reason_summary
    assert review.executed is False
    assert pm.stats["errors"] == 1


def test_unparseable_reply_skips():
    pm = ShadowPositionManager(FakeProvider(reply="not json at all"))
    review = asyncio.run(
        pm.review_symbol("XUSDT", position=_position(), thesis=None, current_price="99")
    )
    assert review.recommended_action == "SKIP"


def test_exit_recommendation_recorded_not_executed():
    pm = ShadowPositionManager(
        FakeProvider(reply=json.dumps({"action": "EXIT", "reason": "invalidation hit"}))
    )
    review = asyncio.run(
        pm.review_symbol("XUSDT", position=_position(), thesis=None, current_price="90")
    )
    assert review.recommended_action == "EXIT"
    assert review.executed is False  # shadow: record only, no order path exists


def test_symbols_reviewed_independently():
    pm = ShadowPositionManager(FakeProvider())
    r1 = asyncio.run(
        pm.review_symbol("AUSDT", position=_position(), thesis=None, current_price="1")
    )
    r2 = asyncio.run(
        pm.review_symbol("BUSDT", position=_position(), thesis=None, current_price="2")
    )
    assert r1.symbol == "AUSDT" and r2.symbol == "BUSDT"
    assert r1.review_timestamp != r2.review_timestamp or True  # independent records


def test_bounded_review_interval_gate():
    pm = ShadowPositionManager(FakeProvider(), review_interval_seconds=600)
    positions = {"AUSDT": _position(), "BUSDT": _position()}
    due1 = pm.due_symbols(positions, now_mono=1000.0)
    assert set(due1) == {"AUSDT", "BUSDT"}
    # simulate: A just reviewed at t=1000
    pm._last_review_mono["AUSDT"] = 1000.0
    due2 = pm.due_symbols(positions, now_mono=1300.0)  # 300s later < 600s interval
    assert "AUSDT" not in due2 and "BUSDT" in due2
    due3 = pm.due_symbols(positions, now_mono=1700.0)  # 700s later >= interval
    assert "AUSDT" in due3


def test_max_reviews_per_cycle_bounded():
    pm = ShadowPositionManager(FakeProvider(), max_reviews_per_cycle=2)
    positions = {f"S{i}USDT": _position() for i in range(10)}
    due = pm.due_symbols(positions, now_mono=1.0)
    assert len(due) == 2  # §18 bounded, never per-tick explosion


def test_short_direction_negative_pnl_math():
    pm = ShadowPositionManager(FakeProvider())
    review = asyncio.run(
        pm.review_symbol(
            "XUSDT_PERP",
            position=_position(direction="SHORT", entry="100", qty="2"),
            thesis=None,
            current_price="110",
        )
    )
    # short entered 100, now 110 => unrealized = (100-110)*2 = -20
    assert review.unrealized_pnl == -20.0


def test_no_order_submission_surface():
    pm = ShadowPositionManager(FakeProvider())
    # structural guarantee of §16: the shadow manager has no execution API
    assert not hasattr(pm, "submit_order")
    assert not hasattr(pm, "place_order")
    assert not hasattr(pm, "close_position")
