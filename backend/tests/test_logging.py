import json
import logging

import pytest

from app.core.logging import REDACTED, JSONFormatter, redact_path, redact_text, redact_value

TOKEN = "phv_pat_" + "Z9" * 20


def format_record(msg: str, **extra: object) -> dict[str, object]:
    record = logging.makeLogRecord({"msg": msg, "levelname": "INFO", "name": "t", **extra})
    return json.loads(JSONFormatter().format(record))  # type: ignore[no-any-return]


def test_masks_planhaven_tokens_in_messages() -> None:
    entry = format_record(f"user created token {TOKEN} ok")

    assert TOKEN not in json.dumps(entry)
    assert entry["msg"] == f"user created token {REDACTED} ok"


@pytest.mark.parametrize(
    "kind", ["sync", "ics", "pat", "oat", "ort", "occ", "inv", "setup", "rst", "shr"]
)
def test_masks_every_token_type(kind: str) -> None:
    token = f"phv_{kind}_" + "Ab3_-" * 9
    assert token not in redact_text(f"opened {token} just now")


def test_masks_bearer_credentials() -> None:
    assert redact_text("Authorization: Bearer abc.def.ghi") == f"Authorization: {REDACTED}"


@pytest.mark.parametrize(
    "key",
    [
        "password",
        "new_password",
        "api_key",
        "Authorization",
        "cookie",
        "session_id",
        "totp_code",
        "recovery_codes",
        "client_secret",
        "refresh_token",
    ],
)
def test_redacts_sensitive_field_names(key: str) -> None:
    entry = format_record("event", **{key: "hunter2hunter2"})

    assert entry[key] == REDACTED


def test_redacts_nested_values() -> None:
    value = redact_value("data", {"user": "ann", "password": "x", "notes": [TOKEN]})

    assert value == {"user": "ann", "password": REDACTED, "notes": [REDACTED]}


def test_keeps_ordinary_fields() -> None:
    entry = format_record("event", status=200, path="/api/v1/projects")

    assert entry["status"] == 200
    assert entry["path"] == "/api/v1/projects"


def test_redacts_calendar_feed_path() -> None:
    assert redact_path("/ics/abcdef123.ics") == f"/ics/{REDACTED}"
    assert redact_path("/api/v1/projects") == "/api/v1/projects"


def test_exceptions_log_type_and_frames_but_not_message() -> None:
    try:
        raise ValueError("the user's secret note text")
    except ValueError:
        import sys

        record = logging.makeLogRecord(
            {"msg": "failed", "levelname": "ERROR", "name": "t", "exc_info": sys.exc_info()}
        )
    entry = json.loads(JSONFormatter().format(record))

    assert entry["exc_type"] == "ValueError"
    assert entry["exc_frames"]
    assert "secret note" not in json.dumps(entry)
