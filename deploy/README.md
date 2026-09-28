# Deployment helpers

Tested configurations for running PlanHaven behind a reverse proxy (SECURITY.md §9).

| Folder | What it's for |
|---|---|
| `crowdsec/` | Parser, scenario and acquisition for PlanHaven's security log |
| `fail2ban/` | Filter and jail for the same log |
| `proxy/nginx-proxy-manager/` | Proxy host settings for Nginx Proxy Manager |

The security log is `/config/logs/security.log` inside the container: one JSON object per
line with `ts`, `event`, `ip` and `user_id`, plus event-specific fields. It never contains
passwords, tokens, codes or email addresses. Events that count toward a ban:
`login_failed`, `mfa_failed`, `rate_limited`.

For bans to hit the right address, the proxy must pass the client's real IP and
`TRUSTED_PROXIES` must list the proxy (SECURITY.md §7.11); otherwise every event shows the
proxy's address.
