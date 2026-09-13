"""RISK-01/02/03: real GrowthReviewEvidenceLoader risk resolution."""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from crypto_trader.learning.growth_review_evidence import GrowthReviewEvidenceLoader


class _Scalars:
    def __init__(self, rows): self._rows = rows
    def all(self): return list(self._rows)


class _Result:
    def __init__(self, rows): self._rows = rows
    def scalars(self): return _Scalars(self._rows)


class _Session:
    def __init__(self, queues): self._queues = list(queues); self.executed = 0
    async def __aenter__(self): return self
    async def __aexit__(self, *exc): return False
    async def get(self, model, key): return None
    async def execute(self, statement):
        self.executed += 1
        rows = self._queues.pop(0) if self._queues else []
        return _Result(rows)


class _Factory:
    def __init__(self, queues): self._queues = queues; self.sessions = []
    def __call__(self):
        session = _Session(self._queues); self.sessions.append(session); return session


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
    factory = _Factory([[], [], []])
    ev = await GrowthReviewEvidenceLoader(factory).load(_episode([]))
    assert ev.risk_availability == "UNAVAILABLE"
    assert ev.risk_decision_ids == []
    assert ev.risk_decision_id is None
