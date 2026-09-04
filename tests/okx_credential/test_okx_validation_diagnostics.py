import httpx
import pytest
from fastapi.testclient import TestClient
from test_credential_api import make_state

from crypto_trader.api.app import create_app
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

    # The HTTP control plane only forwards a typed, sanitized broker result.
    # The real empty-config validation is exercised by test_opaque_okx_vault.py.
    class EmptyConfigBroker:
        async def validate_okx_demo(self):
            return {
                "authenticated": False,
                "health": "DEGRADED",
                "stage": "ACCOUNT_CONFIG",
                "reason_code": "MALFORMED_RESPONSE",
            }

    monkeypatch.setattr("crypto_trader.api.app.BrokerClient", EmptyConfigBroker)
    response = TestClient(create_app(make_state(database, str(env_file)))).post(
        "/exchange/okx/validate"
    )
    payload = response.json()
    assert payload == {
        "authenticated": False,
        "health": "DEGRADED",
        "stage": "ACCOUNT_CONFIG",
        "reason_code": "MALFORMED_RESPONSE",
    }
    assert "demo-secret" not in response.text
    assert "demo-pass" not in response.text
