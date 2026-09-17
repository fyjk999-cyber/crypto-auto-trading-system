"""P1-1 regressions: bounded tool-selection repair, fail-closed and audit trace."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from crypto_trader.llm.tools.registry import LLMToolRegistry, ToolEvidence
from crypto_trader.llm_chief.context import ChiefTraderContext
from crypto_trader.llm_chief.engine import ChiefTraderEngine
from crypto_trader.llm_chief.provider import LLMResponse
from crypto_trader.llm_chief.tool_orchestrator import ToolDrivenChiefTrader


def _ctx() -> ChiefTraderContext:
    return ChiefTraderContext(
        symbol="BTCUSDT",
        market_snapshot={"source": "OKX_PUBLIC"},
        regime="UNKNOWN",
        quant_evidence=[],
        portfolio_state={},
        risk_summary={},
    )


def _response(
    payload: dict | None = None, *, ok: bool = True, error: str | None = None
) -> LLMResponse:
    text = json.dumps(payload, sort_keys=True) if payload is not None else ""
    return LLMResponse(
        text=text,
        provider="deepseek",
        model="deepseek-flash",
        latency_ms=1,
        parsed_json=payload if ok else None,
        ok=ok,
        error=error,
    )


class QueueProvider:
    name = "deepseek"
    model = "deepseek-flash"

    def __init__(self, responses: list[LLMResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    async def complete_json(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def log(self, action: str, **kwargs):
        self.events.append((action, kwargs))
        return "audit_test"


def _registry() -> LLMToolRegistry:
    registry = LLMToolRegistry()

    async def trend(symbol: str, _context: dict) -> ToolEvidence:
        return ToolEvidence(
            tool_name="trend",
            symbol=symbol,
            timestamp=datetime.now(UTC),
            features={"slope": "up"},
            supporting_evidence=["trend up"],
            contrary_evidence=[],
            confidence_of_measurement=0.8,
            data_quality="HEALTHY",
            source_refs=[f"okx:{symbol}:trend"],
        )

    registry.register("trend", trend)
    return registry


def _final_payload() -> dict:
    return {"action": "NO_TRADE", "market_regime": "RANGE", "reason_codes": ["INSUFFICIENT_EDGE"]}


async def _decide(provider: QueueProvider, audit: FakeAudit | None = None):
    orchestrator = ToolDrivenChiefTrader(
        ChiefTraderEngine(provider=provider), _registry(), audit=audit
    )
    return await orchestrator.decide(_ctx(), tool_context={}, now=datetime.now(UTC))


async def test_valid_selection_is_normal_and_not_audited_as_repair():
    provider = QueueProvider([_response({"tools": ["trend"]}), _response(_final_payload())])
    audit = FakeAudit()
    decision, package = await _decide(provider, audit)
    assert decision.action == "NO_TRADE"
    assert package is not None and package.selected_tools == ["trend"]
    assert len(provider.calls) == 2
    assert audit.events == []


async def test_invalid_selection_repair_succeeds_and_is_audited():
    provider = QueueProvider(
        [
            _response({"tools": "trend"}),
            _response({"tools": ["trend"]}),
            _response(_final_payload()),
        ]
    )
    audit = FakeAudit()
    decision, package = await _decide(provider, audit)
    assert decision.action == "NO_TRADE"
    assert package is not None and package.selected_tools == ["trend"]
    assert len(provider.calls) == 3
    assert provider.calls[1]["operation"] == "tool_selection_repair"
    assert len(audit.events) == 1
    action, kwargs = audit.events[0]
    assert action == "LLM_TOOL_SELECTION_TRACE"
    trace = kwargs["after"]
    assert trace["repair_attempted"] is True
    assert trace["final_status"] == "REPAIRED_VALID"
    assert trace["original_response_fingerprint"]
    assert trace["repair_response_fingerprint"]
    assert trace["provider"] == "deepseek"
    assert trace["model"] == "deepseek-flash"
    assert trace["request_id"]


async def test_invalid_repair_still_invalid_fails_closed():
    provider = QueueProvider([_response({"tools": "trend"}), _response({"tools": "still-bad"})])
    audit = FakeAudit()
    decision, package = await _decide(provider, audit)
    assert package is None
    assert decision.action == "FAIL_CLOSED"
    assert decision.reason_codes == ["INVALID_TOOL_SELECTION"]
    assert len(provider.calls) == 2
    trace = audit.events[0][1]["after"]
    assert trace["repair_attempted"] is True
    assert trace["final_status"] == "FAIL_CLOSED"
    assert trace["validation_error"]
    assert trace["repair_response_fingerprint"]


async def test_unknown_tool_fails_closed_without_repair():
    provider = QueueProvider([_response({"tools": ["place_order"]})])
    audit = FakeAudit()
    decision, package = await _decide(provider, audit)
    assert package is None
    assert decision.action == "FAIL_CLOSED"
    assert decision.reason_codes == ["UNKNOWN_TOOL_SELECTED"]
    assert len(provider.calls) == 1
    trace = audit.events[0][1]["after"]
    assert trace["repair_attempted"] is False
    assert trace["final_status"] == "FAIL_CLOSED_NO_REPAIR"


async def test_malformed_json_gets_one_bounded_repair():
    provider = QueueProvider(
        [
            _response(None, ok=False, error="MALFORMED_PROVIDER_RESPONSE"),
            _response({"tools": ["trend"]}),
            _response(_final_payload()),
        ]
    )
    audit = FakeAudit()
    decision, package = await _decide(provider, audit)
    assert decision.action == "NO_TRADE"
    assert package is not None
    assert len(provider.calls) == 3
    trace = audit.events[0][1]["after"]
    assert trace["repair_attempted"] is True
    assert trace["final_status"] == "REPAIRED_VALID"


async def test_provider_timeout_never_fakes_a_repair():
    provider = QueueProvider([_response(None, ok=False, error="LLM_TIMEOUT")])
    audit = FakeAudit()
    decision, package = await _decide(provider, audit)
    assert package is None
    assert decision.action == "FAIL_CLOSED"
    assert decision.reason_codes == ["LLM_TIMEOUT"]
    assert len(provider.calls) == 1
    trace = audit.events[0][1]["after"]
    assert trace["repair_attempted"] is False
    assert trace["final_status"] == "FAIL_CLOSED_NO_REPAIR"


async def test_repair_cannot_add_tools_or_reach_an_order_path():
    provider = QueueProvider(
        [
            _response({"tools": "trend"}),
            _response({"tools": ["trend", "place_order"]}),
        ]
    )
    audit = FakeAudit()
    decision, package = await _decide(provider, audit)
    assert package is None
    assert decision.action == "FAIL_CLOSED"
    assert decision.reason_codes == ["UNKNOWN_TOOL_SELECTED"]
    first_prompt = provider.calls[0]["prompt"]
    repair_prompt = provider.calls[1]["prompt"]
    assert "AvailableTools: ['trend']" in first_prompt
    assert "AvailableTools: ['trend']" in repair_prompt
    assert provider.calls[1]["operation"] == "tool_selection_repair"
    # No order authority exists on either decision path.
    assert not hasattr(provider, "submit_order")
    trace = audit.events[0][1]["after"]
    assert trace["repair_attempted"] is True
    assert trace["final_status"] == "FAIL_CLOSED"


async def test_repair_trace_contains_all_required_fields():
    provider = QueueProvider(
        [
            _response({"tools": "trend"}),
            _response({"tools": ["trend"]}),
            _response(_final_payload()),
        ]
    )
    audit = FakeAudit()
    await _decide(provider, audit)
    trace = audit.events[0][1]["after"]
    for field in (
        "original_response_fingerprint",
        "validation_error",
        "repair_attempted",
        "repair_response_fingerprint",
        "final_status",
        "provider",
        "model",
        "request_id",
    ):
        assert field in trace, field
