#!/usr/bin/env python3
"""Read-only final Low-Risk V2 acceptance/soak harness.

It may read health endpoints, SQLite data, process metadata and launchd state.
It never places/cancels orders, forces signals, changes parameters, promotes
models or fabricates evidence.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

NEW_RISK_ACTIONS = ("LONG", "SHORT", "REVERSE", "HEDGE", "ADD")


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def http_json(url: str, timeout: float = 5.0) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload if isinstance(payload, dict) else {"data": payload}


def try_http_json(url: str, timeout: float = 5.0) -> dict[str, Any]:
    try:
        return http_json(url, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 - harness must survive service absence
        return {"_unavailable": True, "error": type(exc).__name__}


def db_connect_readonly(path: str) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def scalar(conn: sqlite3.Connection, sql: str, default: int = 0, params=()) -> int:
    try:
        row = conn.execute(sql, params).fetchone()
        return int(row[0]) if row and row[0] is not None else default
    except sqlite3.Error:
        return default


def columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    except sqlite3.Error:
        return set()


def collect_db_metrics(db_path: str, *, since: str | None = None) -> dict[str, Any]:
    metrics: dict[str, Any] = {"db_path": db_path, "available": False}
    try:
        conn = db_connect_readonly(db_path)
    except sqlite3.Error as exc:
        metrics["error"] = type(exc).__name__
        return metrics
    try:
        for table in (
            "orders",
            "fills",
            "trade_plans",
            "llm_decisions",
            "trade_episodes",
            "position_legs",
            "news_events",
            "ml_forward_predictions",
        ):
            if table_exists(conn, table):
                metrics[table + "_count"] = scalar(conn, "SELECT COUNT(*) FROM " + table)
        order_cols = columns(conn, "orders")
        duplicate_ids = 0
        if "client_order_id" in order_cols:
            duplicate_ids = scalar(
                conn,
                "SELECT COUNT(*) FROM (SELECT client_order_id FROM orders "
                "WHERE client_order_id IS NOT NULL AND client_order_id <> '' "
                "GROUP BY client_order_id HAVING COUNT(*) > 1)",
            )
        metrics["duplicate_client_order_ids"] = duplicate_ids
        decision_cols = columns(conn, "llm_decisions")
        if {"action", "created_at"} <= decision_cols:
            placeholders = ",".join("?" for _ in NEW_RISK_ACTIONS)
            metrics["new_risk_decisions"] = scalar(
                conn,
                "SELECT COUNT(*) FROM llm_decisions WHERE UPPER(action) IN ("
                + placeholders
                + ")",
                params=NEW_RISK_ACTIONS,
            )
            if since:
                metrics["new_risk_decisions_since_pause"] = scalar(
                    conn,
                    "SELECT COUNT(*) FROM llm_decisions "
                    "WHERE UPPER(action) IN ("
                    + placeholders
                    + ") AND created_at >= ?",
                    params=(*NEW_RISK_ACTIONS, since),
                )
        plan_cols = columns(conn, "trade_plans")
        if "capital_allocation_pct" in plan_cols:
            metrics["plans_over_25pct_allocation"] = scalar(
                conn,
                "SELECT COUNT(*) FROM trade_plans WHERE capital_allocation_pct > 25",
            )
        if "leverage_request" in plan_cols:
            metrics["plans_over_20x_leverage"] = scalar(
                conn,
                "SELECT COUNT(*) FROM trade_plans WHERE leverage_request > 20",
            )
        if "base_exit_json" in plan_cols:
            metrics["plans_missing_base_exit"] = scalar(
                conn,
                "SELECT COUNT(*) FROM trade_plans "
                "WHERE base_exit_json IS NULL OR base_exit_json = '' "
                "OR base_exit_json = '{}'",
            )
        metrics["available"] = True
        return metrics
    finally:
        conn.close()


def evaluate_p0(
    ready: dict[str, Any],
    llm_health: dict[str, Any],
    db_metrics: dict[str, Any],
    *,
    expected_sha: str | None = None,
    running_sha: str | None = None,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []

    def add(code: str, detail: str) -> None:
        events.append({"code": code, "detail": detail, "at": utc_now()})

    if not isinstance(ready, dict) or not ready:
        add("RUNTIME_UNAVAILABLE", "runtime readiness endpoint unavailable")
        return events

    live = ready.get("live_trading_enabled")
    if live is None:
        add("READINESS_UNKNOWN", "live_trading_enabled is absent from readiness")
    elif live is not False:
        add("LIVE_TRADING_ENABLED", "live_trading_enabled is not false")

    mode = ready.get("mode")
    if mode is None:
        add("READINESS_UNKNOWN", "runtime mode is absent from readiness")
    elif str(mode).upper() != "PAPER":
        add("NON_PAPER_MODE", "runtime mode is not PAPER")

    if expected_sha and running_sha and running_sha != expected_sha:
        add("RUNTIME_SHA_DRIFT", "running SHA " + running_sha + " != expected " + expected_sha)

    runtime = ready.get("runtime") or {}
    lease = runtime.get("execution_lease")
    if not isinstance(lease, dict):
        add("LEASE_UNAVAILABLE", "execution lease state unavailable")
        add("WRITER_STATE_UNKNOWN", "single_writer state unavailable")
    else:
        held = lease.get("held")
        if held is None:
            add("LEASE_UNAVAILABLE", "execution lease held state unavailable")
        elif held is not True:
            add("LEASE_NOT_HELD", "execution lease is not held")
        single_writer = lease.get("single_writer")
        if single_writer is None:
            add("WRITER_STATE_UNKNOWN", "single_writer state unavailable")
        elif single_writer is not True:
            add("MULTIPLE_WRITERS", "single_writer is not true")
    if int(db_metrics.get("duplicate_client_order_ids", 0) or 0) > 0:
        add("DUPLICATE_ORDER_ID", "duplicate client_order_id detected")
    if int(db_metrics.get("plans_over_25pct_allocation", 0) or 0) > 0:
        add("CHILD_ALLOCATION_OVER_25", "trade plan allocation exceeds 25 percent")
    if int(db_metrics.get("plans_over_20x_leverage", 0) or 0) > 0:
        add("LEVERAGE_OVER_20", "trade plan leverage exceeds 20x")
    if int(db_metrics.get("plans_missing_base_exit", 0) or 0) > 0:
        add("MISSING_BASE_EXIT", "trade plan is missing a Base Exit contract")
    configured_provider = str(llm_health.get("configured_provider") or "").lower()
    configured_model = str(llm_health.get("configured_model") or "").lower()
    if configured_provider and configured_provider != "deepseek":
        add("PROVIDER_MODEL_DRIFT", "configured provider is not deepseek")
    if configured_model and configured_model != "deepseek-flash":
        add("PROVIDER_MODEL_DRIFT", "configured model is not deepseek-flash")
    pause = (runtime.get("llm_router") or {}).get("pause") or {}
    paused = bool(pause.get("provider_calls_paused")) or bool(
        (llm_health.get("provider_call_pause") or {}).get("provider_calls_paused")
    )
    paused_new_risk = db_metrics.get("new_risk_decisions_since_pause", 0)
    if paused and int(paused_new_risk or 0) > 0:
        add(
            "PAUSED_LLM_NEW_RISK",
            "new-risk decisions present while provider calls are paused",
        )
    return events


def read_json_file(path: str) -> dict[str, Any]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - evidence files may be absent
        return {"_unavailable": True, "error": type(exc).__name__}


def git_sha(path: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", path, "rev-parse", "HEAD"],
            capture_output=True,
            check=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return None


def process_info(pid: int) -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "pid=,etime=,command="],
            capture_output=True,
            check=True,
            text=True,
            timeout=5,
        )
        return {"pid": pid, "ps": result.stdout.strip()}
    except (subprocess.SubprocessError, OSError):
        return {"pid": pid, "_unavailable": True}


def gather_services(root: str) -> dict[str, Any]:
    root_path = Path(root)
    candidates = {
        "growth": root_path / "data" / "growth" / "growth_heartbeat.json",
        "news": root_path / "data" / "news" / "news_heartbeat.json",
        "ml_collector": root_path / "data" / "ml" / "collector_heartbeat.json",
        "ml_trainer": root_path / "data" / "ml" / "trainer_heartbeat.json",
    }
    external = {
        "growth": Path("/Users/huhongjie/lowrisk-growth/data/growth/growth_heartbeat.json"),
        "news": Path("/Users/huhongjie/lowrisk-news/data/news/news_heartbeat.json"),
        "ml_collector": Path("/Users/huhongjie/lowrisk-ml/data/ml/collector_heartbeat.json"),
        "ml_trainer": Path("/Users/huhongjie/lowrisk-ml/data/ml/trainer_heartbeat.json"),
    }
    services: dict[str, Any] = {}
    for name, path in candidates.items():
        resolved = path if path.exists() else external.get(name, path)
        services[name] = read_json_file(str(resolved))
        services[name]["path"] = str(resolved)
    return services


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Read-only final acceptance sampler")
    parser.add_argument("--runtime-url", default="http://127.0.0.1:8010")
    parser.add_argument("--db", default="/private/tmp/lr2-soak2/data/crypto_trader.db")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--expected-sha", default=None)
    parser.add_argument("--out-dir", default="data/acceptance")
    parser.add_argument("--samples", type=int, default=1)
    parser.add_argument("--interval-seconds", type=float, default=0.0)
    return parser.parse_args(argv)


def collect_sample(args) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    ready = try_http_json(args.runtime_url + "/ready")
    health = try_http_json(args.runtime_url + "/health")
    llm_health = try_http_json(args.runtime_url + "/llm/health")
    leg_summary = try_http_json(args.runtime_url + "/position-legs/summary")
    pause_status = (llm_health.get("provider_call_pause") or {})
    if not pause_status:
        pause_status = ((ready.get("runtime") or {}).get("llm_router") or {}).get("pause") or {}
    db_metrics = collect_db_metrics(args.db, since=pause_status.get("paused_since"))
    services = gather_services(args.root)
    running_sha = git_sha(args.root)
    runtime = ready.get("runtime") or {}
    pid = runtime.get("pid")
    baseline = {
        "at": utc_now(),
        "running_sha": running_sha,
        "expected_sha": args.expected_sha,
        "ready": ready,
        "health": health,
        "llm_health": llm_health,
        "leg_summary": leg_summary,
        "services": services,
    }
    topology = {
        "at": utc_now(),
        "root": args.root,
        "running_sha": running_sha,
        "pid": pid,
        "process": process_info(int(pid)) if isinstance(pid, int) else {},
        "services": services,
    }
    p0_events = evaluate_p0(
        ready,
        llm_health,
        db_metrics,
        expected_sha=args.expected_sha,
        running_sha=running_sha,
    )
    return baseline, topology, p0_events


def main(argv=None) -> int:
    args = parse_args(argv)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    all_p0: list[dict[str, Any]] = []
    samples = max(1, int(args.samples))
    for index in range(samples):
        baseline, topology, p0_events = collect_sample(args)
        all_p0.extend(p0_events)
        if index == 0:
            (out_dir / "baseline.json").write_text(
                json.dumps(baseline, indent=2, default=str), encoding="utf-8"
            )
            (out_dir / "service_topology.json").write_text(
                json.dumps(topology, indent=2, default=str), encoding="utf-8"
            )
            (out_dir / "provider_diagnostics.json").write_text(
                json.dumps(
                    {
                        "at": utc_now(),
                        "llm_health": baseline["llm_health"],
                        "pause": (baseline["llm_health"].get("provider_call_pause") or {}),
                    },
                    indent=2,
                    default=str,
                ),
                encoding="utf-8",
            )
        with (out_dir / "soak_samples.ndjson").open("a", encoding="utf-8") as handle:
            payload = {"at": utc_now(), "ready": baseline["ready"]}
            handle.write(json.dumps(payload, default=str) + "\n")
        if samples > 1 and index + 1 < samples:
            time.sleep(max(0.0, float(args.interval_seconds)))
    if all_p0:
        with (out_dir / "p0_events.ndjson").open("a", encoding="utf-8") as handle:
            for event in all_p0:
                handle.write(json.dumps(event, default=str) + "\n")
    receipt = {
        "at": utc_now(),
        "expected_sha": args.expected_sha,
        "p0_count": len(all_p0),
        "p0_events": all_p0,
        "status": "PASS" if not all_p0 else "P0_BLOCKED",
    }
    (out_dir / "test_receipt.json").write_text(
        json.dumps(receipt, indent=2, default=str), encoding="utf-8"
    )
    print(json.dumps(receipt, indent=2, default=str))
    return 1 if all_p0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
