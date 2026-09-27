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

- [x] Settings from environment (A§4.3); `PUBLIC_MODE` refuses insecure configuration (test)
- [x] Trusted-proxy client-IP resolution from `TRUSTED_PROXIES` only (S§7.11)
- [x] Security headers and CSP on every response (S§7.10) (test); also on 413 and 500 responses
- [x] Request IDs, JSON body-size limit, RFC 9457 error responses with no internals
- [x] Structured JSON logging with a redaction filter (test: no secrets or content in logs)

## Step 4: Database foundation

- [x] Roles `planhaven_owner` / `planhaven_app`; Alembic migrations run as owner (`migrate`
      s6 service); migrations ship inside the app package
- [x] RLS session setup: transaction-local `app.user_id` / `app.system`; helper functions
      with fixed `search_path`; no identity sees no rows (ADR 0004). The membership helpers
      `app.can_read` / `app.can_write` come with projects (step 9)
- [x] UUIDv7 primary keys (`uuidv7()` in PostgreSQL 18); common columns (`created_by`,
      `version`, `deleted_at`) come with the first user-content table (step 9)
- [x] Test: every table has RLS enabled **and** forced (`pg_class`); app role owns nothing
      and can't bypass RLS
- [x] `audit_events` (append-only for the app role) and `events` outbox tables
- [x] Database tests run locally (`planhaven-dev-db`) and in CI (`Database` job)
- [x] Job queue (ADR 0003, in-house) and the `worker` s6 service; worker heartbeat in `/readyz`
- [x] Master-key encryption helper (AES-256-GCM, HKDF per purpose, key IDs) (S§7.9)

## Step 5: Sign-in, part 1

- [x] One-time setup token printed at first boot (`setup-token` s6 service); expires on use
      or after 24 h (S§7.1)
- [x] Admin account creation with the setup token
- [x] Passwords: 12+ characters, bundled common/breached list (100k, SecLists),
      Argon2id (S§7.1)
- [x] Server-side sessions, `__Host-` cookie, rotation, idle/absolute timeouts (S§7.2)
- [x] CSRF token (HMAC of the session, never stored) + `Origin` check on state-changing
      requests
- [x] Identical responses and timing whether or not an account exists

## Step 6: Sign-in, part 2

- [x] TOTP enrollment + 10 hashed recovery codes; second factor mandatory for every account
      (password-only sessions reach nothing but the second factor); TOTP replay blocked;
      five wrong codes end the session
- [x] Passkeys (WebAuthn), including passkey-only sign-in; discoverable + user-verified;
      single-use challenges bound to the session; cloned-key (counter) detection; the last
      second factor can't be removed
- [x] Step-up re-authentication (5 minutes) for sensitive actions
- [x] Rate limits on sign-in, setup, passkey sign-in and second factor (per IP, per account
      per IP, per account overall, per user); token buckets in PostgreSQL; 429 + Retry-After.
      Lockout notifications to the account owner come with notifications (phase 0.3)
- [x] Security log (`/config/logs/security.log`) with a documented format; fail2ban filter
      and CrowdSec parser in `deploy/`, tested against real log lines
- [x] Session list and revocation; password change revokes other sessions

## Step 7: Invites and user management

- [x] Admin creates single-use, 72-hour `phv_inv_` invite links (token in the URL fragment,
      optionally bound to an email); no public registration
- [x] Admin user management: list, disable (signs out everywhere), grant/revoke admin, reset a
      lost second factor; last-admin and self-disable protection; every action needs step-up;
      `ADMIN_ALLOWED_CIDRS` makes the admin API answer 404 elsewhere
- [x] New sign-in notifications (new address in 30 days) and security-change notifications
      (in-app; push in phase 0.3)
- [ ] Later: admin-issued password reset links (no email server needed)

## Step 8: Authorization layer and test matrix

- [x] `authz.require(principal, action)` as the only permission path (S§7.4): one rules table
      (verified / step-up / admin); project resources join it in step 9
- [x] 404 (not 403) for resources the principal can't know about; one error mapping
- [x] Route × principal matrix (`backend/tests/authz_matrix.py`): a route without an entry
      fails CI; structural check of each route's guard; every route called as anonymous,
      password-only, stale, fresh, stale admin and fresh admin; CSRF and Origin checks on
      every unsafe route. Token principals get columns when tokens exist

## Step 9: Projects and tasks

- [x] Choose the UI component library (A§19.2): React Aria + Tailwind (ADR 0014); criteria include
      responsive and touch-friendly components, accessibility and CSP compatibility (A§13.5)
- [x] Projects: CRUD, stages, membership roles (owner/editor/viewer), RLS policies
      (membership enforced in RLS via `app.project_role`)
- [x] Tasks: CRUD, due dates, done state; assignee column + RLS visibility (chores, ADR 0013)
- [x] API conventions: cursor pagination, `If-Match` concurrency, soft delete (A§8.2)
- [x] Minimal UI: sign-in, 2FA enrollment, project list, project view with tasks;
      responsive for phone and desktop (A§13.5), checked at 390 px and 1280 px widths
      by Playwright browser tests against the container in CI (no CSP violations allowed)
- [x] Matrix entries and audit events for every new route; outbox events for stage changes
      and completed tasks

## Step 10: Plugin foundation

- [x] `sdk/python` (`planhaven_sdk`, API v1): manifest model, `PluginContext` protocol and
      serializable types; async only
- [x] Plugin host: `plugin.toml` discovery without importing, `api_version` check, admin
      enable/disable (takes effect on restart; only enabled plugins are imported), a broken
      plugin can't stop startup; `PluginContext` enforces manifest permissions and acts as the
      user under RLS; plugin data table with RLS (project- or user-scoped)
- [x] Boundary test: plugins and the SDK never import the application
- [ ] Later: deliver outbox events to plugin handlers (with the event consumer, phase 0.3);
      plugin UI iframes and the JS bridge (with the first plugin UI, phase 0.7)

## Step 11: Release

- [x] Nightly `pg_dump` backup with rotation; restore smoke test in CI (A§16);
      `docs/backup-restore.md`
- [x] Release workflow (on a `v*` tag): native multi-arch build, cosign keyless signature,
      SPDX SBOM attestation, build provenance, GitHub release with verify instructions
- [x] OWASP ZAP baseline scan against the test container (fails on high risk)
- [x] `unraid/planhaven.xml` template (hardening flags in Extra Parameters) and
      `deploy/proxy/nginx-proxy-manager/`
- [ ] Walk through the SECURITY.md §11 checklist; tag `v0.1.0`
- [ ] Install on Unraid and test end to end
