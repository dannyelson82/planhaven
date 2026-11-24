"""The OpenAPI schema of PlanHaven's REST API, written to a file (ADR 0021, phase 0.5).

The running server doesn't serve it (it would map the attack surface for anyone on the
internet, A§8.2). CI generates it on every pull request, and each release attaches it as
`openapi.json`, so the iPhone app can build and check its client against the exact server
version it pins.

    uv run python -m app.openapi_schema openapi.json [version]
"""

import json
import sys
from pathlib import Path
from typing import Any

from fastapi.openapi.utils import get_openapi

from app.main import ROUTERS


def schema(version: str = "dev") -> dict[str, Any]:
    routes = [route for router in ROUTERS for route in router.routes]
    document = get_openapi(
        title="PlanHaven",
        version=version,
        description=(
            "PlanHaven's REST API (/api/v1). The iPhone app signs in with OAuth 2.1 and PKCE "
            "(ADR 0021) and sends its access token as `Authorization: Bearer phv_aat_...`; "
            "routes for account security answer 403 to it."
        ),
        routes=routes,
    )
    document.setdefault("components", {})["securitySchemes"] = {
        "appToken": {
            "type": "http",
            "scheme": "bearer",
            "description": "The iPhone app's access token (phv_aat_, 1 hour).",
        }
    }
    return document


def main(argv: list[str]) -> int:
    if not 2 <= len(argv) <= 3:
        print("usage: python -m app.openapi_schema OUT.json [VERSION]", file=sys.stderr)
        return 2
    version = argv[2] if len(argv) == 3 else "dev"
    Path(argv[1]).write_text(json.dumps(schema(version), indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
