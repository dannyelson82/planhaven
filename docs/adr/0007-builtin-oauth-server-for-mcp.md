# ADR 0007: Built-in OAuth 2.1 authorization server for MCP

- **Status:** Accepted
- **Date:** 2026-09-26

## Context

Commercial AI assistants (Claude, ChatGPT) connect to remote MCP servers as custom connectors,
using OAuth 2.1 with PKCE and, typically, dynamic client registration. Self-hosters mostly
don't run an identity provider, and requiring one would break "one container, easy to run"
(A§2 principle 4). The MCP endpoint gives an external AI read and write access to personal
data, so authorization must be scoped, consented and revocable (S§7.7).

## Options considered

1. **Built-in authorization server.** Works out of the box with standard connectors; full
   control of scopes, consent and 2FA. More security-critical code to write and test.
2. **External identity provider (Authentik, Keycloak, etc.).** Mature OAuth implementations.
   A large extra deployment for most users; consent and scope rules end up split across
   systems.
3. **Static API keys for MCP.** Simple. Not supported by standard connectors, no per-client
   consent, and long-lived bearer secrets pasted into third-party UIs.

## Decision

PlanHaven includes its own **OAuth 2.1 authorization server** (A§12.2):

- Authorization code flow with **PKCE S256 required** and exact-match redirect URIs.
- Discovery metadata at `/.well-known/oauth-authorization-server`, plus protected-resource
  metadata for `/mcp`.
- Dynamic client registration is enabled but rate-limited. A registered client has no access
  until a user approves it.
- Consent shows the client name, redirect host and scopes, and requires 2FA step-up.
- Scopes are `projects:read` and `projects:write`. Tokens are audience-bound to `/mcp`.
- Access tokens last 1 hour. Refresh tokens are rotated on use; reusing one revokes the whole
  token family.
- Users can list and revoke connected clients.

## Consequences

- Connectors work with no extra infrastructure; there is no API-key or anonymous mode.
- The OAuth server is security-critical. It needs threat-model entries, rate limits (S§7.11),
  audit events (S§7.12) and tests against the OAuth 2.1 security best-practice rules.
- Tokens follow the prefix scheme (`phv_oat_`, `phv_ort_`) and are hashed at rest (S§7.3).
- Built in phase 0.6. Before then there is no `/mcp` endpoint at all.
- If an operator enables OIDC login (S§7.1), it is used to sign the user in; PlanHaven still
  issues the MCP tokens.
