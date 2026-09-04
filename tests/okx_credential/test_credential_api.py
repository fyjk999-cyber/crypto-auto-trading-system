from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from crypto_trader.api.app import create_app
from crypto_trader.api.deps import AppState
from crypto_trader.config import Settings
from crypto_trader.credentials import EnvCredentialStore
from crypto_trader.ledger.service import LedgerService
from crypto_trader.market_data.service import MarketDataService
from crypto_trader.observability.audit import AuditService
from crypto_trader.order.manager import OrderManager
from crypto_trader.portfolio.service import PortfolioService
from crypto_trader.reconciliation.service import ReconciliationService
from crypto_trader.risk.engine import RiskEngine
from crypto_trader.runtime.lease import LeaseManager


@pytest.fixture(autouse=True)
def isolate_real_broker(monkeypatch, tmp_path):
    # Never connect a test to the user's enrolled/running credential broker.
    monkeypatch.setenv("OKX_VAULT_SOCKET", str(tmp_path / "nonexistent-test-broker.sock"))


def make_state(database, tmp_env: str):
    settings = Settings(
        _env_file=None, app_env="development", trading_mode="PAPER", database_url=database.url
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


async def test_credential_save_status_delete(database, monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    monkeypatch.setenv("OKX_CREDENTIALS_ENV_FILE", str(env_file))
    state = make_state(database, str(env_file))
    client = TestClient(create_app(state))

    response = client.post(
        "/exchange/okx/credentials",
        json={
            "api_key": "demo-key-ABCD",
            "api_secret": "secret-1",
            "api_passphrase": "pass-1",
            "base_url": "https://openapi.okx.com",
            "demo": True,
        },
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "HUMAN_VAULT_CLI_REQUIRED"
    assert "secret" not in response.text
    assert "pass-1" not in response.text

    class Client:
        async def credential_status(self):
            return {"configured": True, "key_suffix": None, "environment": "DEMO"}

    monkeypatch.setattr("crypto_trader.api.app.BrokerClient", Client)
    client = TestClient(create_app(state))
    status = client.get("/exchange/okx/status").json()
    assert status["configured"] is True
    assert status["key_suffix"] is None
    assert "secret" not in status

    assert client.delete("/exchange/okx/credentials").status_code == 403
    assert not env_file.exists()


async def test_credential_live_rejected(database, monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    monkeypatch.setenv("OKX_CREDENTIALS_ENV_FILE", str(env_file))
    client = TestClient(create_app(make_state(database, str(env_file))))
    response = client.post(
        "/exchange/okx/credentials",
        json={
            "api_key": "k",
            "api_secret": "s",
            "api_passphrase": "p",
            "base_url": "https://openapi.okx.com",
            "demo": False,
        },
    )
    assert response.status_code == 403


async def test_credential_validate_missing_returns_not_configured(database, monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    monkeypatch.setenv("OKX_CREDENTIALS_ENV_FILE", str(env_file))
    client = TestClient(create_app(make_state(database, str(env_file))))
    response = client.post("/exchange/okx/validate")
    assert response.status_code == 200
    assert response.json()["reason_code"] == "BROKER_UNAVAILABLE"


def test_legacy_plaintext_read_write_delete_denied(tmp_path):
    store = EnvCredentialStore(tmp_path / ".env")
    for action in (store.read, lambda: store.write({}), store.clear):
        with pytest.raises(PermissionError):
            action()
    assert not (tmp_path / ".env").exists()


def test_runtime_environment_credentials_override_legacy_file(monkeypatch, tmp_path):
    # Environment injection is retired as well as file storage.
    import secrets

    monkeypatch.setenv("OKX_API_KEY", secrets.token_urlsafe(24))
    with pytest.raises(PermissionError):
        EnvCredentialStore(tmp_path / ".env").read()


def test_env_file_is_gitignored():
    root = Path(__file__).resolve().parents[2]
    assert ".env" in (root / ".gitignore").read_text()
