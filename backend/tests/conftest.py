import ipaddress

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "base_url": "https://planhaven.example.com",
        "public_mode": True,
        "trusted_proxies": (ipaddress.ip_network("192.0.2.0/24"),),
        "admin_allowed_cidrs": (),
        "max_upload_mb": 100,
        "max_json_bytes": 1024,
        "log_level": "info",
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
