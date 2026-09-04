"""Credential-free launcher under the main UID, never under the vault owner UID."""

import asyncio
import os
import resource
from pathlib import Path

from .broker import CredentialBroker, failure
from .isolation import PAPER_SOCKET, SOCKET, protected_policy
from .service import handle_client


class PaperLauncher:
    def __init__(self, policy):
        self._runtime = CredentialBroker(None, Path(policy["paper_home"]), SOCKET)

    async def dispatch(self, request):
        if request != {"operation": "run_paper"}:
            return failure("OPERATION_DENIED")
        # Peer authentication admits only the protected broker, which verified
        # the real vault before forwarding. There is no fake credential provider.
        return self._runtime._launch_paper()


async def serve():
    policy = protected_policy()
    if os.getuid() != policy["client_uid"] or os.getuid() == policy["broker_uid"]:
        raise PermissionError
    launcher = PaperLauncher(policy)
    if PAPER_SOCKET.is_symlink():
        raise PermissionError
    PAPER_SOCKET.unlink(missing_ok=True)
    server = await asyncio.start_unix_server(
        lambda r, w: handle_client(r, w, launcher, {policy["broker_uid"]}),
        path=str(PAPER_SOCKET),
        limit=8192,
    )
    os.chown(PAPER_SOCKET, -1, policy["ipc_gid"])
    PAPER_SOCKET.chmod(0o660)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    os.umask(0o077)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    try:
        asyncio.run(serve())
    except Exception:
        raise SystemExit("PAPER_LAUNCHER_FAILED") from None
