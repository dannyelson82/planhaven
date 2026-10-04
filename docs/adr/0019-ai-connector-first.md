# ADR 0019: The AI connector comes next; how its writes and visibility work

- **Status:** Accepted
- **Date:** 2026-10-04
- **Changes:** roadmap (ARCHITECTURE.md §18) order and numbering; refines ADR 0007 and A§12

## Context

After phase 0.3, the maintainer postponed the time planner ("I want to flesh it out more") and
made the MCP connector (ADR 0007, A§12) the focus, ahead of local AI. Release versions must keep
increasing, so the roadmap is renumbered to the order things will ship.

ADR 0007 settled the OAuth server; A§12 lists the v1 tools. Still open were what an AI's
changes do, which projects it sees, and how to build it.

## Decision

**Roadmap (ARCHITECTURE.md §18):** 0.4 MCP connector (was 0.6), 0.5 Local AI (unchanged),
0.6 Time planner (was 0.4; postponed until the maintainer brings it back), 0.7 Cut-list plugin
(unchanged). Older ADRs keep the numbers they were written with; this one maps them.

**Writes, per connection (maintainer, 2026-10-04):** at consent the person chooses, for that AI
app, either
- **approve first** (the default): the AI's changes wait in an "AI suggestions" list in
  PlanHaven and nothing changes until the person approves them; or
- **apply with undo**: changes happen at once, marked with the AI app's name, each undoable
  from the project's activity.

Either way, a read-only connection can be chosen at consent, and the mode can be changed later
in Account.

**Visibility:** a connection sees all the projects its person can see, except those marked
`local_ai_only` (A§12.4). No per-project picking for now.

**Clients:** any app following the MCP standard (Streamable HTTP, OAuth 2.1 with PKCE and
dynamic client registration), tested with Claude.

**Search:** keyword search (PostgreSQL full-text) over titles, tasks, notes, lists and contacts;
meaning-based search comes with local AI (0.5).

**Build:** both the OAuth authorization server and the MCP endpoint are written in PlanHaven,
with no new dependencies (the maintainer's choice over the official MCP package and Authlib).
Tokens use the existing 256-bit random keys and SHA-256 hashing (§7.3); no new cryptography. The
OAuth code is tested against the OAuth 2.1 security best practices (RFC 9700): exact redirect
URIs, PKCE S256 only, single-use short-lived codes, refresh-token rotation with reuse detection,
audience-bound tokens, no tokens in URLs.

## Consequences

- New attack surface reachable from the internet (the AI app's servers call `/mcp` and the
  OAuth endpoints): threat-model rows, rate limits per client, audit events, and the authz
  matrix get `oauth` and `mcp` access classes.
- An "AI suggestions" inbox and undo for AI writes are new pieces of the app.
- The `assistant.mcp_write` experimental feature (ADR 0012) keeps the wider write tools
  (contacts, quotes, costs, stages) for later; the v1 tools of A§12.3 are core.

## As built (v0.4.0, 2026-10-04)

The three milestones shipped together as v0.4.0 (maintainer's request). Differences from the
plan above:

- **Search** is a case-insensitive substring search (`ILIKE`, escaped) over project titles and
  descriptions, tasks, notes and list items; contacts aren't searched yet. Full-text ranking can
  replace it without changing the tool.
- **Undo** lives on the new **AI** page ("Recent AI changes"), next to the suggestions waiting
  for approval, rather than in a project activity view (there isn't one yet).
- **Authz matrix:** the OAuth endpoints apps call from their servers (register, token, revoke,
  discovery, authorize) are `public` (they read no cookies, so cross-site calls carry no
  ambient authority); `/mcp` has its own `mcp` class (an access token only; sessions get 401).
- **Notifications:** a new "AI apps" group for suggestions (at most one alert per app per
  hour), and a security notification when an app is connected.
