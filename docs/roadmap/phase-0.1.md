# Phase 0.1: Secure foundation

> **Status:** In progress · **Started:** 2026-09-27
> Scope: ARCHITECTURE.md §18. Exit criteria: every item in SECURITY.md §11.

**Goal:** a Planhaven that can be installed on Unraid and safely exposed to the internet, doing
only the basics: secure sign-in, then projects and tasks. Security controls are built first;
features come last.

Each step lands as one or more small pull requests. Tick items off in the PR that completes
them. Every PR gets a security review before merge.

## Step 1: Project skeleton and CI gates

- [x] Backend skeleton in `backend/`: `pyproject.toml` managed with **uv** (lockfile with
      hashes), FastAPI app with `GET /healthz` and a test
- [x] Python tooling: **ruff** (lint + format), **mypy** (strict type checks), **pytest**;
      Python version: newest release all planned dependencies support
- [x] `import-linter` contracts for the backend layering (A§6)
- [x] Frontend skeleton in `frontend/`: Vite + React + TypeScript, **oxlint**, **Vitest**,
      `package-lock.json`; npm install scripts disabled, 7-day minimum package age
- [x] `ci.yml`: lint, type-check and tests for backend and frontend
- [x] `security.yml`: CodeQL, Bandit, Semgrep, `pip-audit`, `npm audit`, Gitleaks (with a
      rule for `phv_` tokens), dependency license check against the ADR 0010 policy
- [x] Actions pinned to commit SHAs; least-privilege `permissions:`; workflows audited by zizmor
- [x] Dependabot config for uv, npm and GitHub Actions (Docker added in step 2)
- [x] Add the CI and security checks as **required status checks** in the "Protect main"
      ruleset
- [x] Commands documented in `CLAUDE.md`

## Step 2: Container

- [x] Multi-stage `Dockerfile`; s6-overlay services `init-dirs`, `init-secrets`, `init-db`,
      `postgres`, `db-bootstrap`, `app` (A§4). `worker`, `migrate` and `setup-token` are added
      in steps 4 and 5, with the code they run
- [x] PostgreSQL 18 + pgvector on a Unix socket only; runs as its own user; refuses to start
      on a different major version (automatic upgrade with pre-upgrade dump: later, A§16)
- [x] Non-root app (PUID:PGID); minimal capability set confirmed in CI and documented;
      read-only root FS (S§7.13)
- [x] `init-secrets` creates master key, session key and VAPID keys with `0600` permissions
- [x] `/healthz` and `/readyz` (database check); Docker `HEALTHCHECK`
- [x] `image.yml`: native amd64 and arm64 builds, smoke test with hardening flags, Trivy
      scan (fail on fixable critical) and Dockerfile scan
- [x] Add `Image (amd64)` and `Image (arm64)` as required status checks

## Step 3: Core safety layer

- [ ] Settings from environment (A§4.3); `PUBLIC_MODE` refuses insecure configuration (test)
- [ ] Trusted-proxy client-IP resolution from `TRUSTED_PROXIES` only (S§7.11)
- [ ] Security headers and CSP on every response (S§7.10) (test)
- [ ] Request IDs, JSON body-size limit, RFC 9457 error responses with no internals
- [ ] Structured JSON logging with a redaction filter (test: no secrets or content in logs)

## Step 4: Database foundation

- [ ] Roles `planhaven_owner` / `planhaven_app`; Alembic migrations run as owner
- [ ] RLS session setup (`SET LOCAL app.user_id`); `app.can_read` / `app.can_write` helpers
      with fixed `search_path` (ADR 0004)
- [ ] UUIDv7 keys; common columns (`created_at`, `updated_at`, `created_by`, `version`,
      `deleted_at`)
- [ ] Test: every user-content table has RLS enabled **and** forced (`pg_class`)
- [ ] `audit_events` (append-only for the app role) and `events` outbox tables
- [ ] Job queue (ADR 0003) and the `worker` s6 service; `migrate` s6 service running Alembic
- [ ] Master-key encryption helper (AES-256-GCM, HKDF per purpose, key IDs) (S§7.9)

## Step 5: Sign-in, part 1

- [ ] One-time setup token printed at first boot (`setup-token` s6 service); expires on use
      or after 24 h (S§7.1)
- [ ] Admin account creation with the setup token
- [ ] Passwords: 12+ characters, bundled common/breached list, Argon2id (S§7.1)
- [ ] Server-side sessions, `__Host-` cookie, rotation, idle/absolute timeouts (S§7.2)
- [ ] CSRF token + `Origin` check on state-changing requests
- [ ] Identical responses and timing whether or not an account exists

## Step 6: Sign-in, part 2

- [ ] TOTP enrollment + 10 hashed recovery codes; second factor mandatory for every account
- [ ] Passkeys (WebAuthn), including passkey-only sign-in
- [ ] Step-up re-authentication (5 minutes) for sensitive actions
- [ ] Rate limits on sign-in and 2FA (per IP and per account); progressive lockout (S§7.11)
- [ ] Security log (`/config/logs/security.log`) with a documented format; fail2ban filter
      and CrowdSec parser in `deploy/`
- [ ] Session list and revocation; password change revokes other sessions

## Step 7: Invites and user management

- [ ] Admin creates single-use, 72-hour `phv_inv_` invite links; no public registration
- [ ] Admin user management; `ADMIN_ALLOWED_CIDRS` restriction
- [ ] New sign-in notifications (in-app for now)

## Step 8: Authorization layer and test matrix

- [ ] `authz.require(principal, action, resource)` as the only permission path (S§7.4)
- [ ] 404 (not 403) for resources the principal can't read
- [ ] Route × role × token-type test matrix; a route without matrix entries fails CI

## Step 9: Projects and tasks

- [ ] Choose the UI component library (A§19.2) and record it in an ADR; criteria include
      responsive and touch-friendly components, accessibility and CSP compatibility (A§13.5)
- [ ] Projects: CRUD, stages, membership roles (owner/editor/viewer), RLS policies
- [ ] Tasks: CRUD, due dates, assignee, done state
- [ ] API conventions: cursor pagination, `If-Match` concurrency, soft delete (A§8.2)
- [ ] Minimal UI: sign-in, 2FA enrollment, project list, project view with tasks;
      responsive for phone and desktop (A§13.5), checked at 390 px and 1280 px widths
- [ ] Matrix entries and audit events for every new route

## Step 10: Plugin foundation

- [ ] `sdk/python`: `PluginContext` protocol and types (async, serializable)
- [ ] Plugin loader: `plugin.toml` manifest, `api_version` check, admin enable/disable
- [ ] `import-linter` contract: plugins import only the SDK

## Step 11: Release

- [ ] Nightly `pg_dump` backup with rotation; restore smoke test in CI (A§16)
- [ ] Image signed with cosign (keyless), SBOM attached, provenance attestation
- [ ] OWASP ZAP baseline scan against a test container
- [ ] `unraid/planhaven.xml` template and a reverse-proxy snippet for Nginx Proxy Manager
- [ ] Walk through the SECURITY.md §11 checklist; tag `v0.1.0`
- [ ] Install on Unraid and test end to end
