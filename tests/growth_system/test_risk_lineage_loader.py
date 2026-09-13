"""RISK-01/02/03: real GrowthReviewEvidenceLoader risk resolution."""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from crypto_trader.learning.growth_review_evidence import (
    GrowthReviewEvidence,
    GrowthReviewEvidenceLoader,
)


class _Scalars:
    def __init__(self, rows): self._rows = rows
    def all(self):
        return list(self._rows)


class _Result:
    def __init__(self, rows): self._rows = rows
    def scalars(self):
        return _Scalars(self._rows)


class _Session:
    def __init__(self, queues):
        self._queues = list(queues)
        self.executed = 0
    async def __aenter__(self):
        return self
    async def __aexit__(self, *exc):
        return False
    async def get(self, model, key):
        return None
    async def execute(self, statement):
        self.executed += 1
        rows = self._queues.pop(0) if self._queues else []
        return _Result(rows)


class _Factory:
    def __init__(self, queues):
        self._queues = queues
        self.sessions = []
    def __call__(self):
        session = _Session(self._queues)
        self.sessions.append(session)
        return session


def _episode(risk_ids):
    return SimpleNamespace(
        episode_id="ep", trade_plan_id="plan", symbol="BTCUSDT",
        direction="LONG", entry_decision_id="dec", exit_decision_id=None,
        risk_decision_ids=risk_ids, risk_decision_ids_json=[],
        order_ids=[], order_ids_json=[], fill_ids=[], fill_ids_json=[],
        terminal_reason="EXIT", holding_time_seconds=1.0,
        gross_pnl="1", fees="0", funding_pnl="0", net_pnl="1",
        entry_price="1", exit_price="1", opened_quantity="1",
        closed_quantity="1", leverage="1", opened_at=datetime(2026,1,1,tzinfo=UTC),
        closed_at=datetime(2026,1,1,1,tzinfo=UTC), entry_market_regime="TREND",
    )


def _row(rid, reason):
    return SimpleNamespace(risk_decision_id=rid, decision="APPROVED", reason=reason)


async def test_risk_01_order_preserved_when_db_returns_reversed():
    factory = _Factory([[_row("risk-1", "r1"), _row("risk-2", "r2")], [], []])
    ev = await GrowthReviewEvidenceLoader(factory).load(_episode(["risk-2", "risk-1"]))
    assert ev.risk_availability == "AVAILABLE"
    assert ev.risk_decision_ids == ["risk-2", "risk-1"]
    assert ev.risk_decision_id == "risk-2"
    assert ev.risk_result == "APPROVED"
    assert ev.risk_reason_codes == ["r2"]


async def test_risk_02_partial_resolution_fails_closed():
    factory = _Factory([[_row("risk-1", "r1")], [], []])
    ev = await GrowthReviewEvidenceLoader(factory).load(_episode(["risk-1", "risk-2"]))
    assert ev.risk_availability == "UNAVAILABLE"
    assert ev.risk_decision_ids == []
    assert ev.risk_decision_id is None
    assert "RISK" in ev.missing_evidence


async def test_risk_03_empty_lineage_unavailable():
    factory = _Factory([[], []])
    ev = await GrowthReviewEvidenceLoader(factory).load(_episode([]))
    assert ev.risk_availability == "UNAVAILABLE"
    assert ev.risk_decision_ids == []
    assert ev.risk_decision_id is None


def _exec_episode(order_ids, fill_ids):
    ep = _episode([])
    ep.order_ids, ep.fill_ids = order_ids, fill_ids
    return ep


def _order(oid): return SimpleNamespace(internal_order_id=oid)
def _fill(fid, price="100", quantity="1"):
    return SimpleNamespace(fill_id=fid, price=price, quantity=quantity)


async def test_exec_01_order_preserved_when_db_reversed():
    factory = _Factory([[_order("order-1"), _order("order-2")],
                        [_fill("fill-1"), _fill("fill-2")]])
    ev = await GrowthReviewEvidenceLoader(factory).load(
        _exec_episode(["order-2", "order-1"], ["fill-2", "fill-1"])
    )
    assert ev.execution_availability == "AVAILABLE"
    assert ev.order_ids == ["order-2", "order-1"]
    assert ev.fill_ids == ["fill-2", "fill-1"]


async def test_exec_02_partial_order_fail_closed():
    factory = _Factory([[_order("order-1")], [_fill("fill-1")]])
    ev = await GrowthReviewEvidenceLoader(factory).load(
        _exec_episode(["order-1", "order-2"], ["fill-1"])
    )
    assert ev.execution_availability == "UNAVAILABLE"
    assert "ORDERS_FILLS" in ev.missing_evidence
    assert ev.weighted_entry_price == "UNKNOWN"


async def test_exec_03_partial_fill_fail_closed():
    factory = _Factory([[_order("order-1")], [_fill("fill-1")]])
    ev = await GrowthReviewEvidenceLoader(factory).load(
        _exec_episode(["order-1"], ["fill-1", "fill-2"])
    )
    assert ev.execution_availability == "UNAVAILABLE"


@pytest.mark.parametrize("order_ids,fill_ids", [([], ["f1"]), (["o1"], [])])
async def test_exec_04_empty_lineage(order_ids, fill_ids):
    factory = _Factory([[], []])
    ev = await GrowthReviewEvidenceLoader(factory).load(
        _exec_episode(order_ids, fill_ids)
    )
    assert ev.execution_availability == "UNAVAILABLE"


@pytest.mark.parametrize(
    "order_ids,fill_ids",
    [(["o1", "o1"], ["f1"]), (["o1"], ["f1", "f1"])],
)
async def test_exec_05_duplicate_expected_ids_fail_closed(order_ids, fill_ids):
    factory = _Factory([[_order("o1")], [_fill("f1")]])
    ev = await GrowthReviewEvidenceLoader(factory).load(
        _exec_episode(order_ids, fill_ids)
    )
    assert ev.execution_availability == "UNAVAILABLE"


async def test_weighted_price_complete_lineage():
    factory = _Factory([[_order("o1"), _order("o2")],
                        [_fill("f1", "100", "1"), _fill("f2", "200", "3")]])
    ev = await GrowthReviewEvidenceLoader(factory).load(
        _exec_episode(["o1", "o2"], ["f1", "f2"])
    )
    assert ev.execution_availability == "AVAILABLE"
    assert str(ev.weighted_entry_price) == "175"


async def test_exit_01_factual_terminal_available():
    ep = _episode([])
    ep.terminal_reason = "STOP_LOSS"
    ep.exit_decision_id = None
    factory = _Factory([[], []])
    ev = await GrowthReviewEvidenceLoader(factory).load(ep)
    assert ev.exit_availability == "AVAILABLE"
    assert ev.exit_reason == "STOP_LOSS"
    assert ev.exit_decision_id is None


async def test_exit_02_empty_terminal_unavailable():
    ep = _episode([])
    ep.terminal_reason = ""
    factory = _Factory([[], []])
    ev = await GrowthReviewEvidenceLoader(factory).load(ep)
    assert ev.exit_availability == "UNAVAILABLE"
    assert ev.exit_reason == "UNKNOWN"
    assert "EXIT" in ev.missing_evidence


def test_exit_03_invariant():
    ev = GrowthReviewEvidence(
        episode_id="ep", exit_availability="AVAILABLE", exit_reason="UNKNOWN"
    )
    try:
        ev.validate_availability()
    except ValueError:
        pass
    else:
        raise AssertionError("AVAILABLE exit with UNKNOWN reason must fail")


class _RuntimeLoader:
    def __init__(self, behaviour):
        self.behaviour = behaviour
        self.calls = []
    async def load(self, episode, **kwargs):
        self.calls.append(episode.episode_id)
        return self.behaviour(episode)


class _RuntimeReview:
    def __init__(self):
        self.calls = []
    async def review(self, payload, **kwargs):
        self.calls.append(payload.episode_id)
        return SimpleNamespace(status="FAILED", review=None, error_type="FAKE")


def _runtime_episode(eid):
    return SimpleNamespace(
        episode_id=eid, trade_plan_id="p", symbol="BTCUSDT", direction="LONG",
        entry_decision_id="d", exit_decision_id=None, position_decision_ids=[],
        risk_decision_ids=[], order_ids=[], fill_ids=[],
        entry_price="1", exit_price="1", opened_quantity="1",
        closed_quantity="1", leverage="1", fees="0", funding_pnl="0",
        gross_pnl="0", net_pnl="0", holding_time_seconds=1.0,
        entry_market_regime="TREND", terminal_reason="EXIT",
        opened_at=datetime(2026,1,1,tzinfo=UTC), closed_at=datetime(2026,1,1,1,tzinfo=UTC),
    )


def _valid_evidence(eid):
    return GrowthReviewEvidence(
        episode_id=eid, decision_id="d", decision_availability="AVAILABLE",
        exit_reason="EXIT", exit_availability="AVAILABLE",
    )


async def test_runtime_01_bad_loader_blocks_review():
    from crypto_trader.learning.growth_runtime_learning import GrowthRuntimeLearningService

    service = GrowthRuntimeLearningService(None, provider=SimpleNamespace())
    service.evidence_loader = _RuntimeLoader(lambda ep: (_ for _ in ()).throw(ValueError("BAD")))
    review = _RuntimeReview()
    service.review_service = review
    report = await service.run(
        [_runtime_episode("ep-bad")], review_date="2026-09-13",
        claim_token="t", owner="o", fence=_true,
    )
    assert review.calls == []
    assert "ValueError" in report.errors


async def test_runtime_02_next_episode_continues():
    from crypto_trader.learning.growth_runtime_learning import GrowthRuntimeLearningService

    def behaviour(ep):
        if ep.episode_id == "ep-bad":
            raise ValueError("BAD")
        return _valid_evidence(ep.episode_id)

    service = GrowthRuntimeLearningService(None, provider=SimpleNamespace())
    service.evidence_loader = _RuntimeLoader(behaviour)
    review = _RuntimeReview()
    service.review_service = review
    await service.run(
        [_runtime_episode("ep-bad"), _runtime_episode("ep-good")],
        review_date="2026-09-13", claim_token="t", owner="o", fence=_true,
    )
    assert review.calls == ["ep-good"]


async def test_validate_01_called_before_return(monkeypatch):
    calls = []
    original = GrowthReviewEvidence.validate_availability

    def spy(self):
        calls.append(1)
        return original(self)

    monkeypatch.setattr(GrowthReviewEvidence, "validate_availability", spy)
    factory = _Factory([[], []])
    await GrowthReviewEvidenceLoader(factory).load(_episode([]))
    assert len(calls) == 1


async def test_validate_02_invalid_envelope_blocked(monkeypatch):
    def boom(self):
        raise ValueError("CONTRADICTORY_AVAILABILITY:test")

    monkeypatch.setattr(GrowthReviewEvidence, "validate_availability", boom)
    with pytest.raises(ValueError):
        await GrowthReviewEvidenceLoader(_Factory([[], []])).load(_episode([]))


async def _true():
    return True
