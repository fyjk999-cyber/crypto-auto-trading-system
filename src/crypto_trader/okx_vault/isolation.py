"""Fixed macOS deployment contract. No environment-controlled security policy."""

import ctypes
import json
import os
import pwd
import stat
from pathlib import Path

USER = "crypto-okx-broker"
HOME = Path("/Users/crypto-okx-broker")
BASE = Path("/Library/Application Support/CryptoOKXBroker")
RUNTIME = BASE / "runtime"
CONFIG = BASE / "policy.json"
VAULT = HOME / ".crypto-okx/vault"
KEYCHAIN = HOME / "Library/Keychains/okx-broker.keychain-db"
IPC = BASE / "ipc"
SOCKET = IPC / "broker/broker.sock"
PAPER_SOCKET = IPC / "paper/paper.sock"


def protected_policy():
    """Trust root-owned policy only, including every parent; reject symlinks/ACLs."""
    for path in (CONFIG, *CONFIG.parents):
        info = path.lstat()
        if path.is_symlink() or info.st_uid != 0 or info.st_mode & 0o022:
            raise PermissionError("UNPROTECTED_POLICY")
    policy = json.loads(CONFIG.read_text())
    if policy["broker_uid"] != pwd.getpwnam(USER).pw_uid:
        raise PermissionError("IDENTITY_CHANGED")
    return policy


def broker_identity():
    policy = protected_policy()
    if os.getuid() != policy["broker_uid"] or os.getuid() == policy["client_uid"]:
        raise PermissionError("BROKER_IDENTITY_REQUIRED")
    return policy


def peer_uid(sock):
    """Kernel-authenticated peer identity, never a UID claimed in JSON."""
    libc = ctypes.CDLL(None, use_errno=True)
    uid, gid = ctypes.c_uint(), ctypes.c_uint()
    if libc.getpeereid(sock.fileno(), ctypes.byref(uid), ctypes.byref(gid)) != 0:
        raise PermissionError("PEER_IDENTITY_UNAVAILABLE")
    return uid.value


def private_home():
    info = HOME.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise PermissionError("PRIVATE_HOME_REQUIRED")


def frozen_libraries():
    """Check loaded native dependencies too, not just the Python executable."""
    import importlib

    for module in (
        "cryptography.hazmat.bindings._rust",
        "psycopg2",
        "pydantic_core",
        "ssl",
        "uvloop",
    ):
        importlib.import_module(module)

    library = ctypes.CDLL(None)
    library._dyld_image_count.restype = ctypes.c_uint32
    library._dyld_get_image_name.argtypes = [ctypes.c_uint32]
    library._dyld_get_image_name.restype = ctypes.c_char_p
    allowed = (
        RUNTIME,
        Path("/System/Library"),
        Path("/usr/lib"),
        Path("/Library/Apple/System/Library"),
    )
    for index in range(library._dyld_image_count()):
        path = Path(os.fsdecode(library._dyld_get_image_name(index))).resolve()
        if not any(path.is_relative_to(root) for root in allowed):
            return False
    return True
