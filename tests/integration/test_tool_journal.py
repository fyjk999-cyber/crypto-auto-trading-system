"""Phase H acceptance: tool invocation journal + advisory utility learning.

Directive coverage:
TOOL_JOURNAL_RECORD    : every pipeline tool call journaled with bounded detail
DECISION_LINEAGE       : buffered rows flush with decision_id + llm id
FAIL_SAFE              : journal failure never breaks trading; counted
UTILITY_REPORT         : factual per-tool volume/error/latency + pairing
ADVISORY_ONLY          : lesson text carries explicit non-authority framing;
                         no gate, no risk bypass anywhere in the module
BUDGET_PARAM_WIRED     : tool_call_budget_per_decision readable from hot policy
"""

import time
from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from crypto_trader.governance.tool_journal import ToolInvocationJournal


@pytest.fixture()
async def journal(database):
    return ToolInvocationJournal(database.session_factory)


async def test_record_and_report(journal):
    await journal.record("factor_snapshot", symbol="BTCUSDT", latency_ms=12)
    await journal.record("factor_snapshot", symbol="BTCUSDT", latency_ms=18)
    await journal.record(
        "memory_retrieval", symbol="BTCUSDT", latency_ms=5, status="ERROR",
        detail="DecimalError",
    )
    assert journal.recorded == 3
    report = await journal.utility_report(window_hours=24)
    per_tool = report["per_tool"]
    assert per_tool["factor_snapshot"]["invocations"] == 2
    assert per_tool["factor_snapshot"]["error_rate"] == 0.0
    assert per_tool["factor_snapshot"]["avg_latency_ms"] == 15.0
    assert per_tool["memory_retrieval"]["errors"] == 1
    assert "CORRELATION_NOT_CAUSATION" in report["pairing_disclaimer"]


async def test_defer_flush_carries_decision_lineage(journal):
    journal.defer("decision_context", symbol="ETHUSDT", latency_ms=40)
    journal.defer("memory_retrieval", symbol="ETHUSDT", latency_ms=6)
    written = await journal.flush(
        decision_id="dec-lineage-1", llm_invocation_id="llm-1"
    )
    assert written == 2
    async with journal.session_factory() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT decision_id, llm_invocation_id, tool_name FROM "
                    "tool_invocations ORDER BY id"
                )
            )
        ).all()
    assert [(r[0], r[1]) for r in rows] == [
        ("dec-lineage-1", "llm-1"),
        ("dec-lineage-1", "llm-1"),
    ]
    assert {r[2] for r in rows} == {"decision_context", "memory_retrieval"}


async def test_buffer_bounded_and_never_raises(journal):
    for i in range(250):
        journal.defer("opportunity_scan", symbol="X", latency_ms=i)
    assert len(journal._buffer) <= 100
    written = await journal.flush(decision_id="dec-bounded")
    assert written == 100


async def test_fail_safe_write(database):
    """Journal write failure must be counted, never raised, never silent."""

    class BrokenFactory:
        def __call__(self):
            raise RuntimeError("db closed")

    j = ToolInvocationJournal(BrokenFactory)
    await j.record("factor_snapshot", symbol="BTCUSDT")  # must not raise
    assert j.write_failures == 1


async def test_chief_trader_defers_and_flushes_lineage(database):
    """End-to-end in the decision pipeline: context build defers tool rows;
    evidence persist flushes them with the decision id."""
    from crypto_trader.runtime.chief_trader_strategy import ChiefTraderStrategyAdapter
    from types import SimpleNamespace
    from datetime import UTC, datetime

    journal = ToolInvocationJournal(database.session_factory)
    adapter = ChiefTraderStrategyAdapter(provider=None, tool_journal=journal)
    ctx = SimpleNamespace(
        symbol="BTCUSDT",
        positions={},
        clock_time=datetime.now(UTC),
        mark_price=60000.0,
        funding=None,
        oi=None,
    )
    # memory tool path (provider absent -> no row); decision context absent.
    # Simulate the two deferred calls the pipeline would produce:
    adapter._defer_tool_call("decision_context", "BTCUSDT", time.monotonic() - 0.01, "OK")
    adapter._defer_tool_call("memory_retrieval", "BTCUSDT", time.monotonic() - 0.005, "OK")
    decision = SimpleNamespace(
        decision_id="dec-e2e-journal",
        thesis="t",
        model_version="mv",
        domain_model_version="dv",
        llm_invocation_id="llm-e2e",
        selected_strategy="mean_reversion",
        strategy_version="sv",
        strategy_fit_score=0.7,
        market_regime="RISK_OFF",
        factor_snapshot_id="fs",
        factor_set_version="fsv",
        factor_profile="default",
        raw_llm_confidence=0.7,
        evidence_adjusted_confidence=0.7,
        decision_class="NO_TRADE",
        action="HOLD",
        exploration_mode=False,
        secondary_strategies=[],
        supporting_factors=[],
        contradicting_factors=[],
        dominant_factor="",
        position_size_request=0.0,
        leverage_request=0.0,
    )
    decision.model_dump = lambda mode="json": {"decision_id": decision.decision_id}
    stored = {}

    class CaptureBackend:
        async def store_decision(self, evidence):
            stored.update(evidence)

    adapter.evidence_backend = CaptureBackend()
    chief_ctx = SimpleNamespace(
        symbol="BTCUSDT",
        regime="RISK_OFF",
        factor_snapshot={},
        strategy_evidence={"strategy_candidates": []},
    )
    await adapter._persist_evidence(decision, ctx, chief_ctx)
    from sqlalchemy import text as _t

    async with journal.session_factory() as session:
        rows = (
            await session.execute(
                _t(
                    "SELECT tool_name, decision_id FROM tool_invocations "
                    "WHERE decision_id = 'dec-e2e-journal'"
                )
            )
        ).all()
    rows = [{"tool_name": r[0], "decision_id": r[1]} for r in rows]
    assert {r["tool_name"] for r in rows} >= {"decision_context", "memory_retrieval"}
    assert all(r["decision_id"] == "dec-e2e-journal" for r in rows)


async def test_utility_report_pairs_episodes(database, journal):
    """§57-§62 pairing: tool rows joined to episodes through decision
    lineage_json -> factual WIN/LOSS + mean net pnl with the disclaimer."""
    from sqlalchemy import text as _t

    # NOTE: separate sessions + SQLite write lock — run the committing
    # backend insert FIRST, then the raw inserts in one short transaction.
    from crypto_trader.evolution.persistence_backends import SqlEvidenceBackend

    backend = SqlEvidenceBackend(journal.session_factory)
    await backend.store_decision({
        "decision_id": "dec-pair-1",
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "symbol": "TRXUSDT",
        "timeframe": "1m",
        "strategy_id": "ai_brain",
        "strategy_version": "v1",
        "model_version": "m",
        "prompt_version": "p",
        "factor_snapshot_id": "fs",
        "factor_set_version": "fv",
        "factor_profile": "prof",
        "market_data_reference": "ref",
        "analysis_evidence": {},
        "decision": {},
        "risk_decision": {},
        "execution_intent_reference": "ref",
        "domain_model_version": "dv",
        "created_at_utc": datetime.now(UTC).isoformat(),
    })
    async with journal.session_factory() as session:
        await session.execute(_t(
            "INSERT INTO tool_invocations (invocation_uid, tool_name, decision_id, "
            "symbol, status, latency_ms, detail, created_at) VALUES "
            "('tool-uid-pair1', 'opportunity_scan', 'dec-pair-1', 'TRXUSDT', 'OK', 9, '', datetime('now'))"
        ))
        await session.execute(_t(
            "INSERT INTO ai_trade_episodes (episode_id, symbol, market_regime, "
            "market_snapshot_json, quant_evidence_json, strategy_selected, "
            "llm_reasoning, entry_price, exit_price, position_size, leverage, "
            "holding_time_seconds, pnl, mfe, mae, result, review_status, created_at, "
            "market_type, direction, exit_reason, lineage_json, gross_pnl, fees, "
            "net_pnl) VALUES ('eps-pair-1', 'TRXUSDT', 'RISK_OFF', '{}', '{}', "
            "'ai_brain', 'test', 0.26, 0.261, 0.001, 1, 1000, 2.5, 0, 0, 'WIN', "
            "'NEW', datetime('now'), 'SPOT', 'LONG', 'TP', "
            "'{\"decision_id\": \"dec-pair-1\"}', 2.5, 0, 2.5)"
        ))
        await session.commit()
    report = await journal.utility_report(window_hours=24)
    pairing = report["decision_outcome_pairing"]["opportunity_scan"]
    assert pairing["episodes"] == 1
    assert pairing["WIN"] == 1
    assert pairing["mean_net_pnl"] == 2.5
    lesson = await journal.emit_lesson(report)
    assert lesson is not None and lesson.startswith("lesson-tool-")
    async with journal.session_factory() as session:
        row = (
            await session.execute(
                _t("SELECT canonical_statement FROM learning_lessons WHERE lesson_id = :i"),
                {"i": lesson},
            )
        ).first()
    assert "CORRELATION_NOT_CAUSATION" in row[0]
    assert "no trading gate, no risk bypass" in row[0]


async def test_budget_param_readable_from_policy(database):
    """tool_call_budget_per_decision is hot-policy readable (§21 wiring)."""
    from crypto_trader.governance.runtime_policy import RuntimePolicyManager

    mgr = RuntimePolicyManager(database.session_factory)
    await mgr.initialize()
    value = mgr.param("tool_call_budget_per_decision", cast=int)
    assert 2 <= value <= 12
