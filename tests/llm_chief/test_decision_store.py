from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from crypto_trader.llm_chief.context import ChiefTraderContext
from crypto_trader.llm_chief.decision import ChiefTraderDecision, PositionState
from crypto_trader.llm_chief.decision_store import LLMDecisionStore
from crypto_trader.llm_chief.engine import ChiefTraderEngine
from crypto_trader.llm_chief.provider import LLMResponse


def decision(action: str, *, state: str = "FLAT") -> ChiefTraderDecision:
    directional = action in {"LONG", "SHORT"}
    return ChiefTraderDecision(
        decision_id=f"decision-{state}-{action}",
        symbol="ETHUSDT",
        position_state=state,
        action=action,
        market_regime="RANGE",
        model_provider="deepseek",
        model="deepseek-v4-pro",
        model_version="live-v1",
        thesis="factual directional thesis" if directional else "",
        position_size_request=0.5 if action == "REDUCE" or directional else 0,
        leverage_request=2 if directional else 0,
        stop_loss=90 if directional else None,
        created_at=datetime.now(UTC).isoformat(),
    )


def test_strict_flat_and_open_action_sets_reject_legacy_or_wrong_context():
    for action in ("LONG", "SHORT", "NO_TRADE", "WAIT"):
        assert decision(action).action == action
    for action in ("HOLD", "REDUCE", "EXIT"):
        assert decision(action, state="OPEN").action == action
    for action, state in (("ADD", "OPEN"), ("HEDGE", "OPEN"), ("EXIT", "FLAT"), ("LONG", "OPEN")):
        with pytest.raises(ValidationError):
            decision(action, state=state)


def test_directional_entry_requires_risk_sizing_inputs():
    baseline = decision("LONG").model_dump()
    for missing in ("thesis", "leverage_request", "stop_loss"):
        invalid = dict(baseline)
        invalid[missing] = "" if missing == "thesis" else 0
        with pytest.raises(ValidationError):
            ChiefTraderDecision(**invalid)

    invalid_size = dict(baseline, position_size_request=0, requested_exposure=None)
    with pytest.raises(ValidationError):
        ChiefTraderDecision(**invalid_size)


async def test_store_persists_non_directional_and_open_decisions_idempotently(database):
    store = LLMDecisionStore(database.session_factory)
    for item in (
        decision("NO_TRADE"),
        decision("WAIT"),
        decision("FAIL_CLOSED"),
        decision("HOLD", state="OPEN"),
        decision("REDUCE", state="OPEN"),
        decision("EXIT", state="OPEN"),
    ):
        first = await store.save(item, run_id="run-1", prompt_version="prompt-v1")
        second = await store.save(item, run_id="run-1", prompt_version="prompt-v1")
        assert first == second
        assert first.reason_codes == item.reason_codes
    assert [row.action for row in await store.list_for_symbol("ETHUSDT")] == [
        "NO_TRADE",
        "WAIT",
        "FAIL_CLOSED",
        "HOLD",
        "REDUCE",
        "EXIT",
    ]


async def test_store_rejects_conflicting_reuse_of_application_decision_id(database):
    store = LLMDecisionStore(database.session_factory)
    original = decision("NO_TRADE")
    await store.save(original, run_id="run-1", prompt_version="prompt-v1")
    conflicting = ChiefTraderDecision(
        **{**original.model_dump(), "action": "WAIT", "thesis": "changed"}
    )

    with pytest.raises(ValueError, match="immutable LLM decision conflict"):
        await store.save(conflicting, run_id="run-1", prompt_version="prompt-v1")
    with pytest.raises(ValueError, match="immutable LLM decision conflict"):
        await store.save(original, run_id="run-2", prompt_version="prompt-v1")

    persisted = await store.get(original.decision_id)
    assert persisted is not None
    assert persisted.action == "NO_TRADE"
    assert persisted.run_id == "run-1"


async def test_store_persists_immutable_evidence_package(database):
    store = LLMDecisionStore(database.session_factory)
    item = decision("NO_TRADE")
    package = {
        "symbol": "ETHUSDT",
        "selected_tools": ["trend"],
        "items": [{"tool_name": "trend", "finding": {"return_20": "0.1"}}],
    }
    stored = await store.save(
        item, run_id="run-evidence", prompt_version="prompt-v1",
        evidence_package=package,
    )
    assert stored.evidence_package == package
    with pytest.raises(ValueError, match="evidence_package_json"):
        await store.save(
            item, run_id="run-evidence", prompt_version="prompt-v1",
            evidence_package={**package, "selected_tools": ["momentum"]},
        )


async def test_fail_closed_decision_has_no_fabricated_evidence_package(database):
    store = LLMDecisionStore(database.session_factory)
    stored = await store.save(
        decision("NO_TRADE"),
        run_id="run-fail-closed",
        prompt_version="prompt-v1",
        evidence_package=None,
    )
    assert stored.evidence_package is None


class InvalidProvider:
    name = "deepseek"
    model = "deepseek-v4-pro"

    async def complete_json(self, **_kwargs):
        return LLMResponse(
            text='{"action":"HEDGE"}',
            provider=self.name,
            model=self.model,
            latency_ms=1,
            parsed_json={"action": "HEDGE"},
        )


async def test_malformed_provider_output_becomes_application_owned_fail_closed():
    context = ChiefTraderContext(
        symbol="ETHUSDT",
        market_snapshot={},
        regime="UNKNOWN",
        quant_evidence=[],
        portfolio_state={},
        risk_summary={},
        position_state=PositionState.FLAT,
    )
    result = await ChiefTraderEngine(provider=InvalidProvider()).decide(context)
    assert result.action == "FAIL_CLOSED"
    assert result.decision_id.startswith("llm_")
    assert result.model_provider == "deepseek"
    assert result.model == "deepseek-v4-pro"
