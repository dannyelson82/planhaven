# ADR 0003: PostgreSQL job queue; no Redis

- **Status:** Accepted
- **Date:** 2026-09-26

## Context

The worker runs extraction, embeddings, notifications, recurrence, purges, backups and plugin
jobs (A§9). Jobs need retries, backoff, a dead-letter state, and must be enqueued reliably in
the same transaction as the change that caused them (outbox pattern, A§8.4). Everything must
fit in one container (ADR 0002).

## Options considered

1. **PostgreSQL table consumed with `SELECT … FOR UPDATE SKIP LOCKED`.** Transactional
   enqueue with the business write, no extra service, backed up with the database. Lower peak
   throughput than a dedicated broker; irrelevant at household scale.
2. **Redis + a queue library (RQ, Celery, arq).** Mature and fast. Another stateful service in
   the container, another thing to secure and back up, and no transactional enqueue with
   PostgreSQL.
3. **In-process scheduler only.** Simplest. Jobs are lost on restart; no retry or dead-letter
   visibility.

## Decision

Use a **PostgreSQL-backed job queue**, implemented in PlanHaven itself (a `jobs` table
claimed with `FOR UPDATE SKIP LOCKED`, retries with backoff, a dead state), rather than
`procrastinate`.

*Updated 2026-09-27, when the worker was built in phase 0.1:* `procrastinate` was the candidate
library. It was not adopted because it depends on the LGPL `psycopg` driver (we use `asyncpg`,
Apache-2.0; ADR 0010) and manages its own connections. Every job must run inside
`Database.user_transaction()` or `system_transaction()` so Row-Level Security applies (ADR
0004); that is simpler to guarantee and test in a small amount of code we own. The cost is
maintaining the queue ourselves.

## Consequences

- Jobs and domain events commit atomically with the change that caused them.
- No Redis to run, secure or back up.
- Jobs run with the RLS context of the user who caused them; system jobs use a narrowly
  scoped `app.system` context (A§8.3).
- Queue tables need vacuuming and indexes; job concurrency limits protect the database
  (S§7.11).
