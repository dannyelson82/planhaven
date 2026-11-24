# ADR 0021: Server support for the native iPhone app comes next; how the app signs in

- **Status:** Accepted
- **Date:** 2026-11-24
- **Changes:** roadmap (ARCHITECTURE.md §18) order and numbering; extends ADR 0007 (a first-party
  app client whose tokens work on the REST API); updates ADR 0006 and A§19.2 (native apps)

## Context

ADR 0006 chose Shortcuts, ICS, Web Push and the PWA for the iPhone, and A§18 put native apps
"later". In November 2026 the maintainer started a native SwiftUI app (a separate repository,
built on the Mac) for what the web can't do: Reminders and Calendar through EventKit, widgets,
Siri (App Intents), a Share extension, the camera, and real offline use. Versions 0.1 and 0.2
work against v0.4.2 with no server changes, by signing in the way the browser does: password
and TOTP, a session cookie, a CSRF token and an `Origin` header.

That has limits the server has to fix:
- the app is signed out after 7 idle days, 30 days at most (S§7.2), and its Siri actions stop
  with it;
- passkeys can't be used (the person's passkey lives in a password manager);
- every API change has to be copied into the app by hand, because no OpenAPI file is published.

ADR 0007's OAuth server already does nearly all of what a native app needs (A§12.2), but its
tokens work only on `/mcp`. Release versions must keep increasing, so the roadmap is renumbered
to the order things will ship (as in ADR 0019).

## Options considered

1. **Keep the browser sign-in in the app.** No server work; keeps the 30-day limit, no passkeys,
   and puts a cookie jar, CSRF handling and the `Origin` rule into a native client.
2. **A native login endpoint that issues a device token.** Simple, but a second sign-in path
   to secure, and passkeys would need Associated Domains (a paid Apple account) and an
   `apple-app-site-association` file.
3. **A built-in first-party client of the existing OAuth server** (RFC 8252): the person signs
   in on the server's own pages in a system browser sheet, however their account does (password
   and TOTP, or a passkey), and the app gets tokens for `/api/v1`. Reuses ADR 0007's tested
   code; passkeys work without a paid Apple account.

## Decision

**Roadmap (ARCHITECTURE.md §18, maintainer 2026-11-24):** 0.5 iPhone app support, server side
(new); 0.6 Local AI (was 0.5); 0.7 Time planner (was 0.6, still postponed); 0.8 Cut-list plugin
(was 0.7). Older ADRs keep the numbers they were written with; this one maps them.

**App sign-in (option 3, design approved by the maintainer 2026-11-24):**

1. **Built-in client.** A fixed client `phc_planhaven_ios`, "PlanHaven for iPhone", created by
   a migration (not by dynamic registration). Its one redirect URI is the private-use scheme
   the app's bundle ID in reverse-DNS form (`com.example.planhaven:/oauth/callback` in examples; RFC 8252 §7.1); `redirect_allowed()` keeps
   refusing custom schemes for every other client. Public client, PKCE S256 required.
2. **Sign-in on the server's own pages.** The app opens `/oauth/authorize` with
   `resource=<base>/api/v1` in an ephemeral `ASWebAuthenticationSession`. The person signs in
   as usual; the page is on the server's own domain, so passkeys work with no Associated Domains.
   Consent for this client is one short question ("Sign in to PlanHaven for iPhone on
   <device>?"): no scope or write-mode choice. Approving needs a fresh second factor, as for AI
   apps. The response carries `iss`; the app exchanges the code with its PKCE verifier.
3. **Tokens for the REST API.** A new audience `<base>/api/v1`. App tokens are never accepted on
   `/mcp`, and MCP tokens are never accepted on `/api/v1`. New prefixes `phv_aat_` (access, 1
   hour) and `phv_art_` (refresh, rotated on every use; reuse revokes the whole family; the
   family ends after 90 days without use, configurable, with no absolute limit while in use).
   Hashed at rest; added to the secret-scanning regex, `.gitleaks.toml` and log redaction. The
   token request may name the device (`device_name`, at most 100 characters).
4. **Using a token.** `Authorization: Bearer phv_aat_…` on `/api/v1` gives the person's
   principal with the second factor counted as done. No cookies, so no CSRF or `Origin` checks
   (as for sync keys). A cookie and a bearer token together are refused (400). Refused with an
   app token, as "Do this in PlanHaven on the web." (403): admin routes; password, TOTP, passkey
   and recovery-code changes; ending other sessions; managing AI connections and sync keys;
   creating share links. The authz matrix records, for every route, whether an app token is
   allowed, and CI fails without it. WebSockets: `POST /api/v1/live/ticket` returns a single-use
   ticket valid for 30 seconds, passed on the handshake; a bearer token never goes in a
   WebSocket URL.
5. **Seeing and revoking.** Account gets "Signed-in apps": device name, first sign-in, last use,
   approximate place, Sign out. Revoking deletes the refresh family; access tokens are looked up,
   not self-contained, so they stop at once. A password change or turning 2FA off revokes all of
   the person's app tokens.
6. **Limits, audit, tests.** Rate limits on the token endpoint (per address and per client) and
   on refreshes per family. Audit events `app_token.issued`, `.refreshed`, `.reuse_detected`,
   `.revoked`. Tests for: the custom scheme for this client only; audience separation both ways;
   every route's app-token class; refresh reuse revoking the family; cookie plus bearer refused;
   a WebSocket ticket that can't be reused or used late.

**OpenAPI file:** each release publishes the server's `openapi.json` as a release asset, so the
app can generate or check its models against the exact server version it pins.

**Later in phase 0.5, each designed with the maintainer first:** APNs push (a new outbound
destination, S§7.8; needs the paid Apple account), a change feed for offline use, and the
`apple-app-site-association` file for universal links. Item locations ("where") and odometer
prompts wait for the app's version-1 feature choices.

## Consequences

- A second kind of bearer token reaches the REST API. The refused-route list and the
  per-route app-token class in the authz matrix are what keep a stolen phone token from
  changing the account's security; they're tested in CI.
- Refresh families can live indefinitely while used (unlike AI apps' 30 days), so "Signed-in
  apps" and revocation on password or 2FA changes matter; a lost phone is signed out from there.
- The private-use scheme can in principle be claimed by another app on the same phone; PKCE
  (the verifier never leaves the app) and the ephemeral browser session make an intercepted
  code useless (RFC 8252 §8.1).
- ADR 0006 still holds for the web: the Shortcut, ICS feed, Web Push and the PWA stay, for
  people who don't install the app.
- Security impact: S§6 (new threat rows), S§7.2, §7.3 (new token types), §7.11, §7.12 and a new
  section for the app, written with the implementation.
