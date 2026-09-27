"""Settings from environment variables (ARCHITECTURE.md §4.3).

In public mode (the default) the app refuses insecure configuration (SECURITY.md §7.11):
`BASE_URL` must be https and `TRUSTED_PROXIES` must be set. The container runs
`python -m app.core.config` before starting the app, so a bad setting stops the container
with a clear message instead of a restart loop.
"""

import ipaddress
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

type IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network
type LogLevel = Literal["debug", "info", "warning", "error"]

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}
_LOG_LEVELS: tuple[LogLevel, ...] = ("debug", "info", "warning", "error")


class ConfigError(ValueError):
    """Configuration is missing, malformed or insecure."""


@dataclass(frozen=True, slots=True)
class Settings:
    base_url: str
    public_mode: bool
    trusted_proxies: tuple[IPNetwork, ...]
    admin_allowed_cidrs: tuple[IPNetwork, ...]
    max_upload_mb: int
    max_json_bytes: int
    log_level: LogLevel

    @property
    def base_scheme(self) -> str:
        return urlsplit(self.base_url).scheme

    @property
    def base_origin(self) -> str:
        parts = urlsplit(self.base_url)
        return f"{parts.scheme}://{parts.netloc}"


def _bool(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = env.get(name, "").strip().lower()
    if not raw:
        return default
    if raw in _TRUE:
        return True
    if raw in _FALSE:
        return False
    raise ConfigError(f"{name} must be true or false")


def _int(env: Mapping[str, str], name: str, default: int, low: int, high: int) -> int:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a whole number") from None
    if not low <= value <= high:
        raise ConfigError(f"{name} must be between {low} and {high}")
    return value


def _networks(env: Mapping[str, str], name: str) -> tuple[IPNetwork, ...]:
    raw = env.get(name, "")
    networks: list[IPNetwork] = []
    for item in raw.replace(";", ",").split(","):
        item = item.strip()
        if not item:
            continue
        try:
            networks.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            raise ConfigError(f"{name}: {item!r} is not an IP address or CIDR range") from None
    return tuple(networks)


def _base_url(env: Mapping[str, str], public_mode: bool) -> str:
    raw = env.get("BASE_URL", "").strip().rstrip("/")
    if not raw:
        raise ConfigError("BASE_URL is required, e.g. https://projects.example.com")
    parts = urlsplit(raw)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ConfigError("BASE_URL must be a full URL like https://projects.example.com")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ConfigError("BASE_URL must not contain credentials, a query or a fragment")
    if public_mode and parts.scheme != "https":
        raise ConfigError("BASE_URL must use https in public mode (PUBLIC_MODE=true)")
    return raw


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Read and validate settings. Raises ConfigError with a user-facing message."""
    env = os.environ if env is None else env
    public_mode = _bool(env, "PUBLIC_MODE", default=True)
    base_url = _base_url(env, public_mode)
    trusted_proxies = _networks(env, "TRUSTED_PROXIES")
    if public_mode and not trusted_proxies:
        raise ConfigError(
            "TRUSTED_PROXIES is required in public mode: the IP address or network of your "
            "reverse proxy, e.g. 172.18.0.0/16"
        )
    if any(net.prefixlen == 0 for net in trusted_proxies):
        raise ConfigError("TRUSTED_PROXIES must not trust every address (0.0.0.0/0 or ::/0)")

    raw_level = env.get("LOG_LEVEL", "info").strip().lower() or "info"
    log_level = next((lvl for lvl in _LOG_LEVELS if lvl == raw_level), None)
    if log_level is None:
        raise ConfigError(f"LOG_LEVEL must be one of: {', '.join(_LOG_LEVELS)}")

    return Settings(
        base_url=base_url,
        public_mode=public_mode,
        trusted_proxies=trusted_proxies,
        admin_allowed_cidrs=_networks(env, "ADMIN_ALLOWED_CIDRS"),
        max_upload_mb=_int(env, "MAX_UPLOAD_MB", default=100, low=1, high=10_240),
        max_json_bytes=1024 * 1024,  # SECURITY.md §7.11
        log_level=log_level,
    )


def main() -> int:
    """Validate configuration; used by the container before the app starts."""
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"planhaven: configuration error: {exc}", file=sys.stderr)
        return 1
    mode = "public" if settings.public_mode else "private (PUBLIC_MODE=false)"
    print(f"planhaven: configuration ok ({mode} mode)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
