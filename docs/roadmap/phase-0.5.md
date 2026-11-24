# Phase 0.5: iPhone app support (server)

> **Status:** Planned · **Planned with the maintainer:** 2026-11-24
> Scope: ARCHITECTURE.md §12.2, §18 (0.5), §19.2; ADR 0021 (extends ADR 0007). Every release
> meets SECURITY.md §11.

**Goal:** the native iPhone app (its own repository, built on the Mac) signs in properly and
stays signed in: through the server's own sign-in page, passkeys included, with tokens that
work on the REST API, a list of signed-in phones the person can sign out, and an OpenAPI file
the app can be built against. Later milestones add what the app needs for push and offline use.

**Decided (2026-11-24, ADR 0021):** a built-in first-party OAuth client with a private-use
redirect scheme; separate token audiences and prefixes for the app (`phv_aat_`, `phv_art_`);
security-sensitive routes refused with an app token; refresh families end after 90 days without
use; `openapi.json` attached to every release.

Every milestone: RLS on new tables (and the `pg_class` test), authz matrix entries, audit
events, rate limits, browser tests at phone and desktop widths where there's UI, threat-model
check, user guide and screenshots, a What's new entry.

## Milestone 1: App sign-in (v0.5.0)

- [ ] Built-in client `phc_planhaven_ios` created by a migration; private-use redirect
      the app's bundle ID (`com.example.planhaven:/oauth/callback` in examples), allowed for that client only; PKCE S256
- [ ] Consent for the app: one question naming the device, a fresh second factor; `iss` in
      the response
- [ ] Audience `<base>/api/v1`; `phv_aat_` (1 hour) and `phv_art_` (rotated, reuse revokes the
      family, 90 days without use, configurable); hashed; `device_name` on the token request;
      the new prefixes in the secret-scanning regex, `.gitleaks.toml` and log redaction
- [ ] Bearer path in `deps.require_session`: no CSRF or `Origin` checks for bearer requests;
      cookie plus bearer refused (400); MCP tokens refused on `/api/v1` and app tokens on `/mcp`
- [ ] Routes refused with an app token (403 "Do this in PlanHaven on the web."): admin;
      password, TOTP, passkey and recovery-code changes; ending other sessions; AI connections
      and sync keys; creating share links. An app-token class for every route in the authz
      matrix; CI fails without it
- [ ] `POST /api/v1/live/ticket`: single-use WebSocket ticket, 30 seconds
- [ ] Account, "Signed-in apps": device name, first sign-in, last use, approximate place,
      Sign out; a password change or turning 2FA off signs out every app
- [ ] Rate limits on the token endpoint (per address, per client) and refreshes per family;
      audit events `app_token.issued`, `.refreshed`, `.reuse_detected`, `.revoked`
- [ ] SECURITY.md: threat rows (§6), sessions and tokens (§7.2, §7.3), rate limits (§7.11),
      audit (§7.12) and a section for the app; user guide; What's new

## Milestone 2: OpenAPI file with each release (v0.5.0)

- [ ] The release workflow attaches `openapi.json` (the same schema CI already generates) to
      every GitHub release

## Milestone 3 and later: each designed with the maintainer before it's built

- [ ] APNs push from the worker (a new outbound destination, S§7.8; needs the paid Apple
      Developer account): device registration, the same notification types, preferences and
      quiet hours as Web Push, minimal payloads
- [ ] Change feed for offline use (per-user cursor; conflicts with `If-Match` and base, as now)
- [ ] `/.well-known/apple-app-site-association` for universal links (`/i/<item_id>`)
- [ ] Item locations ("where") and odometer prompts, if chosen for the app's version 1

## Wrap-up

- [ ] Phase security review against SECURITY.md §11
