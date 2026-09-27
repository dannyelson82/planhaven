# ADR 0009: Deploy behind the user's existing reverse proxy; no forward-auth in front of the app

- **Status:** Accepted
- **Date:** 2026-09-26

## Context

Self-hosters typically already run a reverse proxy (Nginx Proxy Manager, SWAG, Traefik) that
terminates TLS for all their apps, and often a forward-auth layer (Authelia, Authentik proxy
auth, Cloudflare Access) in front of some of them. Planhaven must be reachable by
non-browser clients that can't complete interactive login redirects: the Apple Shortcut, the
calendar app and MCP connectors (ADR 0006, ADR 0007).

## Options considered

1. **Use the operator's reverse proxy for TLS; Planhaven handles its own auth.** Fits
   existing setups; all clients work. The app must be safe even if the proxy is
   misconfigured.
2. **Bundle TLS (built-in ACME) in the container.** Self-contained. Conflicts with the
   existing proxy on ports 80/443 and duplicates certificate management.
3. **Require forward-auth in front of the app.** An extra login layer. Breaks the Shortcut,
   the ICS feed and the MCP connector, which cannot pass interactive forward-auth.

## Decision

- The container serves plain HTTP on port 8080. TLS is terminated at the operator's reverse
  proxy (A§4.4).
- **Forward-auth must not be placed in front of Planhaven** (S§9). Planhaven's native auth
  (mandatory 2FA, passkeys) is the auth layer; optional OIDC login covers single sign-on
  (S§7.1).
- Forwarded headers are trusted only from `TRUSTED_PROXIES`. In `PUBLIC_MODE` (the default)
  the app refuses to start without `TRUSTED_PROXIES` and an `https` `BASE_URL` (S§7.11).
- The app sets its own security headers and doesn't rely on the proxy for them (S§7.10).
- Tested proxy snippets and fail2ban/CrowdSec parsers ship in `deploy/` (A§6, S§9).

## Consequences

- Internet exposure depends on Planhaven's own authentication, so its auth, rate limiting and
  lockout (S§7.1, S§7.11) must be production-grade from phase 0.1.
- Edge banning uses the app's security log (`/config/logs/security.log`) via fail2ban or
  CrowdSec.
- `ADMIN_ALLOWED_CIDRS` can restrict the admin panel to the LAN.
- Operators who want an extra layer can restrict by IP or country at the proxy, as long as it
  doesn't require interactive login.
