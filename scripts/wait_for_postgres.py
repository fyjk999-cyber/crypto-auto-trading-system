"""Wait until the PostgreSQL host/port from DATABASE_URL accepts connections.

Cloud entrypoint helper: pure stdlib, no app imports, no secrets printed.
"""
from __future__ import annotations

import os
import socket
import sys
import time
from urllib.parse import urlparse


def _target() -> tuple[str, int]:
    url = os.environ.get("DATABASE_URL", "")
    parsed = urlparse(url)
    host = parsed.hostname or "crypto-postgres"
    port = parsed.port or 5432
    return host, port


def main() -> int:
    host, port = _target()
    deadline = time.monotonic() + 120.0
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=3.0):
                print(f"[wait_for_postgres] {host}:{port} is accepting connections")
                return 0
        except OSError as exc:
            kind = exc.__class__.__name__
            print(f"[wait_for_postgres] {host}:{port} not ready ({kind}); retrying")
            time.sleep(2.0)
    print("[wait_for_postgres] FATAL: PostgreSQL not reachable within 120s", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
