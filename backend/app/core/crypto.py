"""Encryption of secrets at rest (SECURITY.md §7.9).

AI provider keys, TOTP secrets and OIDC client secrets are stored encrypted with AES-256-GCM.
Keys are derived from the master key (`/config/secrets/master.key`, never in the database)
with HKDF-SHA256, one key per purpose, so a key for one use can't decrypt another's data.

Ciphertext format (bytes): version (1) | key ID (8) | nonce (12) | AES-GCM ciphertext+tag.
The key ID identifies which master key encrypted it, so the master key can be rotated: add
the new key first in the keyring, keep the old one until everything is re-encrypted.

`context` (e.g. the owning row's ID) is authenticated but not stored: a ciphertext copied to
another row fails to decrypt.
"""

import hashlib
import os
import stat
from collections.abc import Sequence
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

VERSION = 1
KEY_ID_LEN = 8
NONCE_LEN = 12
MASTER_KEY_LEN = 32
HEADER_LEN = 1 + KEY_ID_LEN + NONCE_LEN

# Every use of encryption names its purpose; add new purposes here, never reuse one.
PURPOSES = frozenset({"ai-provider-key", "totp-secret", "oidc-client-secret"})


class DecryptionError(Exception):
    """Ciphertext is malformed, tampered with, for another purpose/context, or from an
    unknown key. Deliberately says nothing more."""


def _key_id(master: bytes) -> bytes:
    return hashlib.sha256(b"planhaven key id\x00" + master).digest()[:KEY_ID_LEN]


def _derive(master: bytes, purpose: str) -> AESGCM:
    key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"planhaven:v1:" + purpose.encode(),
    ).derive(master)
    return AESGCM(key)


def _aad(purpose: str, context: str) -> bytes:
    return b"planhaven:v1\x00" + purpose.encode() + b"\x00" + context.encode()


class Keyring:
    """Master keys, newest first. Encrypts with the first; decrypts with any."""

    def __init__(self, master_keys: Sequence[bytes]) -> None:
        if not master_keys:
            raise ValueError("at least one master key is required")
        for key in master_keys:
            if len(key) != MASTER_KEY_LEN:
                raise ValueError("master keys must be 32 bytes")
        self._keys = {_key_id(k): k for k in master_keys}
        self._current = _key_id(master_keys[0])

    @classmethod
    def from_file(cls, path: Path) -> Keyring:
        """Load the master key, refusing files others could read or a symlink."""
        st = path.lstat()
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
            raise PermissionError(f"{path} must be a regular file")
        if stat.S_IMODE(st.st_mode) & 0o077:
            raise PermissionError(f"{path} must not be readable by others (chmod 600)")
        return cls([path.read_bytes()])

    def encrypt(self, purpose: str, plaintext: bytes, context: str = "") -> bytes:
        _check_purpose(purpose)
        nonce = os.urandom(NONCE_LEN)
        aead = _derive(self._keys[self._current], purpose)
        ciphertext = aead.encrypt(nonce, plaintext, _aad(purpose, context))
        return bytes([VERSION]) + self._current + nonce + ciphertext

    def decrypt(self, purpose: str, blob: bytes, context: str = "") -> bytes:
        _check_purpose(purpose)
        if len(blob) < HEADER_LEN + 16 or blob[0] != VERSION:
            raise DecryptionError
        key_id = blob[1 : 1 + KEY_ID_LEN]
        nonce = blob[1 + KEY_ID_LEN : HEADER_LEN]
        master = self._keys.get(key_id)
        if master is None:
            raise DecryptionError
        try:
            return _derive(master, purpose).decrypt(
                nonce, blob[HEADER_LEN:], _aad(purpose, context)
            )
        except InvalidTag:
            raise DecryptionError from None

    def needs_reencryption(self, blob: bytes) -> bool:
        """True if `blob` was encrypted with an older master key."""
        return blob[1 : 1 + KEY_ID_LEN] != self._current


def _check_purpose(purpose: str) -> None:
    if purpose not in PURPOSES:
        raise ValueError(f"unknown encryption purpose: {purpose!r}")
