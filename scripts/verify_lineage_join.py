#!/usr/bin/env python
"""Read-only lineage verification for the Codex Supervisor (P3/P4).

This script runs ONLY SELECT/PRAGMA queries against the canonical paper DB
and read-only GETs against the running runtime. It never writes, never
migrates, never mutates any row, and never places orders.

Usage:
    .venv/bin/python scripts/verify_lineage_join.py [DB_PATH]

Sections:
    RUNTIME         running SHA (must equal `git rev-parse HEAD`), mode
    MIGRATIONS      alembic head (expect 0024_tool_lineage_audit)
    P4_JOIN         canonical three-way Episode -> entry Decision -> Tool
                    join plus the per-episode classification that explains
                    the count (pre-journal vs post-journal entry decision)
    P4_AUDIT        bounded tool audit-field coverage on post-deploy rows
    P3_ATTENTION    AI attention lineage rows and selection modes
    SAFETY          duplicate-id checks, reconciliation status, leases

Exit code is always 0: this is an evidence printer, not a gate.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import urllib.request

DB_DEFAULT = "data/crypto_trader.db"
RUNTIME = "http://127.0.0.1:8000"

THREE_WAY_JOIN = """
SELECT COUNT(*)
FROM tool_invocations ti
JOIN decision_evidence de ON de.decision_id = ti.decision_id
JOIN ai_trade_episodes ep
  ON COALESCE(ep.entry_decision_id,
              json_extract(ep.lineage_json, '$.entry_decision_id'),
              json_extract(ep.lineage_json, '$.decision_id')) = ti.decision_id
"""

EPISODE_CLASSIFICATION = """
SELECT ep.episode_id,
       ep.symbol,
       ep.entry_decision_id,
       (SELECT de.created_at FROM decision_evidence de
         WHERE de.decision_id = ep.entry_decision_id) AS entry_decision_at,
       (SELECT COUNT(*) FROM tool_invocations ti
         WHERE ti.decision_id = ep.entry_decision_id) AS tool_rows
FROM ai_trade_episodes ep
WHERE ep.entry_decision_id IS NOT NULL
ORDER BY ep.id DESC
LIMIT 12
"""

# Journal deployment instant (first recorded tool_invocation row).
JOURNAL_START = "SELECT MIN(created_at) FROM tool_invocations"


def _q(conn: sqlite3.Connection, sql: str, args=()):
    return conn.execute(sql, args).fetchall()


def _runtime(path: str):
    try:
        with urllib.request.urlopen(f"{RUNTIME}{path}", timeout=5) as resp:
            return json.loads(resp.read().decode())
    except Exception as exc:  # read-only probe, never fatal
        return {"error": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    db_path = sys.argv[1] if len(sys.argv) > 1 else DB_DEFAULT
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)

    print("== RUNTIME ==")
    version = _runtime("/version")
    ready = _runtime("/ready")
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True,
            timeout=5, check=True,
        ).stdout.strip()
    except Exception as exc:
        head = f"UNKNOWN ({type(exc).__name__})"
    running_sha = version.get("git_sha", "?")
    print(f"ready            : {ready.get('ready')} mode={ready.get('mode')}")
    print(f"running_sha      : {running_sha} (source={version.get('sha_source')})")
    print(f"git_head         : {head}")
    print(f"sha_matches_head : {running_sha == head}")

    print("\n== MIGRATIONS ==")
    head_db = _q(conn, "SELECT version_num FROM alembic_version")[0][0]
    print(f"alembic_head     : {head_db}")

    print("\n== P4_JOIN (canonical Episode -> entry Decision -> Tool) ==")
    join_count = _q(conn, THREE_WAY_JOIN)[0][0]
    journal_start = _q(conn, JOURNAL_START)[0][0]
    (total_eps, linked_eps) = _q(
        conn,
        "SELECT COUNT(*), COALESCE(SUM(entry_decision_id IS NOT NULL),0) "
        "FROM ai_trade_episodes",
    )[0]
    print(f"journal_started  : {journal_start}")
    print(f"episodes_total   : {total_eps}  linked(link is factual)={linked_eps}")
    print(f"three_way_join   : {join_count}")
    print("-- newest linked episodes (entry-decision timing) --")
    for ep_id, symbol, dec, dec_at, tool_rows in _q(conn, EPISODE_CLASSIFICATION):
        if dec_at is None:
            klass = "ENTRY_DECISION_EVIDENCE_MISSING"
        else:
            klass = (
                "POST_JOURNAL (eligible)"
                if str(dec_at) >= str(journal_start or "")
                else "PRE_JOURNAL (honest gap, tool rows cannot exist)"
            )
        print(
            f"  {ep_id} {symbol:<12} entry_dec={str(dec)[:18]}… "
            f"created={dec_at} tools={tool_rows} [{klass}]"
        )

    print("\n== P4_AUDIT (bounded tool audit fields) ==")
    rows = _q(
        conn,
        "SELECT COUNT(*), "
        "SUM(tool_version <> ''), SUM(source <> ''), "
        "SUM(cache_state <> ''), SUM(evidence_added <> ''), "
        "COALESCE(MAX(LENGTH(error)),0), COALESCE(MAX(LENGTH(detail)),0) "
        "FROM tool_invocations",
    )[0]
    (
        total, with_ver, with_src, with_cache, with_ev, max_err, max_detail,
    ) = rows
    print(
        f"rows={total} tool_version={with_ver} source={with_src} "
        f"cache_state={with_cache} evidence_added={with_ev}"
    )
    print(f"max_error_len={max_err} (<=255) max_detail_len={max_detail} (<=255)")
    print("-- post-deploy rows with decision + own LLM ids --")
    for tool, dec, llm, src, cache, ev in _q(
        conn,
        "SELECT tool_name, decision_id, llm_invocation_id, source, "
        "cache_state, evidence_added FROM tool_invocations "
        "WHERE created_at >= ? AND tool_version <> '' "
        "ORDER BY id DESC LIMIT 6",
        (journal_start,),
    ):
        print(
            f"  {tool:<26} dec={str(dec or '')[:16]}… llm={str(llm or '')[:16]}… "
            f"src={src} cache={cache} ev_added={ev}"
        )

    print("\n== P3_ATTENTION (AI-owned attention lineage) ==")
    for row in _q(
        conn,
        "SELECT attention_uid, mode, roster_size, universe_size, latency_ms, "
        "created_at FROM market_attention_decisions ORDER BY id DESC LIMIT 5",
    ):
        print(f"  uid={row[0][:16]}… mode={row[1]} roster={row[2]} "
              f"universe={row[3]} latency_ms={row[4]} at={row[5]}")
    modes = _q(
        conn,
        "SELECT group_concat(m || ':' || c, ', ') FROM (SELECT mode m, "
        "COUNT(*) c FROM market_attention_decisions GROUP BY mode)",
    )[0][0]
    print(f"mode_counts      : {modes}")
    att_evidence = _q(
        conn,
        "SELECT COUNT(*) FROM decision_evidence "
        "WHERE analysis_evidence_json LIKE '%market_observer_attention%'",
    )[0][0]
    print(f"decisions_carrying_attention_evidence: {att_evidence}")

    print("\n== SAFETY (read-only) ==")
    for label, sql in [
        ("dup_episode_ids", "SELECT COUNT(*)-COUNT(DISTINCT episode_id) "
                            "FROM ai_trade_episodes"),
        ("dup_decision_ids", "SELECT COUNT(*)-COUNT(DISTINCT decision_id) "
                             "FROM decision_evidence"),
        ("open_leases", "SELECT COUNT(*) FROM runtime_leases"),
    ]:
        print(f"{label:<18}: {_q(conn, sql)[0][0]}")
    recon = _q(
        conn,
        "SELECT status, compared_at FROM reconciliation_runs "
        "ORDER BY id DESC LIMIT 1",
    )
    print(f"reconciliation   : {recon[0] if recon else 'NO_RUNS'}")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
