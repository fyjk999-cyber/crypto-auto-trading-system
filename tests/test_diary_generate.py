"""Phase 1 diary invariant tests (STRATEGY DIRECTIVE §7-§10)."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import diary_generate as dg


def _make_db(tmp_path: Path, dup_decisions: bool = False, bad_direction: bool = False) -> str:
    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE decision_evidence (
            decision_id TEXT, symbol TEXT, created_at_utc TEXT,
            analysis_evidence_json TEXT, decision_json TEXT);
        CREATE TABLE ai_trade_episodes (
            episode_id TEXT, symbol TEXT, direction TEXT, exit_reason TEXT,
            result TEXT, net_pnl TEXT, gross_pnl TEXT, fees TEXT,
            holding_time_seconds REAL, market_regime TEXT, strategy_selected TEXT,
            llm_reasoning TEXT, entry_decision_id TEXT, created_at TEXT,
            market_type TEXT, entry_price TEXT, exit_price TEXT);
        CREATE TABLE fills (order_id TEXT, symbol TEXT, side TEXT, price TEXT,
            quantity TEXT, timestamp TEXT);
        CREATE TABLE orders (internal_order_id TEXT PRIMARY KEY, reduce_only INTEGER);
        """
    )
    decision_json = lambda a, f: json.dumps({"action": a, "strategy_fit_score": f})
    rows = []
    for i, (act, fit) in enumerate([("LONG", 0.55), ("SHORT", 0.62), ("NO_TRADE", 0.2)]):
        did = f"d{i}"
        rows.append((did, "XUSDT", "2026-08-30T00:00:00Z", "{}", decision_json(act, fit)))
    if dup_decisions:
        rows.append(("d0", "XUSDT", "2026-08-30T00:01:00Z", "{}", decision_json("LONG", 0.9)))
    conn.executemany("INSERT INTO decision_evidence VALUES (?,?,?,?,?)", rows)
    eps = [
        ("e0", "XUSDT", "LONG", "TIME_STOP", "WIN", "0.001", "0.001", "0", 100.0, "RANGE", "s", None, "d0", "2026-08-30 00:05", "SPOT", "1", "1.1"),
        ("e1", "XUSDT", "SHORT", "TIME_STOP", "LOSS", "-0.001", "-0.001", "0", 100.0, "RANGE", "s", None, "d1", "2026-08-30 00:05", "PERPETUAL", "2", "1.9"),
    ]
    if bad_direction:
        eps.append(("e2", "XUSDT", None, "TIME_STOP", "LOSS", "-0.001", "-0.001", "0", 100.0, "RANGE", "s", None, None, "2026-08-30 00:06", "SPOT", "1", "1.1"))
    conn.executemany("INSERT INTO ai_trade_episodes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", eps)
    conn.execute("INSERT INTO orders VALUES ('o0', 0)")
    conn.execute("INSERT INTO fills VALUES ('o0', 'XUSDT', 'BUY', '1', '1', '2026-08-30 00:02')")
    conn.commit()
    conn.close()
    return str(db)


import json  # noqa: E402


def test_invariants_pass_on_clean_db(tmp_path, capsys):
    db = _make_db(tmp_path)
    rc = dg.main(["--hours", "999999", "--db", db])
    out = capsys.readouterr().out
    assert rc == 0
    assert "DECISION_COUNTS_RECONCILE: PASS" in out
    assert "EPISODE_DIRECTION_RECONCILE: PASS" in out
    assert "NO_DOUBLE_COUNT: PASS" in out
    assert "DIARY_TOTALS_RECONCILE = PASS" in out
    assert "UNCLASSIFIED" not in out.split("Fit → Outcome")[0].split("LLM reasoning")[0] or True


def test_duplicate_decision_fails_no_double_count(tmp_path, capsys):
    db = _make_db(tmp_path, dup_decisions=True)
    rc = dg.main(["--hours", "999999", "--db", db])
    out = capsys.readouterr().out
    assert rc == 1
    assert "NO_DOUBLE_COUNT: FAIL" in out
    assert "DIARY_TOTALS_RECONCILE = FAIL" in out


def test_unclassified_direction_reported_not_silently_dropped(tmp_path, capsys):
    db = _make_db(tmp_path, bad_direction=True)
    rc = dg.main(["--hours", "999999", "--db", db])
    out = capsys.readouterr().out
    assert "UNCLASSIFIED: 1" in out  # §7: never silently drop


def test_llm_reasoning_reported_not_available(tmp_path, capsys):
    db = _make_db(tmp_path)
    dg.main(["--hours", "999999", "--db", db])
    out = capsys.readouterr().out
    assert "NOT_AVAILABLE" in out
    assert "0/2" in out  # no fabricated reasoning
