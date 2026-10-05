"""Offline synthetic metadata fixtures; never historical incident proof."""

import json

import httpx
import pytest

from crypto_trader.llm_chief.provider import DeepSeekProvider


async def test_malformed_reply_records_only_safe_metadata(caplog):
    body = '{"private":"fixture-body-secret",'

    async def handler(request):
        return httpx.Response(
            200,
            headers={"x-request-id": "request_fixture_1"},
            json={
                "id": "response_fixture_1",
                "choices": [{"finish_reason": "length", "message": {"content": body}}],
                "usage": {
                    "prompt_tokens": 12,
                    "completion_tokens": 24,
                    "completion_tokens_details": {"reasoning_tokens": 9},
                },
            },
        )

    p = DeepSeekProvider(api_key="fixture-key-secret", transport=httpx.MockTransport(handler))
    result = await p.complete_json(prompt="fixture-prompt-secret", retries=0, max_tokens=24)
    assert not result.ok and result.error == "INVALID_JSON"
    metadata = p.diagnostics()["operations"]["completion"]["failure_metadata"][0]
    assert metadata["finish_reason"] == "length"
    assert metadata["classification"] == "PROVIDER_REPORTED_TRUNCATION"
    assert metadata["json_error_pos"] == len(body)
    assert metadata["configured_max_output_tokens"] == 24
    assert metadata["response_character_length"] == len(body)
    assert metadata["completion_tokens"] == 24
    assert metadata["reasoning_tokens"] == 9
    assert metadata["provider_request_id"] == "request_fixture_1"
    assert metadata["response_id"] == "response_fixture_1"
    assert len(metadata["response_sha256"]) == 64
    persisted = json.dumps(metadata) + caplog.text
    assert body not in persisted
    for secret in ("fixture-body-secret", "fixture-prompt-secret", "fixture-key-secret"):
        assert secret not in persisted


@pytest.mark.parametrize(
    "body,reason,classification,error",
    [
        ("", "stop", "EMPTY_RESPONSE", "EMPTY_CONTENT"),
        ('{"x":', "stop", "JSON_DECODE_ERROR", "INVALID_JSON"),
        ("```json\n{}\n```", "stop", "MARKDOWN_WRAPPED", "PROSE_CONTAMINATION"),
        ('prose {"x":1}', "stop", "JSON_DECODE_ERROR", "INVALID_JSON"),
        ("{} {}", "stop", "JSON_DECODE_ERROR", "INVALID_JSON"),
        ('{"x":"\\q"}', "stop", "JSON_DECODE_ERROR", "INVALID_JSON"),
        ('{"x":', "length", "PROVIDER_REPORTED_TRUNCATION", "INVALID_JSON"),
        ("[]", "stop", "SCHEMA_VALIDATION_ERROR", "INVALID_JSON_OBJECT"),
    ],
)
async def test_failure_taxonomy_does_not_change_acceptance(body, reason, classification, error):
    calls = []

    async def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": reason, "message": {"content": body}}],
                "usage": {"completion_tokens": 2400},
            },
        )

    p = DeepSeekProvider(api_key="fixture-key", transport=httpx.MockTransport(handler))
    result = await p.complete_json(prompt="fixture", retries=1, max_tokens=2400)
    assert not result.ok and result.error == error
    assert len(calls) == (1 if error == "INVALID_JSON_OBJECT" else 2)
    if len(calls) == 2:
        assert calls[0]["thinking"] == {"type": "enabled"}
        assert calls[1]["thinking"] == {"type": "disabled"}
    meta = p.diagnostics()["operations"]["completion"]["failure_metadata"]
    assert len(meta) == len(calls)
    assert meta[-1]["classification"] == classification
    if reason != "length":
        assert all(m["classification"] != "PROVIDER_REPORTED_TRUNCATION" for m in meta)


async def test_valid_reply_has_no_failure_log_and_same_acceptance(caplog):
    async def handler(request):
        return httpx.Response(
            200, json={"choices": [{"finish_reason": "stop", "message": {"content": '{"x":1}'}}]}
        )

    p = DeepSeekProvider(api_key="fixture-key", transport=httpx.MockTransport(handler))
    result = await p.complete_json(prompt="fixture", retries=0)
    assert result.ok and result.parsed_json == {"x": 1}
    assert result.failure_metadata == []
    assert "LLM_FAILURE_METADATA" not in caplog.text


async def test_schema_failure_logs_codes_not_payload(caplog):
    from crypto_trader.llm_chief.context import ChiefTraderContext
    from crypto_trader.llm_chief.engine import ChiefTraderEngine

    async def handler(request):
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": '{"market_regime":"fixture-secret"}'},
                    }
                ]
            },
        )

    p = DeepSeekProvider(api_key="fixture-key", transport=httpx.MockTransport(handler))
    ctx = ChiefTraderContext(
        symbol="BTCUSDT",
        market_snapshot={},
        regime="RANGE",
        quant_evidence=[],
        portfolio_state={},
        risk_summary={},
    )
    decision = await ChiefTraderEngine(p).decide(ctx)
    assert decision.action == "FAIL_CLOSED"
    lines = [r.message for r in caplog.records if r.message.startswith("LLM_FAILURE_METADATA ")]
    assert len(lines) == 1
    meta = json.loads(lines[0].split(" ", 1)[1])
    assert meta["classification"] == "SCHEMA_VALIDATION_ERROR"
    assert meta["json_parse_ok"] and meta["schema_validation_ok"] is False
    assert meta["decision_id"] == decision.decision_id
    assert meta["validation_errors"]
    assert "fixture-secret" not in lines[0]


@pytest.mark.parametrize(
    "reason,usage,body",
    [
        ([], "malformed-unused-usage", '{"x":1}'),
        (None, {"completion_tokens_details": []}, '{"x":1}'),
        ("stop", None, '{"x":"\\ud800"}'),
    ],
)
async def test_unexpected_unused_wire_metadata_never_changes_valid_acceptance(reason, usage, body):
    async def handler(request):
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": reason, "message": {"content": body}}],
                "usage": usage,
            },
        )

    p = DeepSeekProvider(api_key="fixture-key", transport=httpx.MockTransport(handler))
    result = await p.complete_json(prompt="fixture", retries=0)
    assert result.ok and result.parsed_json == json.loads(body)


async def test_telemetry_handler_failure_does_not_change_retry_or_offline(monkeypatch):
    from crypto_trader.llm_chief import failure_telemetry
    from crypto_trader.llm_chief.failover import CoreLLMRouter

    calls = []

    def broken_handler(*args, **kwargs):
        raise RuntimeError("diagnostic sink unavailable")

    monkeypatch.setattr(failure_telemetry._LOGGER, "warning", broken_handler)

    async def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"x":'}}]})

    p = DeepSeekProvider(api_key="fixture-key", transport=httpx.MockTransport(handler))
    router = CoreLLMRouter(primary=p)
    response = await router.complete_json(prompt="fixture", retries=1)
    assert not response.ok and response.error == "INVALID_JSON"
    assert len(calls) == 2
    assert router.offline
    assert router.diagnostics()["offline"]["reason"] == "INVALID_JSON"


def test_schema_metadata_does_not_keep_untrusted_error_path():
    from pydantic import ValidationError

    from crypto_trader.llm_chief.decision import ChiefTraderDecision
    from crypto_trader.llm_chief.failure_telemetry import validation_failure

    try:
        ChiefTraderDecision.model_validate({"fixture-secret-key": "fixture-secret-value"})
    except ValidationError as error:
        metadata = validation_failure({}, error, set(ChiefTraderDecision.model_fields))
    assert "fixture-secret" not in json.dumps(metadata)
    assert any("<unknown-field>" in e["validation_path"] for e in metadata["validation_errors"])
