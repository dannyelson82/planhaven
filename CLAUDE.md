# CLAUDE.md

Guidance for Claude Code (and other AI agents) working in this repository.

## Project status

Planhaven is in the **design phase**: no application code yet. The source of truth is:

- `ARCHITECTURE.md`: how it's built and why (cited as A§n)
- `SECURITY.md`: threat model, controls, release criteria (cited as S§n)
- `docs/adr/`: decision records (ADRs 0001–0009 are decided but not yet written up; see A§19.1)
- `docs/repo-setup.md`: GitHub hardening checklist

Read the relevant sections before implementing anything. If code and docs disagree, stop and
ask; don't silently pick one. A change that departs from the design updates ARCHITECTURE.md
and/or adds an ADR in the same PR.

## Non-negotiables

Security is a baseline, not a phase (A§2). Every release meets S§11.

- **Authorization has one code path:** `authz.require(principal, action, resource)` in
  `backend/app/authz/`. Never write ad hoc permission checks.
- **Every user-content table** gets `ENABLE` **and** `FORCE ROW LEVEL SECURITY` with policies
  (A§8.3). The app role never owns tables. A missing `app.user_id` must return zero rows.
- **Every new route** gets entries in the authz test matrix (route × role × token type), or CI
  fails (S§7.4).
- Resources the principal can't read return **404, not 403**.
- Admins manage users, settings and plugins, and **cannot read other users' projects**.
- Validate all input with explicit limits (Pydantic). No raw SQL string building.
- Never log secrets, tokens, or user content.
- No new outbound network destinations unless documented in S§7.8.
- Retrieved documents and attachment text are **untrusted data** in AI prompts (S§7.7).
- Tokens use the `phv_<type>_...` format (see the secret-scanning regex in `docs/repo-setup.md`).

## Architecture rules

- Backend layering: `api → services → (authz, db, ai, files, sync)`. Routers don't touch the
  DB; services don't import from `api`. Enforced with `import-linter`.
- Plugins talk to the host **only** through `PluginContext`: async methods, serializable
  data only, imports from `sdk/python` only, never `backend/app/**` (A§14.2).
- Side effects go through domain events persisted in the outbox table (A§8.4).
- API: REST under `/api/v1`, cursor pagination (max 200), `If-Match` optimistic concurrency,
  `Idempotency-Key` on sync/MCP writes, RFC 9457 errors, UTC ISO 8601 timestamps (A§8.2).
- Prefer boring, well-maintained dependencies. Avoid AGPL dependencies until the license is
  decided (A§19.2). New dependencies need review for maintenance, license and CVEs; pin them
  with hashes.

## Stack

Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2 + Alembic, PostgreSQL + pgvector,
PostgreSQL-backed job queue (no Redis), React + TypeScript + Vite, s6-overlay, single Docker
image. Full table in A§5; layout in A§6.

## Style

- `.editorconfig`: LF, UTF-8, 2-space indent (4 for Python).
- Docs: plain, direct prose. Keep section numbering stable, since other docs cite it.
- Conventional commit messages (`docs:`, `feat:`, `fix:`, `chore:`, ...).

## Git workflow

- `main` is protected: work on a branch and open a PR. The PR template's security checklist
  must be filled in honestly.
- Commits **must be signed**. This clone is set up for SSH signing
  (`commit.gpgsign=true`, key `~/.ssh/id_ed25519_signing`). Never pass `--no-gpg-sign` or
  otherwise bypass signing. Check with `git log --show-signature -1`.
- Never force-push to `main` or rewrite pushed history.
- GitHub Actions: pin third-party actions to commit SHAs, least-privilege `permissions:`, no
  `pull_request_target` checking out untrusted code (S§8).

## Commands

None yet. Add build, lint and test commands here once `backend/` and `frontend/` have code.
