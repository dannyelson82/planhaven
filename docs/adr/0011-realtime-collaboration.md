# ADR 0011: Real-time collaborative editing with a CRDT (Yjs) over authenticated WebSockets

- **Status:** Accepted
- **Date:** 2026-09-27
- **Changes:** ARCHITECTURE.md §1.2, which listed real-time co-editing as a non-goal.

## Context

The maintainer asked for real-time collaborative editing: several household members editing
the same note at once and seeing each other's changes and cursors, like a shared document.
Related: list and task changes (e.g. an item checked off on another phone) should appear on
other devices within a second or two.

Constraints: single container (ADR 0002), Python backend (ADR 0001), offline-capable PWA
(A§13.4), strict CSP (S§7.10), per-project roles where viewers must not edit (A§7.5), content
never logged (S§7.12), and AI writes via MCP must remain attributable and undoable (A§12.4).

## Options considered

1. **Last write wins with conflict detection** (the original design). Simple; no live
   co-editing.
2. **Operational transformation** (as in Google Docs). Proven, but needs a central server
   algorithm per editor type and handles offline edits poorly.
3. **CRDT with Yjs** (MIT). Changes from any device merge automatically in any order,
   including edits made offline, which suits the PWA. Mature editor bindings (CodeMirror,
   ProseMirror/TipTap). Server side in Python via `pycrdt` (MIT, Rust `yrs` bindings used by
   Jupyter). Costs: a WebSocket channel to secure, binary document state to store and compact,
   and a derived plain-text copy for search and AI.
4. **Hosted collaboration service or a Node sidecar** (e.g. Hocuspocus). Breaks the
   single-container, local-first design.

## Decision

Option 3.

- **Notes are Yjs documents.** The CRDT state is the source of truth; a Markdown rendering is
  derived on save for display fallback, search, AI retrieval and export.
- **Transport:** one authenticated WebSocket per open document at `/api/v1/collab/{doc_id}`,
  speaking the standard Yjs sync and awareness protocol. Lists and tasks use the same
  connection mechanism for live updates (server-pushed change notifications), without CRDT.
- **Offline:** Yjs state is cached in IndexedDB (`y-indexeddb`) and merges on reconnect.
- **Storage:** incremental updates appended to a table (RLS like any user content), compacted
  into snapshots by a worker job. Document history keeps attribution per update.
- **Editor:** chosen when notes are built (A§19.2). It must bind to Yjs and work under the
  CSP; editors that inject `<style>` at runtime need a per-response CSP nonce, decided then.
- **Timing:** built with notes in phase 0.2, after sign-in exists. No collaboration endpoint
  exists before authentication and authorization do.

Security rules (SECURITY.md §7.15):

- WebSocket handshake requires a valid session (cookie) or scoped token, **and** an `Origin`
  equal to `BASE_URL` (prevents cross-site WebSocket hijacking).
- Authorization is checked at connect through `authz.require`, and again whenever
  membership changes: removing someone from a project closes their open connections.
- Viewers receive updates but every update they send is rejected (server-side, not UI).
- Limits: message size, updates per second per connection, connections per user, document
  size; oversized or malformed updates close the connection.
- Awareness data (names, cursor positions) is relayed only to members of the same document
  and never stored.
- Document content and updates are never logged; logs record document ID, user and sizes.
- MCP and local-AI writes go through the server as CRDT updates attributed to the client
  (`source = mcp:<client>`), so they appear live and stay undoable.

## Consequences

- Real-time co-editing of notes and live list updates arrive in phase 0.2.
- New dependencies at that point: `yjs`, `y-protocols`, `y-indexeddb`, an editor binding
  (npm, MIT) and `pycrdt` (+ possibly `pycrdt-websocket`) (PyPI, MIT). Each is reviewed
  when added (ADR 0010).
- The reverse proxy must pass WebSocket upgrades; the proxy snippets in `deploy/` cover it.
- Search, AI retrieval and exports read the derived Markdown, never the binary CRDT state.
- A long-lived connection is a new attack surface: covered by the threat model entries and
  controls in SECURITY.md, and by tests (handshake without session or with a foreign Origin
  refused, viewer updates rejected, revoked member disconnected, limits enforced).
