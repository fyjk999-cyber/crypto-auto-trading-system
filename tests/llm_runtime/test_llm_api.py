from fastapi.testclient import TestClient

from crypto_trader.api.app import create_app
from crypto_trader.api.deps import AppState
from crypto_trader.config import Settings
from crypto_trader.ledger.service import LedgerService
from crypto_trader.llm_runtime.contracts import ProviderResult
from crypto_trader.llm_runtime.gateway import LLMGateway
from crypto_trader.llm_runtime.repository import LLMRepository
from crypto_trader.llm_runtime.secrets import EncryptedFileSecretStore
from crypto_trader.market_data.service import MarketDataService
from crypto_trader.observability.audit import AuditService
from crypto_trader.order.manager import OrderManager
from crypto_trader.portfolio.service import PortfolioService
from crypto_trader.reconciliation.service import ReconciliationService
from crypto_trader.risk.engine import RiskEngine
from crypto_trader.runtime.lease import LeaseManager


def make_state(database):
    settings = Settings(
        _env_file=None,
        app_env="development",
        trading_mode="PAPER",
        database_url=database.url,
    )
    return AppState(
        settings=settings,
        database=database,
        order_manager=OrderManager(database.session_factory),
        ledger=LedgerService(database.session_factory),
        portfolio=PortfolioService(database.session_factory),
        audit=AuditService(database.session_factory),
        risk=RiskEngine(),
        market_data=MarketDataService(),
        leases=LeaseManager(database.session_factory),
        reconciliation=ReconciliationService(database.session_factory),
    )


class HealthyProvider:
    async def complete(self, **_kwargs):
        return ProviderResult(
            ok=True,
            content={"ok": True},
            latency_ms=12,
            input_tokens=4,
            output_tokens=2,
            total_tokens=6,
        )


async def test_provider_api_hot_reload_test_and_secret_redaction(database, monkeypatch, tmp_path):
    monkeypatch.setenv("OKX_CREDENTIALS_ENV_FILE", str(tmp_path / "okx.env"))
    state = make_state(database)
    repository = LLMRepository(database.session_factory)
    state.llm_repository = repository
    state.llm_gateway = LLMGateway(
        repository,
        EncryptedFileSecretStore(tmp_path / "secrets.enc", tmp_path / "master.key"),
        provider_factory=lambda _config: HealthyProvider(),
    )
    await state.llm_gateway.reload()
    client = TestClient(create_app(state))
    provider = {
        "provider_id": "deepseek",
        "provider_type": "deepseek",
        "display_name": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "api_key": "sk-never-return-this-5678",
        "default_model": "deepseek-chat",
        "enabled": True,
        "timeout_seconds": 15,
        "max_retries": 1,
    }
    created = client.post("/llm/providers", json=provider)
    assert created.status_code == 200
    assert created.json()["api_key_masked"].endswith("5678")
    assert "never-return" not in created.text

    listed = client.get("/llm/providers")
    assert listed.status_code == 200
    assert "never-return" not in listed.text
    assert listed.json()["providers"][0]["configured"] is True

    routes = [
        {
            "route_name": name,
            "provider_id": "deepseek",
            "model_name": "deepseek-chat",
            "enabled": True,
            "temperature": 0.2,
            "max_tokens": 100,
            "timeout_seconds": 15,
        }
        for name in (
            "live_analysis",
            "daily_review",
            "daily_lesson_extraction",
            "evolution_research",
            "evolution_hypothesis",
            "evolution_candidate_reasoning",
        )
    ]
    saved_routes = client.put("/llm/routes", json={"routes": routes})
    assert saved_routes.status_code == 200
    assert len(saved_routes.json()["routes"]) == 6

    tested = client.post("/llm/test", json={"provider_id": "deepseek"})
    assert tested.status_code == 200
    assert tested.json()["ok"] is True
    assert "never-return" not in tested.text
    status = client.get("/llm/status").json()
    assert status["health"] == "HEALTHY"
    assert status["routes"] == 6
    assert status["usage"]["today_calls"] == 1

    qualification = client.post("/llm/qualification")
    assert qualification.status_code == 200
    assert len(qualification.json()["checks"]) == 6
    assert qualification.json()["ok"] is False  # stub is intentionally not six schemas
    assert "never-return" not in qualification.text

    restarted = LLMGateway(
        repository,
        state.llm_gateway.secret_store,
        provider_factory=lambda _config: HealthyProvider(),
    )
    await restarted.reload()
    assert "deepseek" in restarted.providers
    assert set(restarted.routes) == {route["route_name"] for route in routes}


async def test_risk_endpoint_reports_honest_metrics(database):
    client = TestClient(create_app(make_state(database)))
    payload = client.get("/risk").json()
    metrics = payload["metrics"]
    assert metrics["flat"] is True                       # empty ledger -> no positions
    assert metrics["effective_leverage"] == "0"          # real zero, not fabricated
    assert metrics["margin_ratio"] == "0"                # no positions -> no margin used
    assert metrics["current_drawdown"] == "NOT_AVAILABLE"  # equity peak not tracked
    assert metrics["risk_multiplier"] == "NOT_AVAILABLE"
    assert payload["kill_switch"]["enabled"] is False
    assert payload["trading_mode"] == "PAPER"
