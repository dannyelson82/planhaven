import ipaddress

import pytest

from app.core import config
from app.core.config import ConfigError, load_settings

VALID = {"BASE_URL": "https://projects.example.com", "TRUSTED_PROXIES": "172.18.0.0/16"}


def env(**changes: str | None) -> dict[str, str]:
    merged: dict[str, str | None] = {**VALID, **changes}
    return {k: v for k, v in merged.items() if v is not None}


def test_valid_public_configuration() -> None:
    settings = load_settings(env(ADMIN_ALLOWED_CIDRS="192.168.1.0/24, fd00::/8"))

    assert settings.public_mode is True
    assert settings.base_url == "https://projects.example.com"
    assert settings.base_origin == "https://projects.example.com"
    assert settings.trusted_proxies == (ipaddress.ip_network("172.18.0.0/16"),)
    assert len(settings.admin_allowed_cidrs) == 2
    assert settings.max_upload_mb == 100
    assert settings.max_json_bytes == 1024 * 1024
    assert settings.log_level == "info"


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"BASE_URL": None}, "BASE_URL is required"),
        ({"BASE_URL": "http://projects.example.com"}, "must use https"),
        ({"BASE_URL": "projects.example.com"}, "full URL"),
        ({"BASE_URL": "https://user:pw@projects.example.com"}, "credentials"),
        ({"TRUSTED_PROXIES": None}, "TRUSTED_PROXIES is required"),
        ({"TRUSTED_PROXIES": "0.0.0.0/0"}, "every address"),
        ({"TRUSTED_PROXIES": "::/0"}, "every address"),
        ({"TRUSTED_PROXIES": "not-an-ip"}, "not an IP address"),
        ({"PUBLIC_MODE": "maybe"}, "true or false"),
        ({"MAX_UPLOAD_MB": "0"}, "between"),
        ({"MAX_UPLOAD_MB": "lots"}, "whole number"),
        ({"LOG_LEVEL": "verbose"}, "LOG_LEVEL"),
    ],
)
def test_refuses_insecure_or_invalid_configuration(
    changes: dict[str, str | None], message: str
) -> None:
    with pytest.raises(ConfigError, match=message):
        load_settings(env(**changes))


def test_private_mode_allows_http_without_proxies() -> None:
    settings = load_settings({"PUBLIC_MODE": "false", "BASE_URL": "http://planhaven.lan:8080"})

    assert settings.public_mode is False
    assert settings.trusted_proxies == ()


def test_main_reports_error_and_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("BASE_URL", raising=False)

    assert config.main() == 1
    assert "configuration error: BASE_URL is required" in capsys.readouterr().err


def test_main_ok(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    for key, value in VALID.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("PUBLIC_MODE", raising=False)

    assert config.main() == 0
    assert "configuration ok (public mode)" in capsys.readouterr().out
