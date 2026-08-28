"""One-shot PAPER exploration smoke status snapshot (read-only)."""
import json
import sqlite3

c = sqlite3.connect("data/crypto_trader.db")

# Decisions since smoke start
rows = c.execute(
    "SELECT timestamp_utc, decision_id, decision_json, analysis_evidence_json, "
    "factor_snapshot_id FROM decision_evidence WHERE timestamp_utc > '2026-08-28T08:46' "
    "ORDER BY timestamp_utc ASC"
).fetchall()
classes = {}
actions = {}
reasons = {}
llm_called = 0
mem_refs = 0
risk_notes = []
for ts, did, dj, aj, _snap in rows:
    d = json.loads(dj)
    a = json.loads(aj)
    cls = a.get("decision_class") or (
        d.get("action") if d.get("action") == "NO_TRADE" else "UNKNOWN"
    )
    classes[cls] = classes.get(cls, 0) + 1
    actions[d.get("action")] = actions.get(d.get("action"), 0) + 1
    for r in d.get("reason_codes") or []:
        reasons[r] = reasons.get(r, 0) + 1
    if not did.startswith("gate_"):
        llm_called += 1
    if a.get("memory_refs"):
        mem_refs += 1
    # Entry proposals: show their risk note and execution reference
    if d.get("action") in ("LONG", "SHORT"):
        risk_notes.append(
            (ts[11:19], d.get("action"), a.get("decision_class"),
             "exec_ref:", bool(a.get("execution_intent_reference")))
        )

print(f"decisions={len(rows)} llm_invoked={llm_called} with_memory_refs={mem_refs}")
print("classes:", classes)
print("actions:", actions)
print("reasons:", reasons)
for note in risk_notes:
    print("entry proposal:", note)

# Orders / fills / ledger since smoke start (SQLite stores 'YYYY-MM-DD HH:MM:SS')
SMOKE_START = "2026-08-28 08:46"
orders = c.execute(
    "SELECT COUNT(*) FROM orders WHERE created_at > ?",
    (SMOKE_START,),
).fetchone()[0]
fills = c.execute(
    "SELECT COUNT(*) FROM fills WHERE timestamp > ?",
    (SMOKE_START,),
).fetchone()[0]
ledger = c.execute(
    "SELECT COUNT(*) FROM ledger_entries WHERE created_at > ?",
    (SMOKE_START,),
).fetchone()[0]
print(f"orders={orders} fills={fills} ledger_entries={ledger}")

# Open position (projection table; side derived from quantity sign)
try:
    pos = c.execute(
        "SELECT symbol, quantity, avg_entry_price, realized_pnl "
        "FROM positions_projection WHERE quantity != 0"
    ).fetchall()
    print("open_positions:", pos if pos else "none")
except Exception as exc:
    print("positions_projection:", type(exc).__name__)
