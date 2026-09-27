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

Use a **PostgreSQL-backed job queue**. `procrastinate` (MIT) is the candidate library; the
final library choice is confirmed when the worker is built in phase 0.1, and recorded here if
it changes.

## Consequences

- Jobs and domain events commit atomically with the change that caused them.
- No Redis to run, secure or back up.
- Jobs run with the RLS context of the user who caused them; system jobs use a narrowly
  scoped `app.system` context (A§8.3).
- Queue tables need vacuuming and indexes; job concurrency limits protect the database
  (S§7.11).
