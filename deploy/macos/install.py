"""Administrator-reviewed one-shot install. Never enrolls or migrates credentials."""

import grp
import json
import os
import plistlib
import pwd
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

BASE = Path("/Library/Application Support/CryptoOKXBroker")
HOME = Path("/Users/crypto-okx-broker")
USER = "crypto-okx-broker"
GROUP = "crypto-okx-ipc"
ROOT = Path(__file__).resolve().parents[2]


def run(*argv, **kwargs):
    return subprocess.run(argv, check=True, **kwargs)


def mkdir(path, uid=0, gid=0, mode=0o755):
    if path.is_symlink():
        raise RuntimeError("SYMLINK_REFUSED")
    path.mkdir(parents=True, exist_ok=True)
    os.chown(path, uid, gid)
    path.chmod(mode)


def main():
    if sys.platform != "darwin" or os.getuid() != 0:
        raise RuntimeError("MACOS_ADMIN_REQUIRED")
    client = pwd.getpwnam(os.environ["SUDO_USER"])
    if client.pw_uid == 0:
        raise RuntimeError("NORMAL_CLIENT_REQUIRED")
    sudo_rules = subprocess.check_output(
        ["/usr/bin/sudo", "-l", "-U", client.pw_name], stderr=subprocess.DEVNULL
    )
    if b"NOPASSWD:" in sudo_rules:
        raise RuntimeError("PASSWORDLESS_SUDO_RULES_REQUIRE_ADMIN_REVIEW")
    # Refuse updates/overwrites: the administrator must review preservation and
    # uninstall first. Existing vault/home are NEVER adopted, erased or migrated.
    if BASE.exists() or HOME.exists():
        raise RuntimeError("EXISTING_INSTALLATION_REQUIRES_ADMIN_REVIEW")
    used = {p.pw_uid for p in pwd.getpwall()} | {g.gr_gid for g in grp.getgrall()}
    uid = next(i for i in range(450, 500) if i not in used)
    for name in (USER, GROUP):
        try:
            grp.getgrnam(name)
        except KeyError:
            pass
        else:
            raise RuntimeError("EXISTING_GROUP_REFUSED")
    try:
        pwd.getpwnam(USER)
    except KeyError:
        pass
    else:
        raise RuntimeError("EXISTING_USER_REFUSED")
    gid = next(i for i in range(uid + 1, 500) if i not in used)
    for name, number in ((USER, uid), (GROUP, gid)):
        run("/usr/sbin/dscl", ".", "-create", f"/Groups/{name}")
        run("/usr/sbin/dscl", ".", "-create", f"/Groups/{name}", "PrimaryGroupID", str(number))
    record = f"/Users/{USER}"
    run("/usr/sbin/dscl", ".", "-create", record)
    for key, value in {
        "UniqueID": str(uid),
        "PrimaryGroupID": str(uid),
        "NFSHomeDirectory": str(HOME),
        "UserShell": "/usr/bin/false",
        "IsHidden": "1",
        "Password": "*",
        "AuthenticationAuthority": ";DisabledUser;",
    }.items():
        run("/usr/sbin/dscl", ".", "-create", record, key, value)
    for member in (USER, client.pw_name):
        run("/usr/sbin/dseditgroup", "-o", "edit", "-a", member, "-t", "user", GROUP)
    mkdir(HOME, uid, uid, 0o700)
    for rel in (
        ".crypto-okx",
        ".crypto-okx/vault",
        ".crypto-okx/logs",
        "Library",
        "Library/Keychains",
    ):
        mkdir(HOME / rel, uid, uid, 0o700)
    # Non-secret probe proves EACCES before any real bundle exists.
    probe = HOME / ".crypto-okx/vault/.permission-probe"
    probe.write_bytes(b"OS access test; not a credential")
    os.chown(probe, uid, uid)
    probe.chmod(0o600)
    mkdir(BASE)
    runtime = BASE / "runtime"
    # Copy the standalone interpreter AND dependency tree; no user-owned uv or
    # editable venv symlinks remain. Do not execute a project interpreter at runtime.
    shutil.copytree(Path(sys.base_prefix), runtime, symlinks=False)
    site = (
        runtime
        / "lib"
        / f"python{sys.version_info.major}.{sys.version_info.minor}"
        / "site-packages"
    )
    shutil.copytree(
        Path(sysconfig.get_paths()["purelib"]),
        site,
        dirs_exist_ok=True,
        symlinks=False,
        ignore=shutil.ignore_patterns("*.pth", "__editable*"),
    )
    # Committed source only. Dirty project runtime/market work is not deployed.
    files = subprocess.check_output(
        [
            "/usr/bin/git",
            "-C",
            str(ROOT),
            "ls-tree",
            "-rz",
            "--name-only",
            "HEAD",
            "src/crypto_trader",
        ]
    ).split(b"\0")
    for raw in filter(None, files):
        rel = Path(os.fsdecode(raw))
        target = site / rel.relative_to("src")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(
            subprocess.check_output(["/usr/bin/git", "-C", str(ROOT), "show", "HEAD:" + str(rel)])
        )
    for path in runtime.rglob("*"):
        if path.is_symlink():
            raise RuntimeError("SHARED_RUNTIME_SYMLINK_REFUSED")
        os.chown(path, 0, 0)
        path.chmod(0o755 if path.is_dir() or path.stat().st_mode & 0o111 else 0o644)
    # Drop copied site startup hooks even if bundled by base interpreter.
    for pattern in ("*.pth", "sitecustomize.py", "usercustomize.py"):
        for hook in site.glob(pattern):
            hook.unlink()
    python = runtime / "bin/python3"
    run(str(python), "-I", "-c", "import ssl,cryptography,httpx,crypto_trader.okx_vault.service")
    run(
        str(python),
        "-I",
        "-c",
        "from crypto_trader.okx_vault.isolation import frozen_libraries; assert frozen_libraries()",
    )
    paper = BASE / "paper-state"
    mkdir(paper, client.pw_uid, client.pw_gid, 0o700)
    mkdir(paper / ".venv/bin", client.pw_uid, client.pw_gid)
    (paper / ".venv/bin/python").symlink_to(python)
    for rel, owner in (("ipc", 0), ("ipc/broker", uid), ("ipc/paper", client.pw_uid)):
        mkdir(BASE / rel, owner, gid)
    policy = {
        "broker_uid": uid,
        "broker_gid": uid,
        "ipc_gid": gid,
        "client_uid": client.pw_uid,
        "client_gid": client.pw_gid,
        "client_groups": sorted(set(os.getgrouplist(client.pw_name, client.pw_gid) + [gid])),
        "paper_home": str(paper),
        "admin_sudoers_audit_no_nopasswd": True,
        "source_sha": subprocess.check_output(
            ["/usr/bin/git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True
        ).strip(),
    }
    (BASE / "policy.json").write_text(json.dumps(policy))
    (BASE / "policy.json").chmod(0o644)
    shutil.copyfile(ROOT / "deploy/macos/verify.py", BASE / "verify.py")
    (BASE / "verify.py").chmod(0o644)
    # All descendants start with no inherited ACL grants.
    run("/bin/chmod", "-RN", str(BASE), str(HOME))
    run(str(python), "-I", "-m", "crypto_trader.okx_vault.enrollment", "initialize")
    template = plistlib.loads(
        (ROOT / "deploy/macos/com.crypto-trader.okx-broker.plist").read_bytes()
    )
    for role in ("broker", "paper-launcher"):
        plist = dict(template)
        label = f"com.crypto-trader.okx-{role}"
        plist["Label"] = label
        plist["UserName"] = USER if role == "broker" else client.pw_name
        plist["GroupName"] = GROUP
        plist["WorkingDirectory"] = str(HOME if role == "broker" else paper)
        program = [
            str(python),
            "-I",
            "-m",
            "crypto_trader.okx_vault." + ("service" if role == "broker" else "paper_launcher"),
        ]
        plist["EnvironmentVariables"] = {
            "HOME": plist["WorkingDirectory"],
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "OKX_DEMO": "true",
            "TRADING_MODE": "PAPER",
            "PAPER_MODE": "PAPER_REAL_MARKET",
            "LIVE_TRADING_ENABLED": "false",
            "RUNNING_SHA": policy["source_sha"],
            "GIT_SHA": policy["source_sha"],
        }
        plist["ProgramArguments"] = (
            ["/usr/bin/env", "-i"]
            + [name + "=" + value for name, value in plist["EnvironmentVariables"].items()]
            + program
        )
        target = Path("/Library/LaunchDaemons") / (label + ".plist")
        if target.exists():
            raise RuntimeError("EXISTING_DAEMON_REFUSED")
        target.write_bytes(plistlib.dumps(plist))
        target.chmod(0o644)
        run("/bin/launchctl", "bootstrap", "system", str(target))
    # Retire only the obsolete same-user service, retaining ALL old vault data.
    subprocess.run(
        [
            "/bin/launchctl",
            "bootout",
            f"gui/{client.pw_uid}/com.crypto-trader.okx-credential-broker",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    old = Path(client.pw_dir) / "Library/LaunchAgents/com.crypto-trader.okx-credential-broker.plist"
    if old.is_file() and not old.is_symlink():
        old.rename(old.with_suffix(".plist.disabled"))
    print("Installed without credentials. Running actual pre-enrollment OS verification.")
    run(
        str(python),
        "-I",
        str(BASE / "verify.py"),
        user=client.pw_uid,
        group=client.pw_gid,
        extra_groups=policy["client_groups"],
        env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit(
            "INSTALL_INCOMPLETE: no credentials enrolled; preserve files for review"
        ) from None
