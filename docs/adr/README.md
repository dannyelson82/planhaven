# Architecture decision records

One file per significant decision, numbered sequentially, using `0000-template.md`.
A decision is changed by adding a new ADR that supersedes the old one, not by rewriting it.

| ADR | Decision | Status |
|---|---|---|
| [0001](0001-python-fastapi-react-typescript.md) | Python/FastAPI backend, React/TypeScript/Vite frontend | Accepted |
| [0002](0002-all-in-one-container.md) | All-in-one container (s6-overlay) with bundled PostgreSQL + pgvector | Accepted |
| [0003](0003-postgres-job-queue.md) | PostgreSQL job queue; no Redis | Accepted |
| [0004](0004-row-level-security.md) | Row-Level Security as a second enforcement layer | Accepted |
| [0005](0005-project-entity-and-assets.md) | Single Project entity with stages; Assets as first-class | Accepted |
| [0006](0006-iphone-integration-web-standards.md) | iPhone integration via Shortcuts, ICS, Web Push, PWA | Accepted |
| [0007](0007-builtin-oauth-server-for-mcp.md) | Built-in OAuth 2.1 authorization server for MCP | Accepted |
| [0008](0008-plugins-in-process-isolation-ready.md) | Plugins: trusted in-process v1, isolation-ready boundary, sandboxed iframe UIs | Accepted |
| [0009](0009-behind-existing-reverse-proxy.md) | Behind the user's existing reverse proxy; no forward-auth | Accepted |
| [0010](0010-license-apache-2.md) | Apache-2.0 license and dependency license policy | Accepted |
| [0011](0011-realtime-collaboration.md) | Real-time collaborative editing with Yjs over authenticated WebSockets | Accepted; paused for notes by 0016 |
| [0012](0012-ai-assistant-and-experimental-features.md) | AI project assistant (local and commercial) behind experimental feature flags | Accepted |
| [0013](0013-chores-and-time-planner.md) | Household chores with proof; personal time planner; cut-list plugin moved to 0.7 | Accepted |
| [0014](0014-ui-toolkit-react-aria-tailwind.md) | UI toolkit: React Aria Components with Tailwind CSS | Accepted |
| [0015](0015-external-share-links.md) | External share links with per-component permissions | Accepted |
| [0016](0016-notes-save-on-done.md) | Notes saved on Done; live co-editing paused | Accepted |
| [0017](0017-project-page-tiles.md) | Project pages arranged as tiles, per person | Accepted |
| [0018](0018-notifications-messages-presence.md) | Notifications screen, messages between users, online status | Accepted |
| [0019](0019-ai-connector-first.md) | The AI connector comes next (roadmap renumbered); per-connection write mode | Accepted |
