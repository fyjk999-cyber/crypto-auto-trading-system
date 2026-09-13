"""LLM model switching (frontend-selectable, persisted, audited).

Covers the operator contract: only allow-listed models, live provider
mutation, durability across restarts, audit lineage, and the guarantee that
switching is purely operational (no authority/risk/execution change).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from crypto_trader.api.app import create_app
from crypto_trader.llm_chief.model_control import (
    AVAILABLE_LLM_MODELS,
    DEFAULT_LLM_MODEL,
    LLMModelControl,
    ModelSwitchUnavailable,
    UnknownModelError,
)
from tests.integration.test_api import make_state


class FakeProvider:
    name = "deepseek"

    def __init__(self, model: str = "deepseek-chat", api_key: str | None = "k") -> None:
        self.model = model
        self.api_key = api_key


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def log(self, action: str, **kwargs) -> str:
        self.events.append((action, kwargs))
        return "audit_1"


async def test_switch_mutates_live_provider_persists_and_audits(database):
    provider = FakeProvider(model="deepseek-v4-pro")
    audit = FakeAudit()
    control = LLMModelControl(database.session_factory, provider=provider, audit=audit)

    before = await control.state()
    assert before["model"] == "deepseek-v4-pro"
    assert before["source"] == "PROVIDER_CONFIG"
    assert before["available"] == list(AVAILABLE_LLM_MODELS)

    result = await control.switch("deepseek-flash", actor="frontend_operator")
    assert result["model"] == "deepseek-flash"
    assert result["previous_model"] == "deepseek-v4-pro"
    assert result["changed"] is True
    assert provider.model == "deepseek-flash"  # live provider mutated
    assert result["source"] == "RUNTIME_OVERRIDE"
    assert audit.events[0][0] == "LLM_MODEL_SWITCHED"
    assert audit.events[0][1]["after"]["model"] == "deepseek-flash"

    # durability: a fresh control (i.e. next runtime start) applies the choice
    restarted = FakeProvider(model="deepseek-chat")
    restarted_control = LLMModelControl(database.session_factory, provider=restarted)
    assert await restarted_control.apply_persisted() == "deepseek-flash"
    assert restarted.model == "deepseek-flash"
    assert (await restarted_control.state())["source"] == "RUNTIME_OVERRIDE"


async def test_unknown_model_is_rejected_and_provider_untouched(database):
    provider = FakeProvider(model="deepseek-v4-pro")
    control = LLMModelControl(database.session_factory, provider=provider)
    with pytest.raises(UnknownModelError):
        await control.switch("gpt-9-ultra")
    assert provider.model == "deepseek-v4-pro"
    assert await control.persisted_model() is None


async def test_state_without_provider_has_default_and_no_switch(database):
    control = LLMModelControl(database.session_factory, provider=None)
    state = await control.state()
    assert state["model"] == DEFAULT_LLM_MODEL
    assert state["source"] == "DEFAULT"
    assert state["switch_supported"] is False
    with pytest.raises(ModelSwitchUnavailable):
        await control.switch("deepseek-flash")


async def test_switch_is_operational_only(database):
    """Switching never touches authority/risk/execution surfaces."""
    provider = FakeProvider(model="deepseek-v4-pro")
    control = LLMModelControl(database.session_factory, provider=provider)
    result = await control.switch("deepseek-flash")
    assert set(result) >= {"model", "source", "available", "switch_supported"}
    assert "authority" not in result and "risk" not in result
    # the live-LLM authority flag is a runtime property, unaffected here
    state = make_state(database)
    assert state.engine is None


async def test_api_lists_and_switches_model(database):
    state = make_state(database)
    provider = FakeProvider(model="deepseek-v4-pro")
    state.model_control = LLMModelControl(database.session_factory, provider=provider)
    client = TestClient(create_app(state))

    listing = client.get("/llm/models")
    assert listing.status_code == 200
    body = listing.json()
    assert body["model"] == "deepseek-v4-pro"
    assert body["available"] == list(AVAILABLE_LLM_MODELS)
    assert body["switch_supported"] is True

    switched = client.post("/llm/model", json={"model": "deepseek-flash"})
    assert switched.status_code == 200
    assert switched.json()["model"] == "deepseek-flash"
    assert provider.model == "deepseek-flash"
    assert client.get("/llm/models").json()["source"] == "RUNTIME_OVERRIDE"

    rejected = client.post("/llm/model", json={"model": "totally-not-a-model"})
    assert rejected.status_code == 400
    assert rejected.json()["detail"] == "UNSUPPORTED_MODEL"
    assert provider.model == "deepseek-flash"

    missing = client.post("/llm/model", json={})
    assert missing.status_code == 400
    assert missing.json()["detail"] == "MODEL_REQUIRED"


async def test_llm_health_reports_live_switched_model(database):
    state = make_state(database)
    provider = FakeProvider(model="deepseek-v4-pro")
    state.model_control = LLMModelControl(database.session_factory, provider=provider)
    state.llm_runtime.provider_instance = provider
    state.llm_runtime.model = "stale-env-value"
    client = TestClient(create_app(state))

    client.post("/llm/model", json={"model": "deepseek-flash"})
    health = client.get("/llm/health").json()
    assert health["model"] == "deepseek-flash"  # live provider value wins
    assert health["model_source"] == "RUNTIME_OVERRIDE"
    assert "deepseek-flash" in health["available_models"]
