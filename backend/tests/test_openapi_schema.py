"""The published OpenAPI schema (ADR 0021): it describes the REST API the iPhone app uses."""

import json
from pathlib import Path

from app import openapi_schema


def test_schema_describes_the_rest_api(tmp_path: Path) -> None:
    out = tmp_path / "openapi.json"
    assert openapi_schema.main(["openapi_schema", str(out), "1.2.3"]) == 0
    document = json.loads(out.read_text())
    assert document["info"]["version"] == "1.2.3"
    assert "/api/v1/projects" in document["paths"]
    assert "/api/v1/live/ticket" in document["paths"]
    assert document["components"]["securitySchemes"]["appToken"]["scheme"] == "bearer"
    # Hidden routes (the OAuth endpoints, the calendar feed) stay out of it.
    assert "/oauth/token" not in document["paths"]


def test_usage() -> None:
    assert openapi_schema.main(["openapi_schema"]) == 2
