"""Structured JSON logging with redaction (SECURITY.md §7.12).

Passwords, tokens, cookies and secrets must never reach the logs. Two layers enforce that:
fields with sensitive names are replaced, and anything that looks like a Planhaven token or a
bearer credential is masked wherever it appears in a message or field value.
"""

import json
import logging
import re
import sys
import traceback
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

REDACTED = "[redacted]"

_SENSITIVE_KEY = re.compile(
    r"pass(word|wd|phrase)?|secret|token|api[_-]?key|authorization|cookie|session|"
    r"credential|private[_-]?key|otp|totp|recovery",
    re.IGNORECASE,
)
_SECRET_PATTERNS = (
    re.compile(r"phv_(sync|ics|pat|oat|ort|inv)_[A-Za-z0-9_-]+"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"),
)
# Paths whose last segment is a secret (calendar feed tokens live in the URL, A§13.2).
_SECRET_PATHS = (re.compile(r"^(/ics/)[^/]+$"),)

# Attributes every LogRecord has; anything else was passed via `extra=`.
_STANDARD_ATTRS = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "taskName"}


def redact_text(text: str) -> str:
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


def redact_path(path: str) -> str:
    for pattern in _SECRET_PATHS:
        path = pattern.sub(r"\1" + REDACTED, path)
    return redact_text(path)


def redact_value(key: str, value: Any) -> Any:
    if _SENSITIVE_KEY.search(key):
        return REDACTED
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {str(k): redact_value(str(k), v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [redact_value(key, v) for v in value]
    return value


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": redact_text(record.getMessage()),
        }
        request_id = request_id_var.get()
        if request_id:
            entry["request_id"] = request_id
        for key, value in vars(record).items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                entry[key] = redact_value(key, value)
        if record.exc_info:
            # Exception type and frames (file, line, function) only: exception messages and
            # local values can carry user data.
            exc_type, _, tb = record.exc_info
            entry["exc_type"] = exc_type.__name__ if exc_type else None
            entry["exc_frames"] = [
                f"{frame.filename}:{frame.lineno} in {frame.name}"
                for frame in traceback.extract_tb(tb)[-10:]
            ]
        return json.dumps(entry, default=str, ensure_ascii=False)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # Route uvicorn's own loggers through the same formatter; its access log stays off
    # (AccessLogMiddleware replaces it with a redacted one).
    for name in ("uvicorn", "uvicorn.error"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
    logging.getLogger("uvicorn.access").disabled = True
