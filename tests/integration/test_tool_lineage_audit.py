"""P2 CS-20260830-034530-P4-TOOL-LINEAGE acceptance tests.

Directive coverage:
FULL_AUDIT_FIELDS      : every required bounded audit field is recorded
                         (tool/version, source, cache state, start/end/
                         latency, status, bounded summary, bounded error)
BOUNDED_REDACTION      : no raw prompts / payloads / oversized text
                         persisted; fields bounded at the contract limits
DECISION_TOOL_TRACE    : isolated real-pipeline test proving Decision ->
                         Tool trace with tool-level llm id preserved
EPISODE_TOOL_TRACE     : durable Episode -> entry Decision -> Tool trace via
                         the immutable entry_decision_id; historical
                         unknowns stay honestly NULL (no fabrication)
FAILURE_ISOLATED       : tool failure records TOOL-bounded error without
                         crashing the runtime path
UTILITY_FACTORS        : report groups regime/strategy/symbol with sample
                         sizes, cost, decision-change and information value,
                         all correlation-labelled and non-authoritative
IMMUTABLE_LINK         : replay never overwrites a populated entry decision
                         link and never invents one
"""

import json
import sqlite3
from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from crypto_trader.governance.tool_journal import ToolInvocationJournal


@pytest.fixture()
async def journal(database):
    return ToolInvocationJournal(database.session_factory)


# ---------------------------------------------------------- FULL_AUDIT_FIELDS


async def test_full_audit_fields_recorded_and_bounded(journal):
    await journal.record(
        "market_observer_ai",
        decision_id="dec-audit-1",
        llm_invocation_id="llm-att-1",
        symbol="BTCUSDT",
        latency_ms=1234,
        status="OK",
        detail="mode=AI_SELECTED selected=2 roster=48 uid=att-x",
        tool_version="1.0.0",
        source="market_observer",
        cache_state="REFRESH",
        error="",
        evidence_added="ADDED",
    )
    async with journal.session_factory() as session:
        row = (
            await session.execute(
                text(
                    "SELECT tool_name, decision_id, llm_invocation_id, symbol, "
                    "status, latency_ms, detail, tool_version, source, "
                    "cache_state, started_at, finished_at, error, "
                    "evidence_added FROM tool_invocations WHERE "
                    "decision_id = 'dec-audit-1'"
                )
            )
        ).one()
    assert row.tool_name == "market_observer_ai"
    assert row.decision_id == "dec-audit-1"
    assert row.llm_invocation_id == "llm-att-1"
    assert row.symbol == "BTCUSDT"
    assert row.status == "OK"
    assert row.latency_ms == 1234
    assert row.tool_version == "1.0.0"
    assert row.source == "market_observer"
    assert row.cache_state == "REFRESH"
    assert row.evidence_added == "ADDED"
    assert row.error == ""
    assert row.started_at is not None and row.finished_at is not None
    # started <= finished, spaced by the recorded latency (~1.2s)
    started = datetime.fromisoformat(str(row.started_at))
    finished = datetime.fromisoformat(str(row.finished_at))
    delta = (finished - started).total_seconds()
    assert 1.0 <= delta <= 2.0


async def test_error_field_bounded_and_payload_free(journal):
    """A failing tool records a bounded error; raw payloads never persist."""
    huge_payload_error = ("UPSTREAM_RETURNED secrets sk-test-abcdef123456 " + "x" * 5000)
    await journal.record(
        "research_gateway",
        symbol="ETHUSDT",
        latency_ms=50,
        status="ERROR",
        detail=f"payload={huge_payload_error[:80]}",
        error=huge_payload_error,
    )
    async with journal.session_factory() as session:
        row = (
            await session.execute(
                text(
                    "SELECT error, detail, length(error), length(detail) "
                    "FROM tool_invocations WHERE symbol='ETHUSDT' "
                    "AND status='ERROR'"
                )
            )
        ).one()
    assert row[2] <= 255, "error bounded"
    assert row[3] <= 255, "detail bounded"
    assert "x" * 300 not in row[0], "oversized payload truncated"


async def test_row_level_llm_invocation_survives_flush(journal):
    """A tool's own LLM invocation id wins over the decision-level one."""
    journal.defer(
        "market_observer_ai", symbol="BTCUSDT", latency_ms=5,
        llm_invocation_id="llm-attention-own",
    )
    journal.defer(
        "memory_retrieval", symbol="BTCUSDT", latency_ms=3,
    )
    await journal.flush(decision_id="dec-llm-own", llm_invocation_id="llm-decision")
    async with journal.session_factory() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT tool_name, llm_invocation_id FROM tool_invocations "
                    "WHERE decision_id='dec-llm-own' ORDER BY tool_name"
                )
            )
        ).all()
    by_tool = {r[0]: r[1] for r in rows}
    assert by_tool["market_observer_ai"] == "llm-attention-own"
    assert by_tool["memory_retrieval"] == "llm-decision", "fallback applies"


# ------------------------------------------------------- DECISION_TOOL_TRACE


async def test_decision_to_tool_trace_flushes_audit_fields(database, journal):
    """Buffered rows flush WITH the decision lineage AND their audit fields
    intact (Decision -> Tool trace, P4 contract)."""
    journal.defer(
        "decision_context", symbol="BTCUSDT", latency_ms=12,
        tool_version="1.0.0", source="chief_trader_entry",
        cache_state="MISS", evidence_added="ADDED",
    )
    journal.defer(
        "market_observer_ai", symbol="BTCUSDT", latency_ms=40,
        tool_version="1.0.0", source="market_observer", cache_state="REFRESH",
        detail="mode=AI_SELECTED selected=3 uid=att-abc",
        evidence_added="ADDED", llm_invocation_id="llm-att-own",
    )
    written = await journal.flush(
        decision_id="dec-p4-trace", llm_invocation_id="llm-decision-1"
    )
    assert written == 2
    async with journal.session_factory() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT tool_name, decision_id, llm_invocation_id, "
                    "tool_version, source, cache_state, evidence_added, "
                    "started_at IS NOT NULL, finished_at IS NOT NULL "
                    "FROM tool_invocations WHERE decision_id='dec-p4-trace' "
                    "ORDER BY tool_name"
                )
            )
        ).all()
    by_tool = {r[0]: r for r in rows}
    assert all(r[1] == "dec-p4-trace" for r in rows)
    assert by_tool["decision_context"][3] == "1.0.0"
    assert by_tool["decision_context"][4] == "chief_trader_entry"
    assert by_tool["decision_context"][5] == "MISS"
    assert by_tool["decision_context"][6] == "ADDED"
    assert by_tool["market_observer_ai"][2] == "llm-att-own"
    assert by_tool["market_observer_ai"][6] == "ADDED"
    assert all(r[7] == 1 and r[8] == 1 for r in rows), "start/end recorded"


# ------------------------------------------------------- EPISODE_TOOL_TRACE


def _seed_full_cycle_facts(db_path: str, *, entry_decision_id: str | None) -> None:
    conn = sqlite3.connect(db_path)
    try:
        schema = [
            ("orders", "internal_order_id TEXT PRIMARY KEY, client_order_id TEXT, "
             "symbol TEXT, side TEXT, reduce_only INTEGER, strategy_id TEXT, "
             "status TEXT, quantity TEXT, metadata_json TEXT"),
            ("fills", "id INTEGER PRIMARY KEY AUTOINCREMENT, fill_id TEXT, "
             "order_id TEXT, symbol TEXT, side TEXT, price TEXT, quantity TEXT, "
             "fee TEXT, fee_currency TEXT, timestamp TEXT, payload_json TEXT"),
            ("ledger_transactions", "transaction_id TEXT PRIMARY KEY, entry_type TEXT, "
             "order_id TEXT, metadata_json TEXT"),
            ("audit_events", "action TEXT, target TEXT, after_json TEXT, "
             "timestamp TEXT, order_id TEXT"),
        ]
        for table, ddl in schema:
            conn.execute(f"CREATE TABLE IF NOT EXISTS {table} ({ddl})")
        conn.execute(
            "INSERT INTO orders VALUES ('ord-e1','cli-e1','BTCUSDT','BUY',0,"
            "'ai_brain','FILLED','0.001',?)",
            (json.dumps({"decision_id": entry_decision_id or "",
                         "signal_id": "sig-e1"}),),
        )
        conn.execute(
            "INSERT INTO orders VALUES ('ord-x1','cli-x1','BTCUSDT','SELL',1,"
            "'ai_brain','FILLED','0.001',?)",
            (json.dumps({"exit_reason": "TIME_STOP"}),),
        )
        ts_in = "2026-08-30 04:00:00.000000"
        ts_out = "2026-08-30 05:00:00.000000"
        conn.execute(
            "INSERT INTO fills (fill_id, order_id, symbol, side, price, quantity, "
            "fee, fee_currency, timestamp, payload_json) VALUES "
            "('fill-e1','ord-e1','BTCUSDT','BUY','60000','0.001','0','USDT',?,?)",
            (ts_in, json.dumps({"decision_id": entry_decision_id or "",
                                "signal_id": "sig-e1",
                                "market_type": "SPOT"})),
        )
        conn.execute(
            "INSERT INTO fills (fill_id, order_id, symbol, side, price, quantity, "
            "fee, fee_currency, timestamp, payload_json) VALUES "
            "('fill-x1','ord-x1','BTCUSDT','SELL','61000','0.001','0','USDT',?,?)",
            (ts_out, json.dumps({"exit_reason": "TIME_STOP", "market_type": "SPOT"})),
        )
        conn.commit()
    finally:
        conn.close()


def _test_db_schema(db_path: str) -> None:
    """ai_trade_episodes schema as produced by migration 0024 (test-local)."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS ai_trade_episodes (id INTEGER PRIMARY KEY "
            "AUTOINCREMENT, episode_id TEXT UNIQUE, symbol TEXT, market_regime TEXT, "
            "market_snapshot_json TEXT DEFAULT '{}', quant_evidence_json TEXT "
            "DEFAULT '[]', strategy_selected TEXT, llm_reasoning TEXT, entry_price "
            "TEXT, exit_price TEXT, position_size TEXT, leverage TEXT, "
            "holding_time_seconds TEXT, pnl TEXT, mfe TEXT DEFAULT '0', mae TEXT "
            "DEFAULT '0', result TEXT, review_status TEXT, created_at TEXT, "
            "market_type TEXT DEFAULT 'SPOT', direction TEXT DEFAULT 'LONG', "
            "exit_reason TEXT, gross_pnl TEXT, fees TEXT, net_pnl TEXT, "
            "lineage_json TEXT, entry_decision_id TEXT)"
        )
        conn.commit()
    finally:
        conn.close()


async def test_episode_entry_decision_link_populated_without_fabrication(
    tmp_path, journal
):
    """Episode -> entry decision link comes from the fill payload only."""
    from crypto_trader.governance.trade_episodes import (
        ensure_columns,
        record_all_cycles_sync,
    )

    db_path = str(tmp_path / "episodes.db")
    _test_db_schema(db_path)
    _seed_full_cycle_facts(db_path, entry_decision_id="dec-entry-real")
    conn = sqlite3.connect(db_path)
    try:
        assert ensure_columns(conn) == []
    finally:
        conn.close()
    result = record_all_cycles_sync(db_path)
    assert result["inserted"] == 1
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT episode_id, entry_decision_id, "
            "json_extract(lineage_json, '$.entry_decision_id') "
            "FROM ai_trade_episodes"
        ).fetchone()
    finally:
        conn.close()
    assert row[1] == "dec-entry-real", "factual link from fill payload"
    assert row[2] == "dec-entry-real"


async def test_episode_link_stays_null_when_unknown(tmp_path):
    """Historical unknown: no decision id in the payload -> NULL, never a
    guessed value (do-not-fabricate contract)."""
    from crypto_trader.governance.trade_episodes import record_all_cycles_sync

    db_path = str(tmp_path / "episodes_unknown.db")
    _test_db_schema(db_path)
    _seed_full_cycle_facts(db_path, entry_decision_id=None)
    record_all_cycles_sync(db_path)
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT entry_decision_id FROM ai_trade_episodes"
        ).fetchone()
    finally:
        conn.close()
    assert row[0] is None, "unknown link stays honestly NULL"


async def test_episode_link_immutable_across_replay(tmp_path):
    """Replay re-derives facts but NEVER overwrites a populated link and
    NEVER invents one for a row created without it."""
    from crypto_trader.governance.trade_episodes import record_all_cycles_sync

    db_path = str(tmp_path / "episodes_immutable.db")
    _test_db_schema(db_path)
    _seed_full_cycle_facts(db_path, entry_decision_id="dec-first")
    first = record_all_cycles_sync(db_path)
    assert first["inserted"] == 1
    # tamper check equivalent: a replayed pipeline with a DIFFERENT payload
    # must not rewrite the immutable link
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("UPDATE fills SET payload_json=? WHERE fill_id='fill-e1'",
                     (json.dumps({"decision_id": "dec-other"}),))
        conn.commit()
    finally:
        conn.close()
    second = record_all_cycles_sync(db_path)
    assert second["existed"] == 1
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT entry_decision_id FROM ai_trade_episodes"
        ).fetchone()
    finally:
        conn.close()
    assert row[0] == "dec-first", "immutable link survives replay"


async def test_utility_join_episode_to_decision_to_tools(database, journal):
    """The previously-zero three-way join works through the new immutable
    column (and legacy lineage keys)."""
    async with journal.session_factory() as session:
        await session.execute(text(
            "INSERT INTO decision_evidence (decision_id, timestamp_utc, symbol, "
            "timeframe, strategy_id, strategy_version, model_version, "
            "prompt_version, factor_snapshot_id, factor_set_version, "
            "factor_profile, market_data_reference, analysis_evidence_json, "
            "decision_json, risk_decision_json, execution_intent_reference, "
            "created_at_utc, created_at, domain_model_version) VALUES "
            "('dec-p4-join', :ts, 'TRXUSDT', '1m', 'ai_brain', 'v1', 'm', 'p', "
            "'fs', 'fv', 'prof', 'ref', :ae, '{}', '{}', 'ref', :ts, :ts, 'dv')"
        ), {
            "ts": datetime.now(UTC).isoformat(),
            "ae": json.dumps({
                "market_regime": "RISK_OFF",
                "selected_strategy": "breakout",
            }),
        })
        await session.commit()
    await journal.record(
        "market_observer_ai", decision_id="dec-p4-join", symbol="TRXUSDT",
        latency_ms=9, tool_version="1.0.0", source="market_observer",
        cache_state="REFRESH", evidence_added="ADDED",
    )
    await journal.record(
        "decision_context", decision_id="dec-p4-join", symbol="TRXUSDT",
        latency_ms=4, evidence_added="ADDED",
    )
    async with journal.session_factory() as session:
        await session.execute(text(
            "INSERT INTO ai_trade_episodes (episode_id, symbol, market_regime, "
            "strategy_selected, llm_reasoning, entry_price, exit_price, "
            "position_size, leverage, holding_time_seconds, pnl, mfe, mae, "
            "result, review_status, created_at, market_type, direction, "
            "exit_reason, lineage_json, net_pnl, entry_decision_id) VALUES "
            "('eps-p4-join', 'TRXUSDT', 'RISK_OFF', 'ai_brain', '', 0.26, 0.27, "
            "0.001, 1, 600, 1.5, 0, 0, 'WIN', 'NEW', datetime('now'), 'SPOT', "
            "'LONG', 'TP', '{}', 1.5, 'dec-p4-join')"
        ))
        await session.commit()
    report = await journal.utility_report(window_hours=24)
    pairing = report["decision_outcome_pairing"]["market_observer_ai"]
    assert pairing["episodes"] == 1 and pairing["WIN"] == 1
    assert pairing["mean_net_pnl"] == 1.5
    factors = report["factor_analysis"]["per_tool"]["market_observer_ai"]
    assert factors["regime"]["RISK_OFF"]["episodes"] == 1
    assert factors["strategy"]["breakout"]["episodes"] == 1
    assert factors["symbol"]["TRXUSDT"]["sample_size"] == 1
    assert report["factor_analysis"]["global"]["regime"]["RISK_OFF"]["episodes"] == 2
    change = report["decision_change"]["market_observer_ai"]
    assert change["ADDED"] == 1 and change["added_rate"] == 1.0
    info = report["information_value"]["market_observer_ai"]
    assert info["ADDED"]["win_rate"] == 1.0
    assert "CORRELATION_NOT_CAUSATION" in report["information_value_note"]


async def test_utility_report_cannot_alter_authoritative_state(database, journal):
    """Report + lesson emission are read-only for decisions/orders/fills."""
    await journal.record("factor_snapshot", symbol="BTCUSDT", latency_ms=5)
    async with journal.session_factory() as session:
        counts_before = (
            await session.execute(
                text(
                    "SELECT (SELECT COUNT(*) FROM decision_evidence), "
                    "(SELECT COUNT(*) FROM orders), (SELECT COUNT(*) FROM fills), "
                    "(SELECT COUNT(*) FROM learning_lessons)"
                )
            )
        ).one()
    report = await journal.utility_report(window_hours=24)
    await journal.emit_lesson(report)
    async with journal.session_factory() as session:
        counts_after = (
            await session.execute(
                text(
                    "SELECT (SELECT COUNT(*) FROM decision_evidence), "
                    "(SELECT COUNT(*) FROM orders), (SELECT COUNT(*) FROM fills), "
                    "(SELECT COUNT(*) FROM learning_lessons)"
                )
            )
        ).one()
    assert counts_before[:3] == counts_after[:3], (
        "decisions/orders/fills untouched by reporting"
    )
    assert counts_after[3] == counts_before[3] + 1, "only one advisory lesson row"


async def test_tool_failure_isolated_from_runtime(journal):
    """A tool error row is recorded without raising; journal failures are
    counted, never propagated (failure isolation contract)."""

    class BrokenFactory:
        def __call__(self):
            raise RuntimeError("db closed")

    broken = ToolInvocationJournal(BrokenFactory)
    await broken.record(
        "memory_retrieval", status="ERROR", error="Boom: connection refused",
        symbol="BTCUSDT",
    )
    assert broken.write_failures == 1 and broken.recorded == 0
    # healthy journal records the failure row with a bounded error
    await journal.record(
        "memory_retrieval", status="ERROR", error="E" * 1000, symbol="BTCUSDT",
        tool_version="1.0.0", source="chief_trader_entry", evidence_added="EMPTY",
    )
    async with journal.session_factory() as session:
        row = (
            await session.execute(
                text(
                    "SELECT status, length(error), source FROM tool_invocations "
                    "WHERE status='ERROR'"
                )
            )
        ).one()
    assert row[0] == "ERROR" and row[1] <= 255 and row[2] == "chief_trader_entry"
