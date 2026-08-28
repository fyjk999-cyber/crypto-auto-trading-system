from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from crypto_trader.llm_runtime.contracts import (
    LLMErrorCode,
    LLMRequest,
    ModelRoute,
    ProviderResult,
    ProviderUpsert,
)
from crypto_trader.llm_runtime.gateway import LLMGateway
from crypto_trader.llm_runtime.repository import LLMRepository
from crypto_trader.llm_runtime.secrets import EncryptedFileSecretStore


class StructuredAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: str


class FakeProvider:
    def __init__(self, results):
        self.results = list(results)
        self.calls = 0

    async def complete(self, **_kwargs):
        self.calls += 1
        return self.results[min(self.calls - 1, len(self.results) - 1)]


async def configured_gateway(database, tmp_path: Path, fake: FakeProvider):
    repository = LLMRepository(database.session_factory)
    secret_store = EncryptedFileSecretStore(tmp_path / "secrets.enc", tmp_path / "master.key")
    gateway = LLMGateway(
        repository,
        secret_store,
        provider_factory=lambda _config: fake,
        sleep=lambda _delay: _noop(),
    )
    await gateway.reload()
    await gateway.save_provider(
        ProviderUpsert(
            provider_id="deepseek",
            provider_type="deepseek",
            display_name="DeepSeek",
            base_url="https://api.deepseek.com",
            api_key="sk-private-1234",
            default_model="deepseek-chat",
        )
    )
    await gateway.save_routes(
        [
            ModelRoute(
                route_name="live_analysis",
                provider_id="deepseek",
                model_name="deepseek-chat",
            )
        ]
    )
    return gateway, repository, secret_store


async def _noop():
    return None


async def test_secret_is_encrypted_masked_and_restart_safe(database, tmp_path):
    fake = FakeProvider([ProviderResult(ok=True, content={"answer": "safe"})])
    gateway, repository, secret_store = await configured_gateway(database, tmp_path, fake)

    encrypted = (tmp_path / "secrets.enc").read_bytes()
    assert b"sk-private-1234" not in encrypted
    assert (tmp_path / "secrets.enc").stat().st_mode & 0o077 == 0
    assert (tmp_path / "master.key").stat().st_mode & 0o077 == 0
    assert gateway.safe_provider(gateway.providers["deepseek"])["api_key_masked"].endswith("1234")
    assert "api_key" not in gateway.safe_provider(gateway.providers["deepseek"])

    restarted = LLMGateway(repository, secret_store, provider_factory=lambda _config: fake)
    await restarted.reload()
    assert restarted.providers["deepseek"].default_model == "deepseek-chat"
    assert restarted.routes["live_analysis"].provider_id == "deepseek"


async def test_route_resolution_structured_validation_and_usage_audit(database, tmp_path):
    fake = FakeProvider(
        [
            ProviderResult(
                ok=True,
                content={"answer": "validated"},
                input_tokens=5,
                output_tokens=2,
                total_tokens=7,
            )
        ]
    )
    gateway, repository, _ = await configured_gateway(database, tmp_path, fake)
    response = await gateway.invoke(
        LLMRequest(route="live_analysis", brain="LIVE", prompt="safe prompt"),
        StructuredAnswer,
    )
    assert response.ok is True
    assert response.content == {"answer": "validated"}
    assert (await repository.usage_today())["today_tokens"] == 7


async def test_unknown_route_disabled_provider_and_invalid_output_fail_closed(database, tmp_path):
    fake = FakeProvider([ProviderResult(ok=True, content={"wrong": "shape"})])
    gateway, _, _ = await configured_gateway(database, tmp_path, fake)
    unknown = await gateway.invoke(LLMRequest(route="missing", brain="LIVE", prompt="safe"))
    assert unknown.error_code == LLMErrorCode.UNKNOWN_ROUTE

    invalid = await gateway.invoke(
        LLMRequest(route="live_analysis", brain="LIVE", prompt="safe"), StructuredAnswer
    )
    assert invalid.error_code == LLMErrorCode.INVALID_RESPONSE
    assert invalid.content is None

    provider = gateway.providers["deepseek"].model_copy(update={"enabled": False})
    await gateway.repository.upsert_provider(provider)
    await gateway.reload()
    disabled = await gateway.invoke(LLMRequest(route="live_analysis", brain="LIVE", prompt="safe"))
    assert disabled.error_code == LLMErrorCode.DISABLED_PROVIDER


async def test_retry_is_bounded_and_circuit_breaker_opens(database, tmp_path):
    retryable = ProviderResult(ok=False, error_code=LLMErrorCode.TIMEOUT, retryable=True)
    fake = FakeProvider([retryable])
    gateway, _, _ = await configured_gateway(database, tmp_path, fake)
    provider = gateway.providers["deepseek"].model_copy(update={"max_retries": 1})
    await gateway.repository.upsert_provider(provider)
    await gateway.reload()

    for _ in range(3):
        response = await gateway.invoke(
            LLMRequest(route="live_analysis", brain="LIVE", prompt="safe")
        )
        assert response.error_code == LLMErrorCode.TIMEOUT
    assert fake.calls == 6

    circuit = await gateway.invoke(LLMRequest(route="live_analysis", brain="LIVE", prompt="safe"))
    assert circuit.error_code == LLMErrorCode.CIRCUIT_OPEN
    assert fake.calls == 6


async def test_route_qualification_is_inert_and_validates_all_six_routes(database, tmp_path):
    contents = iter(
        [
            {"decision_id": "qualification", "symbol": "BTCUSDT", "action": "NO_TRADE"},
            {"summary": "qualification only"},
            {"lessons": ["qualification only"]},
            {"summary": "qualification only"},
            {"hypothesis": "qualification only", "falsification_test": "not executed"},
            {"rationale": "qualification only"},
        ]
    )
    fake = FakeProvider([ProviderResult(ok=True, content=next(contents)) for _ in range(6)])
    gateway, _, _ = await configured_gateway(database, tmp_path, fake)
    await gateway.save_routes(
        [
            ModelRoute(route_name=name, provider_id="deepseek", model_name="deepseek-chat")
            for name in (
                "live_analysis",
                "daily_review",
                "daily_lesson_extraction",
                "evolution_research",
                "evolution_hypothesis",
                "evolution_candidate_reasoning",
            )
        ]
    )

    results = await gateway.qualify_configured_routes()

    assert len(results) == 6
    assert all(result.ok for result in results)
    assert {result.route for result in results} == {
        "live_analysis",
        "daily_review",
        "daily_lesson_extraction",
        "evolution_research",
        "evolution_hypothesis",
        "evolution_candidate_reasoning",
    }
    # Qualification is gateway-only: no trading engine, exchange adapter, or orders are involved.
    assert fake.calls == 6


def test_provider_configuration_rejects_insecure_remote_url():
    with pytest.raises(ValueError, match="HTTPS"):
        ProviderUpsert(
            provider_id="unsafe",
            provider_type="custom",
            display_name="Unsafe",
            base_url="http://provider.example.com",
            api_key="secret",
            default_model="model",
        )
