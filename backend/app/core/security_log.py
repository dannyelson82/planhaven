"""The security log: one JSON object per line in /config/logs/security.log, in a stable format
for fail2ban and CrowdSec (SECURITY.md §7.12, deploy/). Also sent to the normal log.

Format (fields may be added, never renamed or removed):
  {"ts": "...", "event": "login_failed", "ip": "198.51.100.7", "user_id": "..." | null, ...}

Events: login_failed, login_succeeded, mfa_failed, rate_limited, setup_completed,
password_changed, session_revoked, passkey_added, passkey_removed.
Never contains passwords, tokens, codes or email addresses.
"""

import json
import logging
import logging.handlers
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.logging import redact_value

_logger = logging.getLogger("planhaven.security")
_file_logger = logging.getLogger("planhaven.security.file")
_file_logger.propagate = False


def configure(log_dir: str | None) -> None:
    """Attach the rotating file handler; None (tests) keeps only the normal log."""
    for handler in _file_logger.handlers:
        handler.close()
    _file_logger.handlers.clear()
    if log_dir is None:
        return
    path = Path(log_dir) / "security.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        path, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    _file_logger.addHandler(handler)
    _file_logger.setLevel(logging.INFO)


def event(name: str, *, ip: str | None, user_id: object = None, **fields: Any) -> None:
    entry: dict[str, Any] = {
        "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
        "event": name,
        "ip": ip,
        "user_id": str(user_id) if user_id is not None else None,
    }
    entry.update({k: redact_value(k, v) for k, v in fields.items()})
    _file_logger.info(json.dumps(entry, ensure_ascii=False))
    _logger.info("security event", extra={"event": name, "ip": ip, "user_id": entry["user_id"]})
