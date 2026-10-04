# Phase 0.4: AI connector (MCP)

> **Status:** Built (v0.4.0, all three milestones in one release) · **Planned with the maintainer:** 2026-10-04
> Scope: ARCHITECTURE.md §12, §18 (0.4); ADR 0007, 0019. Every release meets SECURITY.md §11.

**Goal:** a person connects an AI app they already use (any MCP app; tested with Claude) to their
own PlanHaven, safely: their own sign-in and second factor, scopes they choose, changes they
approve (or can undo), revocable at any time, never more than they can see themselves.

**Decided (2026-10-04, ADR 0019):** moved up from 0.6; writes "approve first" or "apply with
undo", chosen per connection (approve first by default); all the person's projects except
`local_ai_only` ones; keyword search for now; OAuth server and MCP endpoint written in
PlanHaven, no new dependencies.

Every milestone: RLS on new tables (and the `pg_class` test), authz matrix entries, audit
events, rate limits, browser tests at phone and desktop widths, threat-model check, user guide
and screenshots, a What's new entry.

## Milestone 1: Sign-in for AI apps (v0.4.0)

- [x] OAuth 2.1 authorization server (ADR 0007): discovery metadata, dynamic client registration
      (rate limited, no access until approved), authorization code with PKCE S256 and exact
      redirect URIs, token endpoint, refresh-token rotation with reuse detection, revocation
- [x] Consent screen: the app's name and where it sends you back, read or read-and-write, and
      for writes "approve first" or "apply with undo"; a fresh second factor first
- [x] Account: connected AI apps, with their scope and mode, last use, change and disconnect
- [x] Tokens `phv_oat_` (1 hour, audience `/mcp`) and `phv_ort_` (30 days, rotated), hashed

## Milestone 2: Reading (v0.4.0)

- [x] `/mcp` (Streamable HTTP, stateless JSON-RPC): initialize, tools/list, tools/call;
      protected-resource metadata; 401 with the right `WWW-Authenticate` for discovery
- [x] Read tools: list projects, get a project (tasks, lists, notes, files' names), keyword search
- [x] `local_ai_only` projects invisible; tool output is data, with user content labelled

## Milestone 3: Changing things (v0.4.0)

- [x] Write tools (A§12.3): create/update a project, add a note, add tasks, add list items,
      complete a task
- [x] "Approve first": an AI suggestions list (a notification, approve one or all, decline)
- [x] "Apply with undo": changes marked with the app's name; Undo on the AI page
- [x] Notes from AI have `source = mcp:<app>`; per-client rate limits on writes

## Wrap-up

- [ ] Phase security review against SECURITY.md §11 (OAuth best-practice checklist included)
