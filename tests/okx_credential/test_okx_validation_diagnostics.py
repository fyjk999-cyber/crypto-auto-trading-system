import httpx
import pytest
from fastapi.testclient import TestClient
from test_credential_api import make_state

from crypto_trader.api.app import create_app
from crypto_trader.credentials import EnvCredentialStore
from crypto_trader.exchange.okx import OKXAdapter, OKXDiagnosticError


def okx_response(code="0", msg="", data=None, status_code=200):
    return httpx.Response(status_code, json={"code": code, "msg": msg, "data": data or []})


@pytest.mark.asyncio
async def test_http_200_requires_okx_code_zero():
    client = httpx.AsyncClient(
        base_url="https://okx.test",
        transport=httpx.MockTransport(lambda request: okx_response("50113", "Invalid signature")),
    )
    adapter = OKXAdapter(
        api_key="demo-key", api_secret="demo-secret", api_passphrase="demo-pass", client=client
    )
    await adapter.connect()
    with pytest.raises(OKXDiagnosticError) as raised:
        await adapter.get_account_config()
    assert raised.value.reason_code == "AUTH_FAILED"
    assert raised.value.exchange_code == "50113"
    await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("code", "message", "expected"),
    [
        ("50113", "Invalid signature", "AUTH_FAILED"),
        ("50000", "Permission denied", "PERMISSION_DENIED"),
        ("50115", "IP is not in whitelist", "IP_RESTRICTED"),
        ("50101", "API key environment mismatch", "DEMO_ENV_MISMATCH"),
        ("50011", "Rate limit exceeded", "RATE_LIMITED"),
        ("99999", "Unknown business failure", "OKX_REJECTED"),
    ],
)
async def test_okx_business_errors_have_typed_safe_reasons(code, message, expected):
    client = httpx.AsyncClient(
        base_url="https://okx.test",
        transport=httpx.MockTransport(lambda request: okx_response(code, message)),
    )
    adapter = OKXAdapter(
        api_key="demo-key", api_secret="demo-secret", api_passphrase="demo-pass", client=client
    )
    await adapter.connect()
    with pytest.raises(OKXDiagnosticError) as raised:
        await adapter.get_balances()
    assert raised.value.reason_code == expected
    assert "demo-secret" not in raised.value.safe_message
    await client.aclose()


@pytest.mark.asyncio
async def test_okx_transport_and_service_failures_remain_distinct():
    def timeout(_request):
        raise httpx.ConnectTimeout("timeout")

    client = httpx.AsyncClient(base_url="https://okx.test", transport=httpx.MockTransport(timeout))
    adapter = OKXAdapter(client=client)
    with pytest.raises(OKXDiagnosticError, match="Unable to connect") as network:
        await adapter.sync_server_time()
    assert network.value.reason_code == "NETWORK_ERROR"
    await client.aclose()

    client = httpx.AsyncClient(
        base_url="https://okx.test",
        transport=httpx.MockTransport(lambda request: httpx.Response(503)),
    )
    adapter = OKXAdapter(client=client)
    with pytest.raises(OKXDiagnosticError) as unavailable:
        await adapter.sync_server_time()
    assert unavailable.value.reason_code == "OKX_UNAVAILABLE"
    await client.aclose()


@pytest.mark.asyncio
async def test_non_ascii_credential_is_safe_auth_failure():
    client = httpx.AsyncClient(
        base_url="https://okx.test", transport=httpx.MockTransport(okx_response)
    )
    adapter = OKXAdapter(
        api_key="demo-key",
        api_secret="demo-secret",
        api_passphrase="invalid！",
        client=client,
    )
    await adapter.connect()
    with pytest.raises(OKXDiagnosticError) as raised:
        await adapter.get_account_config()
    assert raised.value.reason_code == "AUTH_FAILED"
    assert "invalid" not in raised.value.safe_message
    await client.aclose()


def test_validate_empty_account_config_is_malformed_and_never_returns_secret(
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

    class EmptyConfigAdapter:
        def __init__(self, **_kwargs):
            pass

        async def connect(self):
            pass

        async def disconnect(self):
            pass

        async def sync_server_time(self):
            return {"offset_ms": 0}

        async def get_account_config(self):
            return {"code": "0", "data": []}

    monkeypatch.setattr("crypto_trader.api.app.OKXAdapter", EmptyConfigAdapter)
    response = TestClient(create_app(make_state(database, str(env_file)))).post(
        "/exchange/okx/validate"
    )
    payload = response.json()
    assert payload == {
        "authenticated": False,
        "health": "DEGRADED",
        "stage": "ACCOUNT_CONFIG",
        "reason_code": "MALFORMED_RESPONSE",
        "message": "OKX account configuration response is incomplete",
    }
    assert "demo-secret" not in response.text
    assert "demo-pass" not in response.text
