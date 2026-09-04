"""Private vault implementation, never imported by the trading runtime.

File permissions protect other users; same-UID arbitrary code is NOT isolated.
See docs/OKX_OPAQUE_VAULT.md for the required OS deployment boundary.
"""

from __future__ import annotations

import ctypes
import json
import os
import stat
import sys
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

BUNDLE = "okx-paper-credentials"
FIELDS = ("OKX_API_KEY", "OKX_API_SECRET", "OKX_API_PASSPHRASE")
MAGIC = b"OKXVAULT1\x00"
AAD = BUNDLE.encode() + MAGIC


class VaultError(Exception):
    """Error without raw library exceptions or credential material."""

    def __init__(self, code, *, os_status=None):
        super().__init__(code)
        self.code = code
        self.os_status = os_status


class _KeychainKey:
    """Keychain access inside the broker process; no CLI for retrieving this key."""

    def __init__(self, keychain_path=None, *, create_keychain=False, password=None):
        if sys.platform != "darwin":
            raise VaultError("MACOS_KEYCHAIN_REQUIRED")
        self._security = ctypes.CDLL("/System/Library/Frameworks/Security.framework/Security")
        self._service = b"crypto-auto-trading-system"
        self._account = b"okx-paper-credentials-aes256-key"
        s = self._security
        s.SecKeychainFindGenericPassword.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_char_p,
            ctypes.c_uint32,
            ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        s.SecKeychainFindGenericPassword.restype = ctypes.c_int32
        s.SecKeychainAddGenericPassword.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_char_p,
            ctypes.c_uint32,
            ctypes.c_char_p,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        s.SecKeychainAddGenericPassword.restype = ctypes.c_int32
        s.SecKeychainItemFreeContent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        s.SecKeychainItemDelete.argtypes = [ctypes.c_void_p]
        s.SecKeychainItemDelete.restype = ctypes.c_int32
        self._cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        self._cf.CFRelease.argtypes = [ctypes.c_void_p]
        self._keychain = ctypes.c_void_p()
        if keychain_path is not None:
            # The human-held private Keychain password is never persisted. A
            # locked Keychain (including after reboot) fails closed until unlocked
            # through the administrator's protected terminal command.
            s.SecKeychainSetUserInteractionAllowed.argtypes = [ctypes.c_bool]
            s.SecKeychainSetUserInteractionAllowed(False)
            s.SecKeychainOpen.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p)]
            s.SecKeychainCreate.argtypes = [
                ctypes.c_char_p,
                ctypes.c_uint32,
                ctypes.c_void_p,
                ctypes.c_bool,
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_void_p),
            ]
            s.SecKeychainUnlock.argtypes = [
                ctypes.c_void_p,
                ctypes.c_uint32,
                ctypes.c_void_p,
                ctypes.c_bool,
            ]
            path = os.fsencode(keychain_path)
            creating = create_keychain and not Path(keychain_path).exists()
            if creating:
                if password is None or len(password) < 12:
                    raise VaultError("STRONG_KEYCHAIN_PASSWORD_REQUIRED")
                status = s.SecKeychainCreate(
                    path, len(password), password, False, None, ctypes.byref(self._keychain)
                )
            else:
                status = s.SecKeychainOpen(path, ctypes.byref(self._keychain))
            if status != 0:
                operation = "CREATE" if creating else "OPEN"
                raise VaultError(f"PRIVATE_KEYCHAIN_{operation}_FAILED", os_status=status)
            if password is not None:
                unlock_status = s.SecKeychainUnlock(self._keychain, len(password), password, True)
                if unlock_status != 0:
                    raise VaultError("PRIVATE_KEYCHAIN_UNLOCK_FAILED", os_status=unlock_status)
            Path(keychain_path).chmod(0o600)

    def _find(self):
        length, data, item = ctypes.c_uint32(), ctypes.c_void_p(), ctypes.c_void_p()
        status = self._security.SecKeychainFindGenericPassword(
            self._keychain,
            len(self._service),
            self._service,
            len(self._account),
            self._account,
            ctypes.byref(length),
            ctypes.byref(data),
            ctypes.byref(item),
        )
        return status, length, data, item

    def _obtain(self, *, create=False):
        status, length, data, item = self._find()
        try:
            if status == 0:
                if length.value != 32:
                    raise VaultError("INVALID_VAULT_KEY")
                return ctypes.string_at(data, length.value)
            if status != -25300 or not create:  # errSecItemNotFound
                raise VaultError("KEYCHAIN_UNAVAILABLE")
            key = os.urandom(32)
            buffer = ctypes.create_string_buffer(key)
            result = self._security.SecKeychainAddGenericPassword(
                self._keychain,
                len(self._service),
                self._service,
                len(self._account),
                self._account,
                len(key),
                ctypes.cast(buffer, ctypes.c_void_p),
                None,
            )
            ctypes.memset(buffer, 0, len(buffer))
            if result != 0:
                raise VaultError("KEYCHAIN_WRITE_FAILED")
            return key
        finally:
            if data:
                self._security.SecKeychainItemFreeContent(None, data)
            if item:
                self._cf.CFRelease(item)

    def _delete(self):
        status, _, data, item = self._find()
        try:
            if status == -25300:
                return
            if status != 0 or self._security.SecKeychainItemDelete(item) != 0:
                raise VaultError("KEYCHAIN_DELETE_FAILED")
        finally:
            if data:
                self._security.SecKeychainItemFreeContent(None, data)
            if item:
                self._cf.CFRelease(item)


def private_directory(path: Path):
    if path.is_symlink():
        raise VaultError("UNSAFE_VAULT_DIRECTORY")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise VaultError("VAULT_DIRECTORY_MUST_BE_0700")


class _Vault:
    def __init__(self, path: Path, key_provider):
        self._path, self._keys = path, key_provider

    def _save(self, values):
        if set(values) != set(FIELDS) or not all(
            isinstance(v, str)
            and 8 <= len(v) <= 1024
            and v.isascii()
            and all(32 <= ord(c) < 127 for c in v)
            for v in values.values()
        ):
            raise VaultError("INVALID_CREDENTIAL_FIELDS")
        private_directory(self._path.parent)
        if self._path.is_symlink():
            raise VaultError("UNSAFE_VAULT_FILE")
        key = self._keys._obtain(create=not self._path.exists())
        nonce = os.urandom(12)
        plaintext = bytearray(json.dumps(values).encode())
        try:
            encrypted = MAGIC + nonce + AESGCM(key).encrypt(nonce, bytes(plaintext), AAD)
        finally:
            plaintext[:] = b"\x00" * len(plaintext)
            del key
        fd, temporary = tempfile.mkstemp(prefix=".okx-encrypted-", dir=self._path.parent)
        try:
            with os.fdopen(fd, "wb") as out:
                os.fchmod(out.fileno(), 0o600)
                out.write(encrypted)
                out.flush()
                os.fsync(out.fileno())
            os.replace(temporary, self._path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _decrypt(self):
        private_directory(self._path.parent)
        fd = os.open(self._path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as source:
            info = os.fstat(source.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600
            ):
                raise VaultError("VAULT_FILE_MUST_BE_0600")
            data = source.read(16385)
        if len(data) > 16384 or not data.startswith(MAGIC):
            raise VaultError("INVALID_VAULT_DOCUMENT")
        offset = len(MAGIC)
        key = self._keys._obtain()
        plaintext = bytearray()
        try:
            plaintext = bytearray(
                AESGCM(key).decrypt(
                    data[offset : offset + 12],
                    data[offset + 12 :],
                    AAD,
                )
            )
            values = json.loads(plaintext)
            if set(values) != set(FIELDS) or not all(
                isinstance(v, str) and v for v in values.values()
            ):
                raise VaultError("INVALID_VAULT_DOCUMENT")
            return values
        except Exception:
            raise VaultError("VAULT_AUTHENTICATION_FAILED") from None
        finally:
            plaintext[:] = b"\x00" * len(plaintext)
            del key

    def _delete(self):
        if self._path.is_symlink():
            raise VaultError("UNSAFE_VAULT_FILE")
        # Retain ciphertext if Keychain removal fails; deletion is human-only.
        self._keys._delete()
        self._path.unlink(missing_ok=True)
