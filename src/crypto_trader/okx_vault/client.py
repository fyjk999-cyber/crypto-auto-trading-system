"""Agent/runtime client: only operation descriptions and sanitized broker replies."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path


def default_socket():
    return Path(
        os.environ.get(
            "OKX_VAULT_SOCKET",
            "/Library/Application Support/CryptoOKXBroker/ipc/broker/broker.sock",
        )
    )


class BrokerClient:
    def __init__(self, socket_path=None):
        self._socket = Path(socket_path) if socket_path else default_socket()

    async def _call(self, operation, **kwargs):
        writer = None
        try:
            async with asyncio.timeout(55):
                reader, writer = await asyncio.open_unix_connection(
                    str(self._socket), limit=1_000_000
                )
                writer.write(json.dumps({"operation": operation, **kwargs}).encode() + b"\n")
                await writer.drain()
                return json.loads(await reader.readline())
        except Exception:
            return {"ok": False, "error": "BROKER_UNAVAILABLE"}
        finally:
            if writer:
                writer.close()
                await writer.wait_closed()

    async def verify(self):
        return await self._call("verify")

    async def configured(self):
        return await self._call("configured")

    async def credential_status(self):
        return await self._call("credential_status")

    async def validate_okx_demo(self):
        result = await self._call("validate_okx_demo")
        if "authenticated" not in result:
            return {
                "authenticated": False,
                "health": "DEGRADED",
                "stage": "BROKER",
                "reason_code": result.get("error", "BROKER_UNAVAILABLE"),
            }
        return result

    async def signed_request(self, method, path, body=None):
        return await self._call("signed_request", method=method, path=path, body=body)

    async def run_paper(self):
        return await self._call("run_paper")
