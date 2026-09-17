"""Engineering regressions for the read-only final acceptance harness."""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "final_acceptance", ROOT / "scripts" / "acceptance" / "final_acceptance.py"
)
assert SPEC is not None and SPEC.loader is not None
harness = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(harness)


def _ready(*, mode: str = "PAPER", live: bool = False, held: bool = True, single: bool = True):
    return {
        "mode": mode,
        "live_trading_enabled": live,
        "runtime": {
            "execution_lease": {"held": held, "single_writer": single},
            "llm_router": {"pause": {"provider_calls_paused": True}},
        },
    }


def test_evaluate_p0_flags_live_lease_sha_duplicate_and_paused_new_risk():
    events = harness.evaluate_p0(
        _ready(live=True, held=False, single=False),
        {
            "provider_call_pause": {"provider_calls_paused": True},
            "configured_provider": "deepseek-chat",
            "configured_model": "deepseek-chat",
        },
        {
            "duplicate_client_order_ids": 1,
            "new_risk_decisions": 1,
            "plans_over_25pct_allocation": 1,
            "plans_over_20x_leverage": 1,
            "plans_missing_base_exit": 1,
        },
        expected_sha="expected",
        running_sha="actual",
    )
    codes = {event["code"] for event in events}
    assert {
        "LIVE_TRADING_ENABLED",
        "LEASE_NOT_HELD",
        "MULTIPLE_WRITERS",
        "RUNTIME_SHA_DRIFT",
        "DUPLICATE_ORDER_ID",
        "PAUSED_LLM_NEW_RISK",
        "CHILD_ALLOCATION_OVER_25",
        "LEVERAGE_OVER_20",
        "MISSING_BASE_EXIT",
        "PROVIDER_MODEL_DRIFT",
    } <= codes


def test_collect_db_metrics_detects_duplicate_client_order_ids(tmp_path):
    db_path = tmp_path / "paper.db"
    connection = sqlite3.connect(db_path)
    connection.execute("CREATE TABLE orders (client_order_id TEXT, internal_order_id TEXT)")
    connection.execute("INSERT INTO orders VALUES ('c1', 'o1')")
    connection.execute("INSERT INTO orders VALUES ('c1', 'o2')")
    connection.execute(
        "CREATE TABLE trade_plans (capital_allocation_pct REAL, leverage_request REAL, base_exit_json TEXT)"
    )
    connection.execute("INSERT INTO trade_plans VALUES (30, 25, '')")
    connection.commit()
    connection.close()

    metrics = harness.collect_db_metrics(str(db_path))
    assert metrics["available"] is True
    assert metrics["orders_count"] == 2
    assert metrics["duplicate_client_order_ids"] == 1
    assert metrics["plans_over_25pct_allocation"] == 1
    assert metrics["plans_over_20x_leverage"] == 1
    assert metrics["plans_missing_base_exit"] == 1
