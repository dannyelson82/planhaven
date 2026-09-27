"""First-boot secret generation (ARCHITECTURE.md §4.5, SECURITY.md §7.9).

Run once at container start by the `init-secrets` service, as the app user:

    python -m app.core.init_secrets /config/secrets

Creates any missing secret; never overwrites an existing one. Existing files with permissions
looser than 0600 are tightened, because a group- or world-readable master key is a leak.
"""

import base64
import os
import secrets
import stat
import sys
from collections.abc import Callable
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

MASTER_KEY = "master.key"
SESSION_KEY = "session.key"
VAPID_PRIVATE_KEY = "vapid_private.pem"
VAPID_PUBLIC_KEY = "vapid_public.txt"

FILE_MODE = 0o600
DIR_MODE = 0o700


def _random_key() -> bytes:
    return secrets.token_bytes(32)  # 256-bit


def _public_b64(private: ec.EllipticCurvePrivateKey) -> bytes:
    public_raw = private.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return base64.urlsafe_b64encode(public_raw).rstrip(b"=") + b"\n"


def _vapid_keypair() -> tuple[bytes, bytes]:
    """P-256 keypair for Web Push (RFC 8292). Public key is the base64url uncompressed point."""
    private = ec.generate_private_key(ec.SECP256R1())
    private_pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return private_pem, _public_b64(private)


def _vapid_public_from(private_pem: bytes) -> bytes:
    private = serialization.load_pem_private_key(private_pem, password=None)
    if not isinstance(private, ec.EllipticCurvePrivateKey):
        raise RuntimeError(f"{VAPID_PRIVATE_KEY} is not an EC private key")
    return _public_b64(private)


def _write_new(path: Path, data: bytes) -> None:
    """Create `path` with mode 0600 atomically; fails if it already exists."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, FILE_MODE)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)


def _tighten(path: Path, mode: int) -> None:
    st = path.lstat()
    if stat.S_ISLNK(st.st_mode):
        raise RuntimeError(f"{path} is a symlink; refusing to use it")
    if stat.S_IMODE(st.st_mode) & 0o077:
        path.chmod(mode)


def init_secrets(directory: Path) -> list[str]:
    """Ensure all secrets exist in `directory`. Returns the names of files created."""
    directory.mkdir(mode=DIR_MODE, parents=True, exist_ok=True)
    _tighten(directory, DIR_MODE)

    created: list[str] = []

    def ensure(name: str, make: Callable[[], bytes]) -> None:
        path = directory / name
        if path.exists() or path.is_symlink():
            _tighten(path, FILE_MODE)
            return
        _write_new(path, make())
        created.append(name)

    ensure(MASTER_KEY, _random_key)
    ensure(SESSION_KEY, _random_key)

    private_path = directory / VAPID_PRIVATE_KEY
    public_path = directory / VAPID_PUBLIC_KEY
    if not private_path.exists():
        private_pem, public_b64 = _vapid_keypair()
        public_path.unlink(missing_ok=True)  # must match the new private key
        _write_new(private_path, private_pem)
        _write_new(public_path, public_b64)
        created += [VAPID_PRIVATE_KEY, VAPID_PUBLIC_KEY]
    else:
        _tighten(private_path, FILE_MODE)
        if public_path.exists():
            _tighten(public_path, FILE_MODE)
        else:
            _write_new(public_path, _vapid_public_from(private_path.read_bytes()))
            created.append(VAPID_PUBLIC_KEY)

    return created


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m app.core.init_secrets <secrets-dir>", file=sys.stderr)
        return 2
    os.umask(0o077)
    created = init_secrets(Path(argv[1]))
    # Names only, never contents.
    print(f"init-secrets: created {', '.join(created)}" if created else "init-secrets: all present")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
