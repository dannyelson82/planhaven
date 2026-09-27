"""Session-bound values derived from the session signing key (SECURITY.md §7.2).

The CSRF token is HMAC(session key, session token): tied to one session, recomputable on
every request, and never stored. Without the key (in /config/secrets, not the database) it
can't be forged.
"""

import hashlib
import hmac
import stat
from pathlib import Path

KEY_FILE = "session.key"


class SessionKey:
    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("session key must be 32 bytes")
        self._key = key

    @classmethod
    def from_dir(cls, secrets_dir: str) -> SessionKey:
        path = Path(secrets_dir) / KEY_FILE
        st = path.lstat()
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
            raise PermissionError(f"{path} must be a regular file")
        if stat.S_IMODE(st.st_mode) & 0o077:
            raise PermissionError(f"{path} must not be readable by others (chmod 600)")
        return cls(path.read_bytes())

    def csrf_token(self, session_token: str) -> str:
        return hmac.new(self._key, b"csrf\x00" + session_token.encode(), hashlib.sha256).hexdigest()

    def csrf_valid(self, session_token: str, presented: str) -> bool:
        return hmac.compare_digest(self.csrf_token(session_token), presented)
