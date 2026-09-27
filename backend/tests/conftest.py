import ipaddress
import os
import tempfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

# A throwaway secrets directory with a session key, like init-secrets creates.
_SECRETS = Path(tempfile.mkdtemp(prefix="planhaven-test-secrets-"))
(_SECRETS / "session.key").write_bytes(os.urandom(32))
(_SECRETS / "session.key").chmod(0o600)
(_SECRETS / "master.key").write_bytes(os.urandom(32))
(_SECRETS / "master.key").chmod(0o600)


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "base_url": "https://planhaven.example.com",
        "public_mode": True,
        "trusted_proxies": (ipaddress.ip_network("192.0.2.0/24"),),
        "admin_allowed_cidrs": (),
        "max_upload_mb": 100,
        "max_json_bytes": 1024,
        "log_level": "info",
        "secrets_dir": str(_SECRETS),
        "log_dir": None,
        "frontend_dir": None,
        "plugin_dirs": (str(Path(__file__).parent / "fixtures" / "plugins"),),
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)
