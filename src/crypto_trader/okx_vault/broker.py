"""Operations-only broker. Never returns headers, signatures, or upstream error text."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import re
import socket
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

import httpx

from ._storage import BUNDLE, FIELDS

PATHS = {
    "/api/v5/account/config",
    "/api/v5/account/balance",
    "/api/v5/account/positions",
    "/api/v5/trade/orders-pending",
}
NUMERIC_FIELDS = {"totalEq", "eq", "availBal", "cashBal", "pos", "avgPx", "upl", "sz", "px"}
LABEL_FIELDS = {"ccy", "instId", "instType", "posSide", "side", "state"}


def failure(code):
    return {"ok": False, "error": code}


def _project(value):
    """Drop free text, arbitrary fields, identifiers, headers, URLs and signing material."""
    if not isinstance(value, list) or len(value) > 10000:
        raise ValueError
    rows = []
    for row in value:
        if not isinstance(row, dict):
            raise ValueError
        out = {}
        for name, field in row.items():
            if not isinstance(field, str):
                if name == "details":
                    out[name] = _project(field)
                continue
            if name == "acctLv" and field in {"1", "2", "3", "4"}:
                out[name] = field
            elif name == "posMode" and field in {"net_mode", "long_short_mode"}:
                out[name] = field
            elif name in NUMERIC_FIELDS and re.fullmatch(r"-?\d{1,30}(\.\d{1,30})?", field):
                out[name] = field
            elif name in LABEL_FIELDS and re.fullmatch(r"[A-Za-z0-9_-]{1,48}", field):
                out[name] = field
        rows.append(out)
    return rows


class CredentialBroker:
    def __init__(self, vault, root: Path, socket_path: Path, *, transport=None, spawn=None):
        self._vault, self._root, self._socket = vault, root, socket_path
        self._transport, self._spawn = transport, spawn or subprocess.Popen
        self._lock = asyncio.Lock()
        self._child = None

    def credential_status(self):
        # This is API isolation, not a claim of same-user OS isolation.
        return {
            "bundle": BUNDLE,
            "provider": "OKX",
            "environment": "DEMO",
            "configured": self._vault._path.is_file(),
            "key_suffix": None,
            "storage": "AES_256_GCM_KEYCHAIN",
            "secret_return_supported": False,
            "os_agent_isolation": "NOT_ENFORCED",
        }

    def configured(self):
        return {"configured": self.credential_status()["configured"]}

    def verify(self):
        values = None
        try:
            values = self._vault._decrypt()
            return {"ok": True, "configured": True, "bundle": BUNDLE}
        except Exception:
            return failure("VAULT_UNAVAILABLE")
        finally:
            if values:
                values.clear()

    async def signed_request(self, method, path, body=None):
        if method != "GET" or path not in PATHS or body not in (None, {}):
            return failure("OPERATION_DENIED")
        async with self._lock:
            return await self._signed(path)

    async def _signed(self, path):
        values, headers = {}, {}
        try:
            values = self._vault._decrypt()
            stamp = datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
            signature = base64.b64encode(
                hmac.new(
                    values["OKX_API_SECRET"].encode(),
                    (stamp + "GET" + path).encode(),
                    hashlib.sha256,
                ).digest()
            ).decode()
            headers = {
                "OK-ACCESS-KEY": values["OKX_API_KEY"],
                "OK-ACCESS-PASSPHRASE": values["OKX_API_PASSPHRASE"],
                "OK-ACCESS-SIGN": signature,
                "OK-ACCESS-TIMESTAMP": stamp,
                "x-simulated-trading": "1",
            }
            async with httpx.AsyncClient(
                base_url="https://openapi.okx.com",
                timeout=10,
                follow_redirects=False,
                trust_env=False,
                transport=self._transport,
            ) as client:
                async with client.stream("GET", path, headers=headers) as response:
                    if response.status_code != 200:
                        return failure("OKX_UNAVAILABLE")
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 1_000_000:
                            return failure("RESPONSE_TOO_LARGE")
                    payload = json.loads(raw)
            if not isinstance(payload, dict) or payload.get("code") != "0":
                return failure("OKX_DEMO_REQUEST_FAILED")
            result = {
                "ok": True,
                "code": "0",
                "data": _project(payload.get("data")),
                "provider": "OKX",
                "environment": "DEMO",
            }
            encoded = json.dumps(result)
            for secret in (*values.values(), signature):
                variants = (
                    secret,
                    base64.b64encode(secret.encode()).decode(),
                    secret.encode().hex(),
                    quote(secret, safe=""),
                )
                if any(v in encoded for v in variants):
                    return failure("UNSAFE_UPSTREAM_RESPONSE")
            return result
        except Exception:
            # Never serialize exception/request/response objects or traceback locals.
            return failure("BROKER_REQUEST_FAILED")
        finally:
            values.clear()
            headers.clear()
            await asyncio.sleep(0.25)

    async def validate_okx_demo(self):
        counts, config = {}, {}
        for path, stage in (
            ("/api/v5/account/config", "ACCOUNT_CONFIG"),
            ("/api/v5/account/balance", "BALANCE"),
            ("/api/v5/account/positions", "POSITIONS"),
            ("/api/v5/trade/orders-pending", "PENDING_ORDERS"),
        ):
            result = await self.signed_request("GET", path)
            if not result["ok"]:
                return {
                    "authenticated": False,
                    "health": "DEGRADED",
                    "stage": stage,
                    "reason_code": result["error"],
                }
            if stage == "ACCOUNT_CONFIG":
                rows = result["data"]
                if not rows or not {"acctLv", "posMode"} <= rows[0].keys():
                    return {
                        "authenticated": False,
                        "health": "DEGRADED",
                        "stage": stage,
                        "reason_code": "MALFORMED_RESPONSE",
                    }
                config = rows[0]
            counts[stage] = len(result["data"])
        return {
            "authenticated": True,
            "health": "HEALTHY",
            "stage": "COMPLETE",
            "reason_code": None,
            "environment": "DEMO",
            "account_mode": config["acctLv"],
            "position_mode": config["posMode"],
            "balances": counts["BALANCE"],
            "positions": counts["POSITIONS"],
            "pending_orders": counts["PENDING_ORDERS"],
        }

    def run_paper(self):
        if not self.verify()["ok"]:
            return failure("VAULT_UNAVAILABLE")
        if self._child is not None and self._child.poll() is None:
            return {"ok": True, "pid": self._child.pid, "mode": "PAPER", "already_running": True}
        # Fixed launch only. No caller-provided command, environment, port or executable.
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", 8000)) == 0:
                return failure("RUNTIME_ALREADY_LISTENING")
        allowed = {
            "PATH",
            "HOME",
            "TMPDIR",
            "LANG",
            "LC_ALL",
            "TZ",
            "DATABASE_URL",
            "DEEPSEEK_API_KEY",
            "LLM_PROVIDER",
            "LLM_MODEL",
            "LLM_BASE_URL",
        }
        env = {k: v for k, v in os.environ.items() if k in allowed}
        env.update(
            {
                "OKX_VAULT_SOCKET": str(self._socket),
                "OKX_DEMO": "true",
                "TRADING_MODE": "PAPER",
                "PAPER_MODE": "PAPER_REAL_MARKET",
                "LIVE_TRADING_ENABLED": "false",
                "AUTO_START_RUNTIME": "true",
            }
        )
        for name in FIELDS:
            env.pop(name, None)
        try:
            self._child = self._spawn(
                [
                    str(self._root / ".venv/bin/python"),
                    "-m",
                    "crypto_trader.runtime.local_runner",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "8000",
                ],
                cwd=self._root,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return {
                "ok": True,
                "pid": self._child.pid,
                "mode": "PAPER",
                "credential_transport": "BROKER_SIGNING",
                "live_trading_enabled": False,
            }
        except Exception:
            return failure("RUNTIME_START_FAILED")
        finally:
            env.clear()

    async def dispatch(self, request):
        if not isinstance(request, dict):
            return failure("OPERATION_DENIED")
        action = request.get("operation")
        if action == "signed_request" and set(request) <= {"operation", "method", "path", "body"}:
            return await self.signed_request(
                request.get("method"), request.get("path"), request.get("body")
            )
        if set(request) != {"operation"}:
            return failure("OPERATION_DENIED")
        if action == "validate_okx_demo":
            return await self.validate_okx_demo()
        methods = {
            "verify": self.verify,
            "configured": self.configured,
            "credential_status": self.credential_status,
            "run_paper": self.run_paper,
        }
        if action not in methods:
            return failure("OPERATION_DENIED")
        return methods[action]()
