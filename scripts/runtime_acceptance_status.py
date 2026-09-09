#!/usr/bin/env python3
"""Print current fullmarket PAPER runtime acceptance status (read-only)."""
from __future__ import annotations

import json
import sqlite3
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "crypto_trader.db"
PORT = sys.argv[1] if len(sys.argv) > 1 else "8001"
BASE = f"http://127.0.0.1:{PORT}"


def get(path: str) -> dict:
    with urllib.request.urlopen(BASE + path, timeout=5) as resp:
        return json.load(resp)


def main() -> None:
    version = get("/version")
    runtime = get("/runtime")
    health = get("/health")
    llm = get("/llm/health")
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    cur = conn.cursor()
    counts = {}
    for table in ("llm_decisions", "trade_plans", "orders", "fills", "trade_episodes"):
        try:
            counts[table] = cur.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        except Exception:
            counts[table] = -1
    conn.close()
    print(json.dumps({
        "running_sha": version.get("git_sha"),
        "state": runtime.get("state"),
        "lease_held": runtime.get("lease_held"),
        "single_writer": (runtime.get("execution_lease") or {}).get("single_writer"),
        "kill_switch_enabled": bool((runtime.get("kill_switch") or {}).get("enabled")),
        "health": health.get("overall"),
        "llm_health": llm.get("health") or llm.get("configured"),
        "lifecycle_counts": counts,
    }, indent=2))


if __name__ == "__main__":
    main()
