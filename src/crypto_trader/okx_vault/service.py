"""Local Unix socket broker. No TCP, no raw-body logs, no save/delete RPC."""

from __future__ import annotations

import asyncio
import fcntl
import json
import os
import resource
from pathlib import Path

from ._storage import BUNDLE, _KeychainKey, _Vault, private_directory
from .broker import CredentialBroker, failure
from .isolation import KEYCHAIN, SOCKET, VAULT, broker_identity, peer_uid, private_home

ROOT = Path(__file__).resolve().parents[3]
DIRECTORY = VAULT


async def handle_client(reader, writer, broker, allowed_uids=None):
    try:
        if (
            allowed_uids is not None
            and peer_uid(writer.get_extra_info("socket")) not in allowed_uids
        ):
            raise PermissionError
        async with asyncio.timeout(55):
            raw = await reader.readline()
            if len(raw) > 8192:
                raise ValueError
            result = await broker.dispatch(json.loads(raw))
    except Exception:
        result = failure("INVALID_BROKER_REQUEST")
    try:
        writer.write(json.dumps(result).encode() + b"\n")
        await writer.drain()
    finally:
        writer.close()
        await writer.wait_closed()


async def serve():
    policy = broker_identity()
    private_home()
    private_directory(DIRECTORY)
    lock_fd = os.open(DIRECTORY / "okx-broker.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        vault = _Vault(DIRECTORY / (BUNDLE + ".enc"), _KeychainKey(KEYCHAIN))
        broker = CredentialBroker(vault, ROOT, SOCKET, isolated=True)
        if SOCKET.is_symlink():
            raise RuntimeError("UNSAFE_SOCKET")
        SOCKET.unlink(missing_ok=True)
        server = await asyncio.start_unix_server(
            lambda reader, writer: handle_client(
                reader, writer, broker, {policy["client_uid"], policy["broker_uid"]}
            ),
            path=str(SOCKET),
            limit=8192,
        )
        os.chown(SOCKET, -1, policy["ipc_gid"])
        SOCKET.chmod(0o660)
        async with server:
            await server.serve_forever()
    finally:
        os.close(lock_fd)


if __name__ == "__main__":
    os.umask(0o077)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    try:
        asyncio.run(serve())
    except KeyboardInterrupt:
        pass
    except Exception:
        raise SystemExit("OKX_BROKER_START_FAILED") from None
