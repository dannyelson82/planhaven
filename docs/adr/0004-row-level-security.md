# ADR 0004: Row-Level Security as a second enforcement layer

- **Status:** Accepted
- **Date:** 2026-09-26

## Context

Users of one instance are trusted not to attack the host, but not trusted to see each other's
unshared data (S§2). Insecure direct object references (IDOR), meaning reading another user's
project by changing an ID, are among the most common web-app vulnerabilities, and a single
missed check in one route is enough. Defense in depth (A§2 principle 2) requires that access
holds even if the app has a bug.

## Options considered

1. **App-layer authorization only.** One code path (`authz.require`), simple and fast to
   test. A single missed check, or a raw query, leaks data.
2. **App-layer authorization plus PostgreSQL Row-Level Security.** Two independent layers;
   the database fails closed. More complex migrations and policies; the transaction must
   carry the user context; RLS policy bugs are harder to debug.
3. **One database or schema per user.** Strong isolation, but sharing projects between users
   (A§7.5) becomes very hard.

## Decision

Enforce access in **both** layers (A§8.3, S§7.4):

- The service layer calls `authz.require(principal, action, resource)`, the single source of
  rules in `backend/app/authz/`.
- Every user-content table has `ENABLE` **and** `FORCE ROW LEVEL SECURITY`.
- Tables are owned by `planhaven_owner` (migrations only). The app and worker connect as
  `planhaven_app`, which owns nothing.
- Each transaction runs `SET LOCAL app.user_id = '<uuid>'`. Policies use `SECURITY DEFINER`
  helpers `app.can_read(project_id)` / `app.can_write(project_id)`.
- A missing `app.user_id` yields zero rows (fail closed).

## Consequences

- An authorization bug in a route becomes a failed query or an empty result, not a leak.
- Admins get no data access through RLS; admin is an operational role (A§7.5).
- CI tests assert RLS is enabled and forced on every user-content table (query `pg_class`),
  plus the route × role authz matrix (S§7.4, S§11).
- Every new table needs policies in the same migration. The `SECURITY DEFINER` helpers must
  set a fixed `search_path` and are reviewed as security-critical code.
- Connection pooling must never leak `app.user_id` between requests; `SET LOCAL` scopes it to
  the transaction.
