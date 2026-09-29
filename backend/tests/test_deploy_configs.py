"""The fail2ban filter and CrowdSec files must match what the app actually writes."""

import json
import logging
import re
from pathlib import Path

import pytest

from app.core import security_log

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"


def _fail2ban_regex() -> re.Pattern[str]:
    text = (DEPLOY / "fail2ban/filter.d/planhaven.conf").read_text()
    line = next(x for x in text.splitlines() if x.startswith("failregex"))
    pattern = line.split("=", 1)[1].strip()
    return re.compile(pattern.replace("<HOST>", r"(?P<host>[0-9a-fA-F:.]+)"))


def _written_lines(tmp_path: Path, *events: tuple[str, str | None]) -> list[str]:
    security_log.configure(str(tmp_path))
    try:
        for name, ip in events:
            security_log.event(name, ip=ip, user_id=None, method="password")
    finally:
        security_log.configure(None)
        logging.getLogger("planhaven.security.file").handlers.clear()
    return (tmp_path / "security.log").read_text().splitlines()


@pytest.mark.parametrize(
    "event", ["login_failed", "mfa_failed", "rate_limited", "share_link_failed"]
)
@pytest.mark.parametrize("ip", ["198.51.100.7", "2001:db8::42"])
def test_fail2ban_filter_matches_ban_events(tmp_path: Path, event: str, ip: str) -> None:
    (line,) = _written_lines(tmp_path, (event, ip))
    match = _fail2ban_regex().search(line)
    assert match is not None
    assert match.group("host") == ip


@pytest.mark.parametrize("event", ["login_succeeded", "setup_completed", "password_changed"])
def test_fail2ban_ignores_normal_events(tmp_path: Path, event: str) -> None:
    (line,) = _written_lines(tmp_path, (event, "198.51.100.7"))
    assert _fail2ban_regex().search(line) is None


def test_crowdsec_fields_exist_in_log_lines(tmp_path: Path) -> None:
    (line,) = _written_lines(tmp_path, ("login_failed", "198.51.100.7"))
    entry = json.loads(line)
    parser = (DEPLOY / "crowdsec/parsers/s01-parse/planhaven-logs.yaml").read_text()
    for field in re.findall(r"JsonExtract\(evt\.Line\.Raw, '(\w+)'\)", parser):
        assert field in entry, field
    scenario = (DEPLOY / "crowdsec/scenarios/planhaven-bf.yaml").read_text()
    for name in re.findall(r"'planhaven_(\w+)'", scenario):
        assert name in {"login_failed", "mfa_failed", "rate_limited", "share_link_failed"}
