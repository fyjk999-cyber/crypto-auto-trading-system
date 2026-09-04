"""Administrator-reviewed one-shot install. Never enrolls or migrates credentials."""

import argparse
import errno
import grp
import json
import os
import plistlib
import pwd
import shutil
import stat
import subprocess
import sys
import sysconfig
from pathlib import Path

BASE = Path("/Library/Application Support/CryptoOKXBroker")
HOME = Path("/Users/crypto-okx-broker")
USER = "crypto-okx-broker"
GROUP = "crypto-okx-ipc"
ROOT = Path(__file__).resolve().parents[2]
STAGE = "PREFLIGHT_PLATFORM"
COMMAND = "NONE"
DSCL = "/usr/bin/dscl"
DAEMONS = Path("/Library/LaunchDaemons")
SAFE_ERRORS = {
    "MACOS_ADMIN_REQUIRED",
    "MACOS_REQUIRED",
    "NORMAL_CLIENT_REQUIRED",
    "PASSWORDLESS_SUDO_RULES_REQUIRE_ADMIN_REVIEW",
    "EXISTING_INSTALLATION_REQUIRES_ADMIN_REVIEW",
    "EXISTING_GROUP_REFUSED",
    "EXISTING_USER_REFUSED",
    "EXISTING_DAEMON_REFUSED",
    "SYMLINK_REFUSED",
    "UID_GID_RANGE_EXHAUSTED",
    "REQUIRED_TOOL_UNAVAILABLE",
    "RUNTIME_SOURCE_UNAVAILABLE",
    "SHARED_RUNTIME_SYMLINK_REFUSED",
    "INVALID_INSTALLER_ARGUMENTS",
    "HUMAN_TERMINAL_REQUIRED",
    "RESUME_ADMIN_REQUIRED",
    "RESUME_STATE_UNSAFE",
    "RESUME_CREDENTIAL_BUNDLE_PRESENT",
    "RESUME_DAEMON_PRESENT",
}


class InstallerArguments(argparse.ArgumentParser):
    def error(self, message):
        # argparse normally echoes unknown arguments, which may contain secrets.
        raise RuntimeError("INVALID_INSTALLER_ARGUMENTS")


def stage(name):
    global STAGE, COMMAND
    STAGE, COMMAND = name, "NONE"
    print(f"INSTALL_STAGE = {name}", flush=True)


def safe_stderr(value):
    """Project only fixed error categories; never echo arbitrary external text.

    Regex redaction cannot reliably identify unknown future secrets or environment
    dumps. Preserve recognizable diagnostics, discard all surrounding free text.
    """
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    text = (value or "").lower()
    categories = {
        "no such file or directory": "No such file or directory",
        "permission denied": "Permission denied",
        "operation not permitted": "Operation not permitted",
        "a password is required": "Administrator authentication required",
        "not allowed": "Operation not allowed",
        "record was not found": "Directory record not found",
        "file exists": "File exists",
    }
    return next(
        (safe for phrase, safe in categories.items() if phrase in text),
        "External diagnostic omitted (untrusted text)",
    )


def report_error(exc):
    # Neither str(exc), exception args, command args, paths nor environment dump
    # are safe in general. Preserve the real exception class and numeric code.
    code = getattr(exc, "returncode", None)
    if not isinstance(code, int):
        code = getattr(exc, "errno", None)
    detail = "Unclassified exception; details withheld"
    if (
        type(exc) is RuntimeError
        and exc.args
        and isinstance(exc.args[0], str)
        and exc.args[0] in SAFE_ERRORS
    ):
        detail = exc.args[0]
    elif isinstance(exc, OSError) and isinstance(code, int):
        detail = errno.errorcode.get(code, "OS_ERROR") + ": " + os.strerror(code)
    elif isinstance(exc, subprocess.CalledProcessError):
        detail = safe_stderr(exc.stderr)
    elif isinstance(exc, KeyError):
        detail = "Required account or configuration lookup failed"
    elif isinstance(exc, StopIteration):
        detail = "No free identifier found"
    elif isinstance(exc, subprocess.TimeoutExpired):
        detail = "Command timed out"
    print(f"INSTALL_STAGE = {STAGE}")
    print(f"ERROR_TYPE = {type(exc).__name__}")
    print(f"ERROR_COMMAND = {COMMAND}")
    print(f"ERROR_CODE = {code if isinstance(code, int) else 'NONE'}")
    print(f"ERROR_DETAIL = {detail}")
    print("CREDENTIALS_ENROLLED = NO", flush=True)


def run(*argv, interactive=False, **kwargs):
    global COMMAND
    name = Path(argv[0]).name
    COMMAND = (
        name
        if name in {"sudo", "dscl", "dseditgroup", "git", "chmod", "launchctl", "python", "python3"}
        else "UNRECOGNIZED_COMMAND"
    )
    kwargs.setdefault("stdout", None if interactive else subprocess.DEVNULL)
    kwargs.setdefault("stderr", None if interactive else subprocess.PIPE)
    result = subprocess.run(argv, check=True, **kwargs)
    COMMAND = "NONE"
    return result


def output(*argv, **kwargs):
    return run(*argv, stdout=subprocess.PIPE, **kwargs).stdout


def mkdir(path, uid=0, gid=0, mode=0o755):
    if path.is_symlink():
        raise RuntimeError("SYMLINK_REFUSED")
    path.mkdir(parents=True, exist_ok=True)
    os.chown(path, uid, gid)
    path.chmod(mode)


def preflight(only=False):
    stage("PREFLIGHT_PLATFORM")
    if sys.platform != "darwin":
        raise RuntimeError("MACOS_REQUIRED")
    if not only and os.getuid() != 0:
        raise RuntimeError("MACOS_ADMIN_REQUIRED")
    stage("RESOLVE_CLIENT")
    client = (
        pwd.getpwnam(os.environ["SUDO_USER"]) if os.getuid() == 0 else pwd.getpwuid(os.getuid())
    )
    if client.pw_uid == 0:
        raise RuntimeError("NORMAL_CLIENT_REQUIRED")
    stage("AUDIT_SUDOERS")
    audit_complete = os.getuid() == 0
    if audit_complete:
        sudo_rules = output("/usr/bin/sudo", "-l", "-U", client.pw_name)
        if b"NOPASSWD:" in sudo_rules:
            raise RuntimeError("PASSWORDLESS_SUDO_RULES_REQUIRE_ADMIN_REVIEW")
    else:
        print("AUDIT_SUDOERS = DEFERRED_ADMIN_REQUIRED")
    # Refuse updates/overwrites: the administrator must review preservation and
    # uninstall first. Existing vault/home are NEVER adopted, erased or migrated.
    stage("CHECK_EXISTING_INSTALL")
    if BASE.exists() or HOME.exists() or BASE.is_symlink() or HOME.is_symlink():
        raise RuntimeError("EXISTING_INSTALLATION_REQUIRES_ADMIN_REVIEW")
    for label in ("broker", "paper-launcher"):
        target = DAEMONS / f"com.crypto-trader.okx-{label}.plist"
        if target.exists() or target.is_symlink():
            raise RuntimeError("EXISTING_DAEMON_REFUSED")
    stage("ALLOCATE_UID_GID")
    used = {p.pw_uid for p in pwd.getpwall()} | {g.gr_gid for g in grp.getgrall()}
    free = [i for i in range(450, 500) if i not in used]
    if len(free) < 2:
        raise RuntimeError("UID_GID_RANGE_EXHAUSTED")
    uid, gid = free[:2]
    stage("CHECK_NAMES")
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
    stage("CHECK_TOOLS_AND_RUNTIME")
    for tool in (
        DSCL,
        "/usr/sbin/dseditgroup",
        "/usr/bin/sudo",
        "/usr/bin/git",
        "/bin/chmod",
        "/bin/launchctl",
        "/usr/bin/env",
    ):
        if not Path(tool).is_file() or not os.access(tool, os.X_OK):
            global COMMAND
            COMMAND = "dscl" if tool == DSCL else Path(tool).name
            raise FileNotFoundError(errno.ENOENT, "Required tool missing")
    if not Path(sys.base_prefix).is_dir() or not Path(sysconfig.get_paths()["purelib"]).is_dir():
        raise RuntimeError("RUNTIME_SOURCE_UNAVAILABLE")
    output("/usr/bin/git", "-C", str(ROOT), "rev-parse", "--verify", "HEAD")
    plistlib.loads((ROOT / "deploy/macos/com.crypto-trader.okx-broker.plist").read_bytes())
    for asset in ("deploy/macos/verify.py", "src/crypto_trader/okx_vault/enrollment.py"):
        with (ROOT / asset).open("rb"):
            pass
    stage("CHECK_ENROLLMENT_TERMINAL")
    terminal = sys.stdin.isatty() and sys.stdout.isatty()
    if not only and not terminal:
        raise RuntimeError("HUMAN_TERMINAL_REQUIRED")
    if only and not terminal:
        print("INSTALL_TERMINAL = REQUIRED_FOR_KEYCHAIN_INITIALIZATION")
    if only:
        print("PREFLIGHT_RESULT = " + ("PASS" if audit_complete else "ADMIN_AUDIT_REQUIRED"))
        print("SYSTEM_MUTATIONS = ZERO")
        print("CREDENTIALS_ENROLLED = NO")
    return client, uid, gid, audit_complete


def main(argv=None):
    parser = InstallerArguments()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--preflight", action="store_true")
    mode.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    if args.resume:
        return resume()
    client, uid, gid, audit_complete = preflight(args.preflight)
    if args.preflight:
        return 0 if audit_complete else 2
    for name, number in ((USER, uid), (GROUP, gid)):
        stage("CREATE_BROKER_GROUP" if name == USER else "CREATE_IPC_GROUP")
        run(DSCL, ".", "-create", f"/Groups/{name}")
        run(DSCL, ".", "-create", f"/Groups/{name}", "PrimaryGroupID", str(number))
    stage("CREATE_BROKER_USER")
    record = f"/Users/{USER}"
    run(DSCL, ".", "-create", record)
    for key, value in {
        "UniqueID": str(uid),
        "PrimaryGroupID": str(uid),
        "NFSHomeDirectory": str(HOME),
        "UserShell": "/usr/bin/false",
        "IsHidden": "1",
        "Password": "*",
        "AuthenticationAuthority": ";DisabledUser;",
    }.items():
        run(DSCL, ".", "-create", record, key, value)
    stage("ADD_GROUP_MEMBERS")
    for member in (USER, client.pw_name):
        run("/usr/sbin/dseditgroup", "-o", "edit", "-a", member, "-t", "user", GROUP)
    stage("CREATE_HOME")
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
    stage("CREATE_PROTECTED_RUNTIME")
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
    files = output(
        "/usr/bin/git",
        "-C",
        str(ROOT),
        "ls-tree",
        "-rz",
        "--name-only",
        "HEAD",
        "src/crypto_trader",
    ).split(b"\0")
    for raw in filter(None, files):
        rel = Path(os.fsdecode(raw))
        target = site / rel.relative_to("src")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(output("/usr/bin/git", "-C", str(ROOT), "show", "HEAD:" + str(rel)))
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
        "source_sha": output(
            "/usr/bin/git", "-C", str(ROOT), "rev-parse", "HEAD", text=True
        ).strip(),
    }
    (BASE / "policy.json").write_text(json.dumps(policy))
    (BASE / "policy.json").chmod(0o644)
    shutil.copyfile(ROOT / "deploy/macos/verify.py", BASE / "verify.py")
    (BASE / "verify.py").chmod(0o644)
    # All descendants start with no inherited ACL grants.
    run("/bin/chmod", "-RN", str(BASE), str(HOME))
    return complete_install(client, policy, paper, python)


def complete_install(client, policy, paper, python):
    """Only runs after either fresh install or validated credential-free resume."""
    stage("INITIALIZE_KEYCHAIN")
    run(
        str(python),
        "-I",
        "-m",
        "crypto_trader.okx_vault.enrollment",
        "initialize",
        interactive=True,
    )
    stage("INSTALL_LAUNCHDAEMONS")
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
        target = DAEMONS / (label + ".plist")
        if target.exists():
            raise RuntimeError("EXISTING_DAEMON_REFUSED")
        target.write_bytes(plistlib.dumps(plist))
        target.chmod(0o644)
        run("/bin/launchctl", "bootstrap", "system", str(target))
    # Retire only the obsolete same-user service, retaining ALL old vault data.
    stage("RETIRE_LEGACY_SERVICE")
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
    stage("PRE_ENROLLMENT_VERIFY")
    run(
        str(python),
        "-I",
        str(BASE / "verify.py"),
        user=client.pw_uid,
        group=client.pw_gid,
        extra_groups=policy["client_groups"],
        env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
        interactive=True,
    )
    print("INSTALL_RESULT = PASS")
    print("CREDENTIALS_ENROLLED = NO")
    return 0


def root_mode(path, *, uid=0, mode=None):
    if path.is_symlink() or not path.exists():
        return False
    info = path.stat()
    return info.st_uid == uid and (mode is None or stat.S_IMODE(info.st_mode) == mode)


def resume_context():
    """Validate only the known credential-free partial state; never repair it blindly."""
    stage("RESUME_PREFLIGHT")
    if sys.platform != "darwin" or os.getuid() != 0:
        raise RuntimeError("RESUME_ADMIN_REQUIRED")
    client = pwd.getpwnam(os.environ["SUDO_USER"])
    if client.pw_uid == 0:
        raise RuntimeError("NORMAL_CLIENT_REQUIRED")
    sudo_rules = output("/usr/bin/sudo", "-l", "-U", client.pw_name)
    if b"NOPASSWD:" in sudo_rules:
        raise RuntimeError("PASSWORDLESS_SUDO_RULES_REQUIRE_ADMIN_REVIEW")
    stage("RESUME_VALIDATE_PARTIAL_STATE")
    if not root_mode(BASE, mode=0o755) or not root_mode(BASE / "runtime", mode=0o755):
        raise RuntimeError("RESUME_STATE_UNSAFE")
    policy_path = BASE / "policy.json"
    if not root_mode(policy_path, mode=0o644):
        raise RuntimeError("RESUME_STATE_UNSAFE")
    policy = json.loads(policy_path.read_text())
    required = {
        "broker_uid",
        "broker_gid",
        "ipc_gid",
        "client_uid",
        "client_gid",
        "client_groups",
        "paper_home",
    }
    if not required <= policy.keys() or policy["client_uid"] != client.pw_uid:
        raise RuntimeError("RESUME_STATE_UNSAFE")
    try:
        broker = pwd.getpwnam(USER)
        broker_group = grp.getgrnam(USER)
        ipc_group = grp.getgrnam(GROUP)
    except KeyError:
        raise RuntimeError("RESUME_STATE_UNSAFE") from None
    if (broker.pw_uid, broker.pw_gid, broker_group.gr_gid, ipc_group.gr_gid) != (
        policy["broker_uid"],
        policy["broker_gid"],
        policy["broker_gid"],
        policy["ipc_gid"],
    ):
        raise RuntimeError("RESUME_STATE_UNSAFE")
    if not root_mode(HOME, uid=broker.pw_uid, mode=0o700):
        raise RuntimeError("RESUME_STATE_UNSAFE")
    vault = HOME / ".crypto-okx/vault"
    if not root_mode(vault, uid=broker.pw_uid, mode=0o700):
        raise RuntimeError("RESUME_STATE_UNSAFE")
    if (vault / "okx-paper-credentials.enc").exists():
        raise RuntimeError("RESUME_CREDENTIAL_BUNDLE_PRESENT")
    keychain = HOME / "Library/Keychains/okx-broker.keychain-db"
    if keychain.exists() and not root_mode(keychain, uid=broker.pw_uid, mode=0o600):
        raise RuntimeError("RESUME_STATE_UNSAFE")
    paper = Path(policy["paper_home"])
    if paper != BASE / "paper-state" or paper.is_symlink() or not paper.exists():
        raise RuntimeError("RESUME_STATE_UNSAFE")
    if paper.stat().st_uid != client.pw_uid or stat.S_IMODE(paper.stat().st_mode) != 0o700:
        raise RuntimeError("RESUME_STATE_UNSAFE")
    for label in ("broker", "paper-launcher"):
        if (DAEMONS / f"com.crypto-trader.okx-{label}.plist").exists():
            raise RuntimeError("RESUME_DAEMON_PRESENT")
    for socket_path in (BASE / "ipc/broker/broker.sock", BASE / "ipc/paper/paper.sock"):
        if socket_path.exists() or socket_path.is_symlink():
            raise RuntimeError("RESUME_STATE_UNSAFE")
    return client, policy


def refresh_resume_assets(python):
    """Refresh only root-owned broker modules from committed Git, never worktree files."""
    stage("RESUME_REFRESH_PROTECTED_CODE")
    site = (
        BASE
        / "runtime/lib"
        / f"python{sys.version_info.major}.{sys.version_info.minor}"
        / "site-packages"
    )
    if not root_mode(site, mode=0o755):
        raise RuntimeError("RESUME_STATE_UNSAFE")
    files = output(
        "/usr/bin/git",
        "-C",
        str(ROOT),
        "ls-tree",
        "-rz",
        "--name-only",
        "HEAD",
        "src/crypto_trader/okx_vault",
    ).split(b"\0")
    if not files:
        raise RuntimeError("RUNTIME_SOURCE_UNAVAILABLE")
    for raw in filter(None, files):
        rel = Path(os.fsdecode(raw))
        target = site / rel.relative_to("src")
        if target.exists() and (target.is_symlink() or target.stat().st_uid != 0):
            raise RuntimeError("RESUME_STATE_UNSAFE")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(output("/usr/bin/git", "-C", str(ROOT), "show", "HEAD:" + str(rel)))
        os.chown(target, 0, 0)
        target.chmod(0o644)
    verify = BASE / "verify.py"
    if verify.is_symlink() or verify.stat().st_uid != 0:
        raise RuntimeError("RESUME_STATE_UNSAFE")
    verify.write_bytes(
        output("/usr/bin/git", "-C", str(ROOT), "show", "HEAD:deploy/macos/verify.py")
    )
    verify.chmod(0o644)
    run(str(python), "-I", "-c", "import crypto_trader.okx_vault.enrollment")


def resume():
    client, policy = resume_context()
    python = BASE / "runtime/bin/python3"
    if not root_mode(python, mode=0o755):
        raise RuntimeError("RESUME_STATE_UNSAFE")
    refresh_resume_assets(python)
    policy["source_sha"] = output(
        "/usr/bin/git", "-C", str(ROOT), "rev-parse", "HEAD", text=True
    ).strip()
    (BASE / "policy.json").write_text(json.dumps(policy))
    (BASE / "policy.json").chmod(0o644)
    return complete_install(client, policy, Path(policy["paper_home"]), python)


def entry(argv=None):
    try:
        return main(argv)
    except Exception as exc:
        report_error(exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(entry())
