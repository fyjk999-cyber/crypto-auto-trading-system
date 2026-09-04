"""Contract tests only; these deliberately do NOT claim OS isolation is installed."""

import asyncio
import importlib.util
import json
import os
import plistlib
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from crypto_trader.okx_vault import cli, enrollment, isolation, service
from crypto_trader.okx_vault.broker import PATHS, CredentialBroker
from crypto_trader.okx_vault.client import BrokerClient, default_socket
from crypto_trader.okx_vault.paper_launcher import PaperLauncher

ROOT = Path(__file__).resolve().parents[2]


def test_default_ipc_outside_private_vault(monkeypatch):
    monkeypatch.delenv("OKX_VAULT_SOCKET", raising=False)
    assert default_socket() == isolation.SOCKET
    assert not default_socket().is_relative_to(isolation.HOME)
    assert isolation.PAPER_SOCKET.parent != isolation.SOCKET.parent


@pytest.mark.parametrize("action", ["save", "delete"])
def test_unprivileged_cli_never_enrolls(action, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["okx-vault", action])
    with pytest.raises(SystemExit, match="ADMIN_PROTECTED_ENROLLMENT_REQUIRED"):
        cli.main()


@pytest.mark.parametrize("action", ["save", "delete", "export", "unlock", "initialize"])
def test_protected_enrollment_requires_root(action, monkeypatch):
    monkeypatch.setattr(os, "getuid", lambda: 501)
    monkeypatch.setattr(sys, "argv", ["enrollment", action])
    with pytest.raises(PermissionError):
        enrollment.main()


@pytest.mark.asyncio
async def test_isolated_run_delegates_without_secrets(tmp_path, monkeypatch):
    class Vault:
        _path = tmp_path / "vault"

        def _decrypt(self):
            return {}  # Ephemeral fake provider, no real vault access.

    called = []

    async def run(client):
        called.append(client._socket)
        return {"ok": True, "pid": 123, "arbitrary": "discarded"}

    monkeypatch.setattr(BrokerClient, "run_paper", run)
    broker = CredentialBroker(
        Vault(),
        tmp_path,
        isolation.SOCKET,
        isolated=True,
        spawn=lambda *a, **k: pytest.fail("Broker must never spawn trading"),
    )
    result = await broker.dispatch({"operation": "run_paper"})
    assert called == [isolation.PAPER_SOCKET]
    assert result == {
        "ok": True,
        "pid": 123,
        "mode": "PAPER",
        "live_trading_enabled": False,
        "credential_transport": "BROKER_SIGNING",
    }


@pytest.mark.asyncio
async def test_paper_launcher_denies_arbitrary_operations(tmp_path):
    launcher = PaperLauncher({"paper_home": str(tmp_path)})
    for request in (
        {"operation": "verify"},
        {"operation": "run_paper", "env": {}},
        {"operation": "signed_request"},
        {"operation": "delete"},
    ):
        assert await launcher.dispatch(request) == {"ok": False, "error": "OPERATION_DENIED"}


@pytest.mark.asyncio
async def test_peer_authentication_before_dispatch(monkeypatch):
    reader = asyncio.StreamReader()
    reader.feed_data(b'{"operation":"configured"}\n')
    writer = AsyncMock()
    writer.get_extra_info = lambda _: object()
    output = []
    writer.write = output.append
    writer.close = Mock()
    broker = AsyncMock()
    monkeypatch.setattr(service, "peer_uid", lambda _: 999)
    await service.handle_client(reader, writer, broker, {501})
    broker.dispatch.assert_not_called()
    assert json.loads(output[0])["ok"] is False


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform != "darwin", reason="real macOS getpeereid")
async def test_real_unix_peer_uid():
    observed = []

    async def accept(reader, writer):
        observed.append(isolation.peer_uid(writer.get_extra_info("socket")))
        writer.write(b"ok\n")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    # macOS sockaddr_un is bounded; pytest's default temp path exceeds it.
    with tempfile.TemporaryDirectory(prefix="okx-peer-", dir="/tmp") as directory:
        path = Path(directory) / "peer.sock"
        async with await asyncio.start_unix_server(accept, path=str(path)):
            reader, writer = await asyncio.open_unix_connection(str(path))
            assert await reader.readline() == b"ok\n"
            writer.close()
            await writer.wait_closed()
    assert observed == [os.getuid()]


def test_read_only_demo_allowlist_unchanged():
    assert PATHS == {
        "/api/v5/account/config",
        "/api/v5/account/balance",
        "/api/v5/account/positions",
        "/api/v5/trade/orders-pending",
    }


def test_daemon_identity_and_core_dump_contract():
    plist = plistlib.loads((ROOT / "deploy/macos/com.crypto-trader.okx-broker.plist").read_bytes())
    assert plist["UserName"] == "crypto-okx-broker"
    assert plist["HardResourceLimits"]["Core"] == 0
    assert plist["SoftResourceLimits"]["Core"] == 0
    assert str(isolation.RUNTIME) in plist["ProgramArguments"][0]
    assert "-I" in plist["ProgramArguments"]


def test_verifier_missing_file_is_not_denial(tmp_path):
    spec = importlib.util.spec_from_file_location("os_verifier", ROOT / "deploy/macos/verify.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.denied_open(tmp_path / "missing", os.O_RDONLY) is False
    readable = tmp_path / "readable"
    readable.write_text("non-secret probe")
    assert module.denied_open(readable, os.O_RDONLY) is False
    assert readable.read_text() == "non-secret probe"


def test_policy_cannot_be_forged_by_agent(tmp_path, monkeypatch):
    policy = tmp_path / "policy.json"
    policy.write_text('{"broker_uid":501}')
    monkeypatch.setattr(isolation, "CONFIG", policy)
    with pytest.raises(PermissionError, match="UNPROTECTED_POLICY"):
        isolation.protected_policy()
