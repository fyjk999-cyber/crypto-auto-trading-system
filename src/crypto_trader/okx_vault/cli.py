"""Human terminal enrollment and operations-only agent commands."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import plistlib
import subprocess
import sys

from ._storage import BUNDLE, FIELDS, VaultError, _KeychainKey, _Vault, private_directory
from .client import BrokerClient
from .service import DIRECTORY, ROOT


def _human_terminal():
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise VaultError("HUMAN_TERMINAL_REQUIRED")
    # A TTY is an input safeguard, not authentication against same-UID agents.


def _install_service():
    if sys.platform != "darwin":
        raise VaultError("MACOS_KEYCHAIN_REQUIRED")
    private_directory(DIRECTORY)
    label = "com.crypto-trader.okx-credential-broker"
    target = f"gui/{os.getuid()}/{label}"
    from pathlib import Path

    plist = Path.home() / "Library/LaunchAgents" / (label + ".plist")
    content = {
        "Label": label,
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 15,
        "WorkingDirectory": str(ROOT),
        "ProgramArguments": [
            str(ROOT / ".venv/bin/python"),
            "-m",
            "crypto_trader.okx_vault.service",
        ],
        "StandardOutPath": "/dev/null",
        "StandardErrorPath": "/dev/null",
    }
    if plist.exists() and plistlib.loads(plist.read_bytes()).get("WorkingDirectory") != str(ROOT):
        raise VaultError("BROKER_BELONGS_TO_OTHER_CHECKOUT")
    plist.parent.mkdir(parents=True, exist_ok=True)
    plist.write_bytes(plistlib.dumps(content))
    plist.chmod(0o600)
    if subprocess.run(["launchctl", "print", target], capture_output=True).returncode:
        subprocess.run(
            ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(plist)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )


async def _operation(command):
    client = BrokerClient()
    for _ in range(20):
        status = await client.credential_status()
        if status.get("error") != "BROKER_UNAVAILABLE":
            break
        await asyncio.sleep(0.25)
    return await (client.run_paper() if command == "run" else client.verify())


def main():
    parser = argparse.ArgumentParser(description="Opaque OKX PAPER credential bundle")
    parser.add_argument("command", choices=["save", "verify", "run", "delete"])
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.command in {"save", "delete"}:
            _human_terminal()
            vault = _Vault(DIRECTORY / (BUNDLE + ".enc"), _KeychainKey())
            if args.command == "delete":
                if (
                    input("Type DELETE to remove the OKX bundle (running requests may finish): ")
                    != "DELETE"
                ):
                    raise VaultError("DELETE_CANCELLED")
                vault._delete()
                print("OKX bundle deleted. Running PAPER processes must be stopped separately.")
                return
            values = {}
            try:
                for name in FIELDS:
                    values[name] = getpass.getpass(name + ": ")
                vault._save(values)
            finally:
                values.clear()
            print("OKX encrypted bundle saved; AES key is stored in macOS Keychain.")
            _install_service()
            return
        _install_service()
        result = asyncio.run(_operation(args.command))
        print(json.dumps(result))
        if not result.get("ok"):
            raise SystemExit(1)
    except (VaultError, OSError, subprocess.SubprocessError, EOFError):
        raise SystemExit(
            "OKX_VAULT_OPERATION_FAILED: check Keychain access and local setup."
        ) from None


if __name__ == "__main__":
    main()
