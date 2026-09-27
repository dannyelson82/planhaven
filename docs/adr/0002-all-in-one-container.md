# ADR 0002: All-in-one container (s6-overlay) with bundled PostgreSQL + pgvector

- **Status:** Accepted
- **Date:** 2026-09-26

## Context

The primary audience installs apps on Unraid from Community Applications templates, which
deploy one container per template. Multi-container stacks (compose) are awkward there and are
a common source of misconfiguration. The app needs PostgreSQL with pgvector (RLS, ADR 0004;
vector search, A§11) plus an app server and a background worker (A§4).

## Options considered

1. **One image with the app, worker and PostgreSQL, supervised by s6-overlay.** One template,
   a few fields, works like other Unraid apps. PostgreSQL shares the container with the app,
   and major-version upgrades must be handled inside the image.
2. **Separate app and database containers (compose).** Cleaner isolation and standard
   PostgreSQL images. Harder to install on Unraid; users must wire networks, credentials and
   pgvector themselves.
3. **SQLite.** Simplest to ship. No Row-Level Security, weaker concurrency for app + worker,
   and no pgvector (vector search would need another extension).

## Decision

A single image supervised by **s6-overlay**, running `postgres`, `app` and `worker` services
plus one-shot init services (`init-secrets`, `init-db`, `migrate`, `setup-token`) (A§4.1).
Two volumes: `/config` (database, secrets, backups, logs) and `/data` (attachment blobs)
(A§4.2). One exposed port, 8080, behind a TLS-terminating reverse proxy (A§4.4, ADR 0009).

## Consequences

- Install is one template and a few settings (A§2 principle 4).
- PostgreSQL listens on a Unix socket only (`listen_addresses = ''`), runs as its own OS user,
  and is never exposed (S§7.13). Shared-container risk is accepted in S§10.
- The image must handle PostgreSQL major-version upgrades with a mandatory pre-upgrade dump
  (A§16).
- The image carries more software, so it gets Trivy scanning, SBOM and signing (S§8), and
  runs non-root with a minimal capability set confirmed during the build (S§7.13).
- A later option to use an external PostgreSQL is not excluded, but is not planned.
