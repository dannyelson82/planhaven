import os
from pathlib import Path

import pytest

from app.core.crypto import DecryptionError, Keyring

KEY_A = bytes(range(32))
KEY_B = bytes(range(32, 64))
PURPOSE = "ai-provider-key"


def test_round_trip() -> None:
    ring = Keyring([KEY_A])

    blob = ring.encrypt(PURPOSE, b"sk-secret", context="provider:1")

    assert b"sk-secret" not in blob
    assert ring.decrypt(PURPOSE, blob, context="provider:1") == b"sk-secret"


def test_same_plaintext_encrypts_differently() -> None:
    ring = Keyring([KEY_A])

    assert ring.encrypt(PURPOSE, b"x") != ring.encrypt(PURPOSE, b"x")


@pytest.mark.parametrize("position", [0, 5, 15, 25, -1])
def test_tampering_is_detected(position: int) -> None:
    ring = Keyring([KEY_A])
    blob = bytearray(ring.encrypt(PURPOSE, b"secret"))
    blob[position] ^= 0x01

    with pytest.raises(DecryptionError):
        ring.decrypt(PURPOSE, bytes(blob))


def test_other_purpose_cannot_decrypt() -> None:
    ring = Keyring([KEY_A])
    blob = ring.encrypt("ai-provider-key", b"secret")

    with pytest.raises(DecryptionError):
        ring.decrypt("totp-secret", blob)


def test_ciphertext_moved_to_another_row_fails() -> None:
    ring = Keyring([KEY_A])
    blob = ring.encrypt(PURPOSE, b"secret", context="user:alice")

    with pytest.raises(DecryptionError):
        ring.decrypt(PURPOSE, blob, context="user:mallory")


def test_wrong_master_key_fails() -> None:
    blob = Keyring([KEY_A]).encrypt(PURPOSE, b"secret")

    with pytest.raises(DecryptionError):
        Keyring([KEY_B]).decrypt(PURPOSE, blob)


def test_rotation_decrypts_old_and_encrypts_with_new() -> None:
    old_blob = Keyring([KEY_A]).encrypt(PURPOSE, b"secret")
    rotated = Keyring([KEY_B, KEY_A])

    assert rotated.decrypt(PURPOSE, old_blob) == b"secret"
    assert rotated.needs_reencryption(old_blob)
    new_blob = rotated.encrypt(PURPOSE, b"secret")
    assert not rotated.needs_reencryption(new_blob)
    assert Keyring([KEY_B]).decrypt(PURPOSE, new_blob) == b"secret"


@pytest.mark.parametrize("blob", [b"", b"\x01", b"\x02" + b"\x00" * 60, os.urandom(40)])
def test_malformed_input_is_rejected(blob: bytes) -> None:
    with pytest.raises(DecryptionError):
        Keyring([KEY_A]).decrypt(PURPOSE, blob)


def test_unknown_purpose_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown encryption purpose"):
        Keyring([KEY_A]).encrypt("anything", b"x")


def test_master_key_must_be_32_bytes() -> None:
    with pytest.raises(ValueError, match="32 bytes"):
        Keyring([b"short"])


def test_loads_private_key_file(tmp_path: Path) -> None:
    path = tmp_path / "master.key"
    path.write_bytes(KEY_A)
    path.chmod(0o600)

    assert (
        Keyring.from_file(path).decrypt(PURPOSE, Keyring([KEY_A]).encrypt(PURPOSE, b"ok")) == b"ok"
    )


def test_refuses_readable_or_symlinked_key_file(tmp_path: Path) -> None:
    path = tmp_path / "master.key"
    path.write_bytes(KEY_A)
    path.chmod(0o644)
    with pytest.raises(PermissionError, match="chmod 600"):
        Keyring.from_file(path)

    path.chmod(0o600)
    link = tmp_path / "link.key"
    link.symlink_to(path)
    with pytest.raises(PermissionError, match="regular file"):
        Keyring.from_file(link)
