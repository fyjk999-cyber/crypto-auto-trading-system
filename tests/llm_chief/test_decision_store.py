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
    return ChiefTraderDecision(
        decision_id=f"decision-{state}-{action}",
        symbol="ETHUSDT",
        position_state=state,
        action=action,
        market_regime="RANGE",
        model_provider="deepseek",
        model="deepseek-v4-pro",
        model_version="live-v1",
        position_size_request=0.5 if action == "REDUCE" else 0,
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
    assert [row.action for row in await store.list_for_symbol("ETHUSDT")] == [
        "NO_TRADE",
        "WAIT",
        "FAIL_CLOSED",
        "HOLD",
        "REDUCE",
        "EXIT",
    ]


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
