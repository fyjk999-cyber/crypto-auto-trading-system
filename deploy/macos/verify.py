"""Actual normal-UID OS probes. Never read/print secrets, even on unexpected access.

Default is pre-enrollment isolation; --operations adds real credential/DEMO/PAPER
checks AFTER enrollment. Missing credentials are not evidence of access denial.
"""

import ctypes
import json
import os
import plistlib
import socket
import subprocess
import sys
import time
from pathlib import Path

BASE = Path("/Library/Application Support/CryptoOKXBroker")
HOME = Path("/Users/crypto-okx-broker")
SOCKET = BASE / "ipc/broker/broker.sock"
RESULTS = {}


def record(name, passed):
    RESULTS[name] = bool(passed)
    print(f"{name} = {'PASS' if passed else 'FAIL'}", flush=True)


def denied_open(path, flags):
    try:
        fd = os.open(path, flags | os.O_NOFOLLOW)
    except PermissionError:
        return True
    except OSError:
        return False  # ENOENT is NOT permission evidence.
    os.close(fd)  # Deliberately do NOT read, write or truncate, even if accessible.
    return False


def denied_command(argv):
    try:
        return (
            subprocess.run(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
            ).returncode
            != 0
        )
    except (OSError, subprocess.TimeoutExpired):
        return False  # Unsupported or timed-out probes are NOT a PASS.


def rpc(operation, **fields):
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(55)
        connection.connect(str(SOCKET))
        connection.sendall(json.dumps({"operation": operation, **fields}).encode() + b"\n")
        return json.loads(connection.makefile("rb").readline(1_000_000))


def process_debug_denied(pid):
    # task_for_pid is the Mach capability required to inspect process memory.
    # Do not attach a debugger or read memory even if the capability is granted.
    lib = ctypes.CDLL(None)
    task = ctypes.c_uint.in_dll(lib, "mach_task_self_").value
    port = ctypes.c_uint()
    result = lib.task_for_pid(task, pid, ctypes.byref(port))
    if result == 0:
        lib.mach_port_deallocate(task, port)
    return result != 0


def main():
    if sys.platform != "darwin" or os.getuid() == 0 or not (BASE / "policy.json").is_file():
        print("OS_LEVEL_UNREADABILITY = NOT_INSTALLED_OR_WRONG_UID")
        return 1
    policy = json.loads((BASE / "policy.json").read_text())
    record("HARNESS_UID_MATCH", os.getuid() == policy["client_uid"])
    record("BROKER_DISTINCT_UID", os.getuid() != policy["broker_uid"])
    record("ADMIN_SUDOERS_AUDIT", policy.get("admin_sudoers_audit_no_nopasswd") is True)
    record(
        "HARNESS_READ_VAULT", denied_open(HOME / ".crypto-okx/vault/.permission-probe", os.O_RDONLY)
    )
    try:
        with os.scandir(HOME / ".crypto-okx/vault"):
            denied = False
    except PermissionError:
        denied = True
    record("HARNESS_LIST_PRIVATE_VAULT", denied)
    keychain = HOME / "Library/Keychains/okx-broker.keychain-db"
    record("HARNESS_READ_KEYCHAIN", denied_open(keychain, os.O_RDONLY))
    record(
        "SECURITY_TOOL_KEYCHAIN_ACCESS",
        denied_command(["/usr/bin/security", "show-keychain-info", str(keychain)]),
    )
    record(
        "SECURITY_TOOL_AES_READ",
        denied_command(
            [
                "/usr/bin/security",
                "find-generic-password",
                "-s",
                "crypto-auto-trading-system",
                "-a",
                "okx-paper-credentials-aes256-key",
                "-w",
                str(keychain),
            ]
        ),
    )
    for name, path in {
        "HARNESS_MODIFY_BROKER": BASE / "runtime/bin/python3",
        "HARNESS_MODIFY_POLICY": BASE / "policy.json",
        "HARNESS_MODIFY_DAEMON": Path("/Library/LaunchDaemons/com.crypto-trader.okx-broker.plist"),
    }.items():
        record(name, denied_open(path, os.O_WRONLY))
    runtime_safe = True
    for path in [BASE, BASE / "runtime", *(BASE / "runtime").rglob("*")]:
        info = path.lstat()
        if (
            path.is_symlink()
            or info.st_uid != 0
            or info.st_mode & 0o022
            or os.access(path, os.W_OK)
        ):
            runtime_safe = False
    record("NO_SHARED_WRITABLE_RUNTIME", runtime_safe)
    from crypto_trader.okx_vault.isolation import frozen_libraries

    record("NO_SHARED_NATIVE_LIBRARIES", frozen_libraries())
    acl = subprocess.run(
        ["/bin/ls", "-lde", str(BASE), str(BASE / "runtime"), str(BASE / "ipc/broker")],
        capture_output=True,
        text=True,
        check=True,
    )
    record("NO_ACL_GRANTS", not any(" allow " in line for line in acl.stdout.splitlines()))
    record(
        "PROTECTED_SOCKET_DIRECTORY",
        not os.access(SOCKET.parent, os.W_OK)
        and SOCKET.parent.stat().st_uid == policy["broker_uid"],
    )
    # Revoke this authentication context's cached ticket before asserting that
    # agents cannot reuse the installer's authorization for a different command.
    subprocess.run(
        ["/usr/bin/sudo", "-k"],
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    record(
        "CACHED_ROOT_ACCESS_DENIED", denied_command(["/usr/bin/sudo", "-n", "/usr/bin/id", "-u"])
    )
    # -k forces password authentication rather than using the user's cached sudo
    # ticket. A broad NOPASSWD listing is a failure, not an invitation to use root.
    record(
        "PASSWORDLESS_ROOT_DENIED",
        denied_command(["/usr/bin/sudo", "-n", "-k", "/usr/bin/id", "-u"]),
    )
    record(
        "PASSWORDLESS_BROKER_DENIED",
        denied_command(
            ["/usr/bin/sudo", "-n", "-k", "-u", "crypto-okx-broker", "/usr/bin/id", "-u"]
        ),
    )
    sudo_rules = subprocess.run(
        ["/usr/bin/sudo", "-n", "-k", "-l"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=10,
    )
    record(
        "NO_PASSWORDLESS_SUDO_RULES",
        sudo_rules.returncode != 0 or b"NOPASSWD:" not in sudo_rules.stdout,
    )
    record(
        "SU_BROKER_DENIED",
        denied_command(["/usr/bin/su", "crypto-okx-broker", "-c", "/usr/bin/id"]),
    )
    record(
        "LAUNCHCTL_CONTROL_DENIED",
        denied_command(["/bin/launchctl", "kickstart", "system/com.crypto-trader.okx-broker"]),
    )
    for name in ("save", "delete", "export", "decrypt", "shell", "exec", "read"):
        record("RPC_" + name.upper() + "_DENIED", rpc(name).get("error") == "OPERATION_DENIED")
    python = str(BASE / "runtime/bin/python3")
    for action in ("save", "delete", "export"):
        record(
            "DIRECT_" + action.upper() + "_DENIED",
            denied_command([python, "-I", "-m", "crypto_trader.okx_vault.enrollment", action]),
        )
    state = rpc("credential_status")
    record(
        "VAULT_OWNER_AND_MODE",
        state.get("vault_owner_uid") == policy["broker_uid"]
        and state.get("vault_directory_mode") == 0o700,
    )
    print("BROKER_USER = crypto-okx-broker")
    print(f"BROKER_PROCESS_UID = {state.get('uid')}")
    print(f"HARNESS_UID = {os.getuid()}")
    pid = state.get("pid")
    record(
        "BROKER_PROCESS_UID",
        type(pid) is int
        and state.get("uid") == policy["broker_uid"]
        and subprocess.check_output(["/bin/ps", "-p", str(pid), "-o", "uid="], text=True).strip()
        == str(policy["broker_uid"]),
    )
    record("HARNESS_DEBUG_BROKER", type(pid) is int and process_debug_denied(pid))
    # Output is captured, never printed. Broker has no secret environment values.
    proc = subprocess.check_output(["/bin/ps", "eww", "-p", str(pid), "-o", "command="])
    record(
        "NO_SECRET_ENVIRONMENT",
        all(
            name not in proc
            for name in (
                b"OKX_API_KEY=",
                b"OKX_API_SECRET=",
                b"OKX_API_PASSPHRASE=",
                b"DEEPSEEK_API_KEY=",
            )
        ),
    )
    plist = plistlib.loads(
        Path("/Library/LaunchDaemons/com.crypto-trader.okx-broker.plist").read_bytes()
    )
    record(
        "PAPER_ONLY_CONFIGURATION",
        plist["EnvironmentVariables"].get("OKX_DEMO") == "true"
        and plist["EnvironmentVariables"].get("LIVE_TRADING_ENABLED") == "false"
        and plist["EnvironmentVariables"].get("TRADING_MODE") == "PAPER",
    )
    record("IPC_CONFIGURED_ALLOWED", type(rpc("configured").get("configured")) is bool)
    record("IPC_STATUS_ALLOWED", state.get("secret_return_supported") is False)
    if "--operations" in sys.argv:
        record("IPC_VERIFY_ALLOWED", rpc("verify").get("ok") is True)
        record("IPC_DEMO_READ_ALLOWED", rpc("validate_okx_demo").get("authenticated") is True)
        record(
            "IPC_SIGNED_REQUEST_ALLOWED",
            rpc("signed_request", method="GET", path="/api/v5/account/config").get("ok") is True,
        )
        record("IPC_RUN_PAPER_ALLOWED", rpc("run_paper").get("ok") is True)
    else:
        # Endpoint reachability is not credential validation or runtime acceptance.
        record("IPC_VERIFY_REACHABLE", "ok" in rpc("verify"))
        print("DEMO_AUTH_AND_PAPER_LAUNCH = NOT_VERIFIED_PRE_ENROLLMENT")
    passed = all(RESULTS.values())
    print("OS_LEVEL_UNREADABILITY = " + ("PASS" if passed else "FAIL"))
    return 0 if passed else 1


if __name__ == "__main__":
    try:
        # Launchd startup is asynchronous; bounded wait does not enroll anything.
        for _ in range(20):
            if SOCKET.exists():
                break
            time.sleep(0.25)
        raise SystemExit(main())
    except Exception:
        print("OS_LEVEL_UNREADABILITY = NOT_VERIFIED")
        raise SystemExit(1) from None
