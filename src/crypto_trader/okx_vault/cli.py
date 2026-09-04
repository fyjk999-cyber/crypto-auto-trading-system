"""Unprivileged operations client. Enrollment exists only in protected deployment."""

import argparse
import asyncio
import json
import sys

from ._storage import VaultError
from .client import BrokerClient


def _human_terminal():
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise VaultError("HUMAN_TERMINAL_REQUIRED")


def main():
    parser = argparse.ArgumentParser(description="Opaque OKX PAPER credential bundle")
    parser.add_argument("command", choices=["save", "verify", "run", "delete"])
    args = parser.parse_args()
    if args.command in {"save", "delete"}:
        raise SystemExit("ADMIN_PROTECTED_ENROLLMENT_REQUIRED; see docs/OKX_BROKER_ISOLATION.md")
    client = BrokerClient()
    result = asyncio.run(client.run_paper() if args.command == "run" else client.verify())
    print(json.dumps(result))
    if not result.get("ok"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
