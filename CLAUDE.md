# CLAUDE.md

Guidance for Claude Code (and other AI agents) working in this repository.

## Project status

PlanHaven is building **phase 0.4, the AI connector** (checklist: `docs/roadmap/phase-0.4.md`; 0.1 to 0.3 are done; the roadmap was renumbered by ADR 0019). The source of truth is:

- `ARCHITECTURE.md`: how it's built and why (cited as A§n)
- `SECURITY.md`: threat model, controls, release criteria (cited as S§n)
- `docs/adr/`: decision records (ADRs 0001–0019; index in `docs/adr/README.md`)
- `docs/repo-setup.md`: GitHub hardening checklist

Read the relevant sections before implementing anything. If code and docs disagree, stop and
ask; don't silently pick one. A change that departs from the design updates ARCHITECTURE.md
and/or adds an ADR in the same PR.

## How to work

- **Follow the roadmap in phase order** (A§18). Don't start a later phase's features, or
  build ahead for them, until the current phase meets S§11. If something seems to need
  work from a later phase, raise it instead of building it.
- **Discuss design before writing code.** Plan a phase or feature with the maintainer first,
  and ask before big decisions: new dependencies, schema changes, security trade-offs, or
  anything that changes ARCHITECTURE.md or SECURITY.md.
- **Keep the user guide current.** Every feature added, changed or removed updates
  `docs/user-guide/` in the same PR (removed features are taken out of it): plain words,
  numbered steps, button names exactly as on screen, "On a phone" / "On a computer"
  sections where they differ. It's shown in the app (Help). When a screen changes, re-take
  the screenshots (`GUIDE_SHOTS=1 planhaven-e2e e2e/journey.spec.ts e2e/guide.spec.ts`, or
  `npm run guide-shots` against a fresh instance) and add new ones to `e2e/guide.spec.ts`.
- **Keep "What's new" current.** Every release with something people will notice adds an
  entry at the top of `frontend/src/whatsnew.ts` (its version, plain words, a short how-to,
  a "set it up now" action where it fits, and its guide page). The welcome tour's steps
  (`frontend/src/screens/Tour.tsx`) change when the basics change.
- **Keep changes small**: one logical change per commit and per PR. Write clear
  Conventional Commit messages that say what changed and why.
- **Never commit secrets**: no keys, tokens, passwords, `.env` files, or real credentials,
  not even in tests or examples. Use obviously fake placeholders (`phv_pat_EXAMPLE...`).
  Check `git diff --staged` before every commit.
- **Keep the maintainer's infrastructure out of the repo.** The repo may become public: no
  real server IPs, hostnames, domains, container names or network layout in committed files.
  Use `example.com` and RFC 5737 addresses (`192.0.2.x`) in docs. Local setup notes go in
  `.local/` (gitignored).

## Non-negotiables

Security is a baseline, not a phase (A§2). Every release meets S§11.

- **Authorization has one code path:** `authz.require(principal, action, resource)` in
  `backend/app/authz/`. Never write ad hoc permission checks.
- **Every user-content table** gets `ENABLE` **and** `FORCE ROW LEVEL SECURITY` with policies
  (A§8.3). The app role never owns tables. A missing `app.user_id` must return zero rows.
- **Every new route** gets an entry in `backend/tests/authz_matrix.py` (its access class and,
  if needed, a valid sample body), or CI fails (S§7.4). New routers go in `ROUTERS` in
  `backend/app/main.py`. Permission rules live only in `backend/app/authz/`.
- Resources the principal can't read return **404, not 403**.
- Admins manage users, settings and plugins, and **cannot read other users' projects**.
- Validate all input with explicit limits (Pydantic). No raw SQL string building.
- Never log secrets, tokens, or user content.
- No new outbound network destinations unless documented in S§7.8.
- Retrieved documents and attachment text are **untrusted data** in AI prompts (S§7.7).
- Tokens use the `phv_<type>_...` format (see the secret-scanning regex in `docs/repo-setup.md`);
  a new type must be added to that regex, `.gitleaks.toml` and the log redaction patterns.

## Architecture rules

- Backend layering: `api → services → (authz, db, ai, files, sync)`. Routers don't touch the
  DB; services don't import from `api`. Enforced with `import-linter`.
- Plugins talk to the host **only** through `PluginContext`: async methods, serializable
  data only, imports from `sdk/python` only, never `backend/app/**` (A§14.2).
- Side effects go through domain events persisted in the outbox table (A§8.4).
- API: REST under `/api/v1`, cursor pagination (max 200), `If-Match` optimistic concurrency,
  `Idempotency-Key` on sync/MCP writes, RFC 9457 errors, UTC ISO 8601 timestamps (A§8.2).
- Prefer boring, well-maintained dependencies. The project is Apache-2.0; dependencies must
  follow the license policy in ADR 0010 (no GPL, AGPL, SSPL or source-available licenses).
  New dependencies need review for maintenance, license and CVEs; pin them with hashes.

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

Backend (run in `backend/`; Python and dependencies are managed by `uv`, pinned in `uv.lock`):

```bash
uv sync --locked              # install exactly what uv.lock pins
uv run pytest                 # tests
uv run ruff check .           # lint (includes Bandit security rules)
uv run ruff format --check .  # formatting (drop --check to fix)
uv run mypy                   # strict type checks
uv run lint-imports           # layering contracts (A§6)
uv run pytest -m db           # database tests: need a PostgreSQL 18 + pgvector with the
                              # bootstrap SQL applied; set PLANHAVEN_DB_HOST/PLANHAVEN_DB_PORT
uv add <pkg>                  # add a dependency: review license (ADR 0010) and CVEs first
```

Frontend (run in `frontend/`; Node 24 LTS; `package-lock.json` pins versions and hashes):

```bash
npm ci                # install exactly what package-lock.json pins
npm test              # tests (Vitest)
npm run lint          # lint (oxlint, warnings fail)
npm run typecheck     # strict TypeScript
npm run build         # production build to dist/
npm run guide-shots   # re-take the user guide screenshots (docs/user-guide/screens/)
npm run e2e           # Playwright browser tests; needs a running instance
                      # (PLAYWRIGHT_BASE_URL, SETUP_TOKEN for a fresh one)
npm install -D <pkg>  # add a dependency: review license (ADR 0010) and CVEs first
```

`frontend/.npmrc` disables dependency install scripts and ignores packages published less than
7 days ago. Don't override either.
