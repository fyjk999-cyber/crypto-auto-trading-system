"""Root-approved hidden terminal enrollment; privilege drop before secret input."""

import getpass
import os
import resource
import subprocess
import sys

from ._storage import BUNDLE, FIELDS, _KeychainKey, _Vault
from .cli import _human_terminal
from .isolation import BASE, HOME, KEYCHAIN, RUNTIME, USER, VAULT, protected_policy


def main():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.umask(0o077)
    if os.getuid() != 0 or sys.argv[1:] not in (["save"], ["delete"], ["initialize"], ["unlock"]):
        raise PermissionError
    command = sys.argv[1]
    policy = protected_policy()
    _human_terminal()
    if command != "initialize":
        subprocess.run(
            [str(RUNTIME / "bin/python3"), "-I", str(BASE / "verify.py")],
            user=policy["client_uid"],
            group=policy["client_gid"],
            extra_groups=policy["client_groups"],
            env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
            check=True,
        )
    os.setgroups([policy["ipc_gid"]])
    os.setgid(policy["broker_gid"])
    os.setuid(policy["broker_uid"])
    os.environ.clear()
    os.environ.update(HOME=str(HOME), USER=USER, PATH="/usr/bin:/bin:/usr/sbin:/sbin")
    os.chdir(HOME)
    password = getpass.getpass("Private Broker Keychain password (12+ characters): ").encode()
    try:
        if (
            command == "initialize"
            and getpass.getpass("Confirm Keychain password: ").encode() != password
        ):
            raise PermissionError
        keys = _KeychainKey(KEYCHAIN, create_keychain=command == "initialize", password=password)
    finally:
        del password
    if command in {"initialize", "unlock"}:
        return  # Empty private Keychain only. No AES key or OKX credential yet.
    vault = _Vault(VAULT / (BUNDLE + ".enc"), keys)
    if command == "delete":
        if input("Type DELETE to remove the bundle: ") == "DELETE":
            vault._delete()
            print("Credential bundle deleted.")
        return
    values = {}
    try:
        for name in FIELDS:
            values[name] = getpass.getpass(name + ": ")
        vault._save(values)
    finally:
        values.clear()
    print("Encrypted OKX bundle saved. No credential values returned.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit("PROTECTED_ENROLLMENT_FAILED") from None
