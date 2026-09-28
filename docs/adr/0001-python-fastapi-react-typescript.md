# ADR 0001: Python/FastAPI backend, React/TypeScript/Vite frontend

- **Status:** Accepted
- **Date:** 2026-09-26

## Context

PlanHaven needs a web API, a PWA frontend, document extraction (PDF, Office, OCR), local and
commercial AI integration, an MCP server and an OAuth 2.1 authorization server. It is built
and maintained by a very small team, so a mature ecosystem with active security maintenance
matters more than raw performance (A§2 principle 6).

## Options considered

1. **Python + FastAPI.** Strongest document and AI ecosystem, official MCP Python SDK,
   Pydantic validation at every boundary, OpenAPI generated from code. Slower than compiled
   languages, and dynamic typing needs discipline (type checking in CI).
2. **TypeScript/Node end to end.** One language front and back, official MCP TypeScript SDK.
   Weaker document-extraction and OCR libraries; a larger, more churn-prone dependency tree.
3. **Go.** Fast, single static binary, small attack surface. Thinner document-extraction and
   AI ecosystem; slower development for this team.

Frontend: React + TypeScript + Vite (largest ecosystem, strong typing, static build with no
server-side rendering to secure) was chosen over server-rendered templates, which would make
the offline PWA (A§13.4) much harder.

## Decision

- Backend: Python 3.12+, FastAPI + Uvicorn, Pydantic v2, SQLAlchemy 2.x + Alembic (A§5).
- Frontend: React + TypeScript built with Vite to static assets, served by FastAPI; TanStack
  Query for data fetching; `vite-plugin-pwa` for the service worker.
- Backend layering `api → services → (authz, db, ai, files, sync)`, enforced by
  `import-linter` (A§6).

## Consequences

- One HTTP process serves the API, frontend, MCP endpoint, OAuth server and ICS feeds.
- Strict Pydantic models give explicit input limits and reject unknown fields (S§7.5).
- The frontend build must work under a strict CSP with no inline scripts or styles (S§7.10).
  This rules out some UI libraries; checked when choosing the component library (A§19.2).
- Python typing is enforced in CI (type checker plus lint) to compensate for dynamic typing.
- Parsers for untrusted documents run in a sandboxed subprocess, not in the app (S§7.6).
