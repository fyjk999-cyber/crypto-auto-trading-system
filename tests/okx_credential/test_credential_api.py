import time
from pathlib import Path

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
    assert response.status_code == 200
    assert response.json()["key_suffix"] == "ABCD"
    assert "secret" not in response.text
    assert "pass-1" not in response.text

    status = client.get("/exchange/okx/status").json()
    assert status["configured"] is True
    assert status["key_suffix"] == "ABCD"
    assert "secret" not in status

    delete = client.delete("/exchange/okx/credentials").json()
    assert delete["configured"] is False
    assert EnvCredentialStore(env_file).read() == {}


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
    assert response.json()["reason_code"] == "NOT_CONFIGURED"


def test_credential_store_key_suffix_only():
    assert EnvCredentialStore.key_suffix("abcd1234") == "1234"
    assert EnvCredentialStore.key_suffix(None) is None


def test_env_file_is_gitignored():
    root = Path(__file__).resolve().parents[2]
    assert ".env" in (root / ".gitignore").read_text()


def test_configured_demo_credentials_are_validated_automatically_on_startup(
    database, monkeypatch, tmp_path
):
    env_file = tmp_path / ".env"
    monkeypatch.setenv("OKX_CREDENTIALS_ENV_FILE", str(env_file))
    EnvCredentialStore(env_file).write(
        {
            "OKX_API_KEY": "demo-key-1234",
            "OKX_API_SECRET": "demo-secret",
            "OKX_API_PASSPHRASE": "demo-pass",
            "OKX_DEMO": "true",
        }
    )

    class ValidDemoAdapter:
        def __init__(self, **_kwargs):
            pass

        async def connect(self):
            pass

        async def disconnect(self):
            pass

        async def sync_server_time(self):
            return {"offset_ms": 0}

        async def get_account_config(self):
            return {"data": [{"acctLv": "2", "posMode": "net_mode"}]}

        async def get_balances(self):
            return []

        async def get_positions(self):
            return []

        async def get_pending_orders(self):
            return {"data": []}

    monkeypatch.setattr("crypto_trader.api.app.OKXAdapter", ValidDemoAdapter)
    with TestClient(create_app(make_state(database, str(env_file)))) as client:
        payload = {}
        for _ in range(20):
            payload = client.get("/exchange/okx/status").json()
            if payload.get("authenticated") is True:
                break
            time.sleep(0.01)

    assert payload["authenticated"] is True
    assert payload["health"] == "HEALTHY"
    assert payload["key_suffix"] == "1234"
