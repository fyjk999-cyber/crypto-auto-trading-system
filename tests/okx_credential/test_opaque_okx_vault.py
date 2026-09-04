import asyncio
import base64
import hashlib
import hmac
import json
import os
import secrets
import stat
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from crypto_trader.okx_vault._storage import FIELDS, VaultError, _Vault
from crypto_trader.okx_vault.broker import CredentialBroker
from crypto_trader.okx_vault.client import BrokerClient
from crypto_trader.okx_vault.service import handle_client


class FakeKeyProvider:
    """Ephemeral test-only key. Never stored in fixtures or the repository."""

    def __init__(self):
        self._key = secrets.token_bytes(32)

    def _obtain(self, *, create=False):
        return self._key

    def _delete(self):
        self._key = None


@pytest.fixture
def bundle(tmp_path):
    values = {name: secrets.token_urlsafe(24) for name in FIELDS}
    vault = _Vault(tmp_path / ".secrets/okx-paper-credentials.enc", FakeKeyProvider())
    vault._save(values)
    return vault, values


def test_encrypted_at_rest_and_restart(bundle):
    vault, values = bundle
    original = vault._path.read_bytes()
    for value in values.values():
        assert value.encode() not in original
        for path in vault._path.parent.iterdir():
            assert value.encode() not in path.read_bytes()
    assert stat.S_IMODE(vault._path.stat().st_mode) == 0o600
    assert stat.S_IMODE(vault._path.parent.stat().st_mode) == 0o700
    assert _Vault(vault._path, vault._keys)._decrypt() == values
    vault._save(values)
    assert original != vault._path.read_bytes()  # fresh nonce even with same contents


@pytest.mark.parametrize("damage", ["tamper", "truncate", "wrong_key", "permissions"])
def test_vault_fails_closed(bundle, damage):
    vault, _ = bundle
    if damage == "tamper":
        raw = bytearray(vault._path.read_bytes())
        raw[-1] ^= 1
        vault._path.write_bytes(raw)
    elif damage == "truncate":
        vault._path.write_bytes(vault._path.read_bytes()[:12])
    elif damage == "wrong_key":
        vault._keys = FakeKeyProvider()
    else:
        vault._path.chmod(0o644)
    broker = CredentialBroker(vault, vault._path.parent, Path("unused"))
    assert broker.verify() == {"ok": False, "error": "VAULT_UNAVAILABLE"}


def test_symlink_and_atomic_failure_preserve_previous_bundle(bundle, monkeypatch, tmp_path):
    vault, values = bundle
    old = vault._path.read_bytes()

    def fail_replace(*args):
        raise OSError("test failure")

    with monkeypatch.context() as scoped:
        scoped.setattr(os, "replace", fail_replace)
        with pytest.raises(OSError):
            vault._save(values)
    assert vault._path.read_bytes() == old
    assert list(vault._path.parent.iterdir()) == [vault._path]
    link = tmp_path / "link"
    link.symlink_to(vault._path.parent, target_is_directory=True)
    with pytest.raises(VaultError):
        _Vault(link / "other.enc", FakeKeyProvider())._save(values)


async def test_signed_operation_uses_secrets_without_returning_them(bundle, caplog, capsys):
    caplog.set_level("DEBUG")
    vault, values = bundle
    signatures = []

    def handler(request):
        assert request.url.host == "openapi.okx.com"
        assert request.headers["x-simulated-trading"] == "1"
        assert request.headers["OK-ACCESS-KEY"] == values[FIELDS[0]]
        assert request.headers["OK-ACCESS-PASSPHRASE"] == values[FIELDS[2]]
        prehash = request.headers["OK-ACCESS-TIMESTAMP"] + "GET" + request.url.path
        expected = base64.b64encode(
            hmac.new(values[FIELDS[1]].encode(), prehash.encode(), hashlib.sha256).digest()
        ).decode()
        assert request.headers["OK-ACCESS-SIGN"] == expected
        signatures.append(expected)
        return httpx.Response(
            200,
            json={
                "code": "0",
                "data": [
                    {
                        "acctLv": "2",
                        "posMode": "net_mode",
                        "apiKey": values[FIELDS[0]],
                        "headers": dict(request.headers),
                        "secret": values[FIELDS[1]],
                        "passphrase": values[FIELDS[2]],
                    }
                ],
            },
        )

    broker = CredentialBroker(
        vault, vault._path.parent, Path("unused"), transport=httpx.MockTransport(handler)
    )
    result = await broker.signed_request("GET", "/api/v5/account/config")
    assert result["data"] == [{"acctLv": "2", "posMode": "net_mode"}]
    assert broker.verify()["ok"]
    output = (
        json.dumps(result)
        + repr(broker.credential_status())
        + caplog.text
        + repr(capsys.readouterr())
    )
    for value in [*values.values(), *signatures]:
        assert value not in output


@pytest.mark.parametrize("kind", ["field_echo", "encoded_echo", "error", "exception", "redirect"])
async def test_malicious_upstream_cannot_exfiltrate(bundle, kind, caplog, capsys):
    caplog.set_level("DEBUG")
    vault, values = bundle

    def handler(request):
        if kind == "exception":
            raise httpx.ConnectError(json.dumps(values), request=request)
        if kind == "redirect":
            return httpx.Response(
                302, headers={"Location": "https://example.com/" + values[FIELDS[0]]}
            )
        if kind == "error":
            return httpx.Response(200, json={"code": "50113", "msg": json.dumps(values)})
        value = values[FIELDS[0]]
        if kind == "encoded_echo":
            value = base64.b64encode(value.encode()).decode()
        return httpx.Response(200, json={"code": "0", "data": [{"instId": value}]})

    broker = CredentialBroker(
        vault, vault._path.parent, Path("unused"), transport=httpx.MockTransport(handler)
    )
    result = await broker.signed_request("GET", "/api/v5/account/positions")
    output = json.dumps(result) + caplog.text + repr(capsys.readouterr())
    for value in values.values():
        assert value not in output
        assert base64.b64encode(value.encode()).decode() not in output


@pytest.mark.parametrize(
    "operation_request",
    [
        {"operation": operation}
        for operation in (
            "read",
            "get_credentials",
            "export",
            "dump",
            "show_secret",
            "delete",
            "save",
            "load",
        )
    ]
    + [
        {"operation": "run_paper", "env": {"LIVE_TRADING_ENABLED": "true"}},
        {"operation": "signed_request", "method": "POST", "path": "/api/v5/trade/order"},
        {"operation": "signed_request", "method": "GET", "path": "https://example.com"},
        {
            "operation": "signed_request",
            "method": "GET",
            "path": "/api/v5/account/config?demo=false",
        },
        {
            "operation": "signed_request",
            "method": "GET",
            "path": "/api/v5/account/config",
            "body": {"x-simulated-trading": "0"},
        },
    ],
)
async def test_permissions_fail_closed(bundle, operation_request):
    vault, _ = bundle
    broker = CredentialBroker(vault, vault._path.parent, Path("unused"))
    assert await broker.dispatch(operation_request) == {"ok": False, "error": "OPERATION_DENIED"}


async def test_empty_account_config_rejected_at_broker(bundle):
    vault, _ = bundle
    broker = CredentialBroker(
        vault,
        vault._path.parent,
        Path("unused"),
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"code": "0", "data": []})
        ),
    )
    assert (await broker.validate_okx_demo())["reason_code"] == "MALFORMED_RESPONSE"


def test_paper_child_receives_only_broker_capability_never_credentials(bundle, monkeypatch):
    vault, values = bundle
    captured = {}
    child = MagicMock(pid=12345)
    child.poll.return_value = None

    def spawn(command, **kwargs):
        captured.update(command=command, env=kwargs["env"].copy())
        return child

    probe = MagicMock()
    probe.__enter__.return_value.connect_ex.return_value = 1
    monkeypatch.setattr("crypto_trader.okx_vault.broker.socket.socket", lambda: probe)
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "true")
    monkeypatch.setenv("TRADING_MODE", "LIVE")
    broker = CredentialBroker(vault, vault._path.parent, Path("/tmp/test-broker.sock"), spawn=spawn)
    result = broker.run_paper()
    assert result["ok"]
    assert captured["env"]["OKX_DEMO"] == "true"
    assert captured["env"]["TRADING_MODE"] == "PAPER"
    assert captured["env"]["LIVE_TRADING_ENABLED"] == "false"
    assert captured["env"]["PAPER_MODE"] == "PAPER_REAL_MARKET"
    assert captured["env"]["OKX_VAULT_SOCKET"] == "/tmp/test-broker.sock"
    assert all(name not in captured["env"] for name in FIELDS)
    assert not any(value in json.dumps([result, captured]) for value in values.values())
    assert broker.run_paper()["already_running"]


async def test_unix_socket_agent_interface_has_no_secret_methods(bundle):
    vault, values = bundle
    # AF_UNIX path limit on macOS is 104 bytes; pytest tmp paths can exceed it.
    with tempfile.TemporaryDirectory(prefix="okx-vault-", dir="/tmp") as directory:
        path = Path(directory) / "broker.sock"
        broker = CredentialBroker(vault, vault._path.parent, path)
        server = await asyncio.start_unix_server(
            lambda r, w: handle_client(r, w, broker), path=str(path), limit=8192
        )
        async with server:
            client = BrokerClient(path)
            assert (await client.verify())["ok"]
            assert (await client.configured())["configured"]
            for method in ("read", "export", "dump", "delete", "get_credentials"):
                assert not hasattr(client, method)
                result = await client._call(method)
                assert result["error"] == "OPERATION_DENIED"
                assert not any(v in json.dumps(result) for v in values.values())


def test_human_enrollment_requires_tty(monkeypatch):
    from crypto_trader.okx_vault.cli import _human_terminal

    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    with pytest.raises(VaultError, match="HUMAN_TERMINAL_REQUIRED"):
        _human_terminal()


def test_generated_credential_material_never_enters_tracked_repository(bundle):
    _, values = bundle
    root = Path(__file__).resolve().parents[2]
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).split(b"\x00")
    needles = [value.encode() for value in values.values()]
    for name in tracked:
        if name and (root / os.fsdecode(name)).is_file():
            data = (root / os.fsdecode(name)).read_bytes()
            assert not any(value in data for value in needles), "credential escaped into repository"
    assert (
        subprocess.run(
            ["git", "check-ignore", "-q", ".secrets/okx-paper-credentials.enc"],
            cwd=root,
        ).returncode
        == 0
    )


async def test_demo_validation_success_without_remote_orders(bundle):
    vault, _ = bundle
    paths = []

    def handler(request):
        paths.append((request.method, request.url.path))
        rows = (
            [{"acctLv": "2", "posMode": "net_mode"}] if request.url.path.endswith("config") else []
        )
        return httpx.Response(200, json={"code": "0", "data": rows})

    broker = CredentialBroker(
        vault, vault._path.parent, Path("unused"), transport=httpx.MockTransport(handler)
    )
    result = await broker.validate_okx_demo()
    assert result["authenticated"] is True
    assert result["environment"] == "DEMO"
    assert len(paths) == 4
    assert all(method == "GET" for method, _ in paths)


def test_busy_runtime_port_does_not_spawn_another_process(bundle, monkeypatch):
    vault, _ = bundle
    probe = MagicMock()
    probe.__enter__.return_value.connect_ex.return_value = 0
    monkeypatch.setattr("crypto_trader.okx_vault.broker.socket.socket", lambda: probe)
    spawn = MagicMock()
    broker = CredentialBroker(vault, vault._path.parent, Path("unused"), spawn=spawn)
    assert broker.run_paper()["error"] == "RUNTIME_ALREADY_LISTENING"
    spawn.assert_not_called()
