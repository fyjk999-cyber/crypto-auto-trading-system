"""POSITION SIZING V2 observability: the audit trail must explain every entry.

Covers §61-§63: sizing equity, risk %, risk budget, target/final notional,
notional as % of equity, requested/approved leverage, expected stop-loss $, and
the binding cap must be reachable from the API and from the durable audit.
"""

from __future__ import annotations

from decimal import Decimal

from fastapi.testclient import TestClient

from crypto_trader.api.app import create_app
from crypto_trader.observability.audit import AuditService
from tests.integration.test_api import make_state


async def test_sizing_audit_is_exposed_for_each_entry(database):
    state = make_state(database)
    audit = AuditService(database.session_factory)
    await audit.log(
        "LIVE_LLM_SIZING_AUDIT",
        target="llm_sizing_v2_probe",
        actor="live_llm",
        run_id="run_sizing_v2",
        after={
            "equity": "100000",
            "valuation_id": "val-api-probe",
            "effective_risk_fraction": "0.005",
            "risk_budget": "500.00000",
            "entry_price": "100",
            "stop_price": "99",
            "stop_distance": "1",
            "risk_qty": "500.00000",
            "final_qty": "500.000",
            "final_notional": "50000.000",
            "notional_pct_of_equity": "0.5",
            "requested_leverage": "5",
            "approved_leverage": "5",
            "max_loss_estimate": "500.00000",
            "binding_cap": "RISK_BUDGET",
            "binding_caps": ["RISK_BUDGET"],
            "min_effective_notional": "500.00000",
            "sizing_reason_codes": ["RISK_BUDGET", "ECONOMIC_NOTIONAL_PASS"],
        },
    )
    client = TestClient(create_app(state))

    payload = client.get("/sizing/llm_sizing_v2_probe").json()

    assert payload["sizing_equity"] == "100000"
    assert payload["risk_pct"] == "0.005"
    assert payload["risk_budget"] == "500.00000"
    assert payload["target_notional"] == "500.00000"
    assert payload["final_notional"] == "50000.000"
    assert payload["final_qty"] == "500.000"
    assert payload["position_notional_pct"] == "0.5"
    assert payload["requested_leverage"] == "5"
    assert payload["approved_leverage"] == "5"
    assert payload["expected_stop_loss"] == "500.00000"
    assert payload["binding_cap"] == "RISK_BUDGET"
    assert payload["binding_caps"] == ["RISK_BUDGET"]
    assert payload["llm_size_authority"] == "ADVISORY_ONLY"
    assert payload["sizer_final_quantity_authority"] is True
    assert payload["decision"] == "LIVE_LLM_SIZING_AUDIT"


async def test_sizing_audit_exposes_rejections_too(database):
    state = make_state(database)
    await AuditService(database.session_factory).log(
        "LIVE_LLM_SIZING_REJECTED",
        target="llm_sizing_v2_reject",
        actor="live_llm",
        run_id="run_sizing_v2",
        after={
            "reason_codes": ["BELOW_ECONOMIC_NOTIONAL"],
            "binding_cap": "ECONOMIC_MINIMUM",
            "sizing": {
                "equity": "100000",
                "final_notional": "210",
                "min_effective_notional": "500",
                "binding_cap": "ECONOMIC_MINIMUM",
                "sizing_reason_codes": ["BELOW_ECONOMIC_NOTIONAL"],
            },
        },
    )
    client = TestClient(create_app(state))

    payload = client.get("/sizing/llm_sizing_v2_reject").json()

    assert payload["decision"] == "LIVE_LLM_SIZING_REJECTED"
    assert payload["final_notional"] == "210"
    assert payload["min_effective_notional"] == "500"
    assert payload["binding_cap"] == "ECONOMIC_MINIMUM"
    assert payload["sizing_reason_codes"] == ["BELOW_ECONOMIC_NOTIONAL"]


async def test_sizing_audit_is_absent_for_an_unknown_decision(database):
    client = TestClient(create_app(make_state(database)))

    response = client.get("/sizing/does-not-exist")

    assert response.status_code == 404


async def test_sizing_audit_lookup_is_read_only_and_never_mutates(database):
    state = make_state(database)
    audit = AuditService(database.session_factory)
    event_id = await audit.log(
        "LIVE_LLM_SIZING_AUDIT",
        target="llm_sizing_v2_readonly",
        actor="live_llm",
        run_id="run_sizing_v2",
        after={"equity": "100000", "final_notional": "1"},
    )
    client = TestClient(create_app(state))

    before = len(await audit.list_recent(limit=100))
    first = client.get("/sizing/llm_sizing_v2_readonly").json()
    second = client.get("/sizing/llm_sizing_v2_readonly").json()

    assert first == second
    assert len(await audit.list_recent(limit=100)) == before
    assert event_id


async def test_latest_for_target_returns_the_newest_record(database):
    audit = AuditService(database.session_factory)
    await audit.log("LIVE_LLM_SIZING_AUDIT", target="dup", after={"equity": "1"})
    await audit.log("LIVE_LLM_SIZING_AUDIT", target="dup", after={"equity": "2"})

    event = await audit.latest_for_target(
        "dup", actions=("LIVE_LLM_SIZING_AUDIT",)
    )

    assert event is not None
    assert event.after_json["equity"] == "2"
    assert await audit.latest_for_target("dup", actions=("NEVER_LOGGED",)) is None
    assert Decimal("2") == Decimal(event.after_json["equity"])
