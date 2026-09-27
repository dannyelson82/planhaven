"""Job queue and worker heartbeats (ADR 0003).

Users may enqueue jobs for themselves (in the same transaction as the change that caused
them) but can't read or change the queue; only the worker, in system context, claims and
updates jobs. The worker then runs each job's work as the job's user, so RLS still applies.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-27
"""

from app.db.schema_migrations.sqlscript import execute_script

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    execute_script("""
        CREATE TABLE jobs (
            id           uuid PRIMARY KEY DEFAULT uuidv7(),
            kind         text NOT NULL CHECK (length(kind) <= 100),
            payload      jsonb NOT NULL DEFAULT '{}'::jsonb,
            user_id      uuid,
            status       text NOT NULL DEFAULT 'queued'
                         CHECK (status IN ('queued', 'running', 'done', 'dead')),
            attempts     integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
            max_attempts integer NOT NULL DEFAULT 5 CHECK (max_attempts BETWEEN 1 AND 20),
            run_after    timestamptz NOT NULL DEFAULT now(),
            locked_until timestamptz,
            last_error   text CHECK (length(last_error) <= 200),
            created_at   timestamptz NOT NULL DEFAULT now(),
            updated_at   timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX jobs_ready_idx ON jobs (run_after) WHERE status = 'queued';
        CREATE INDEX jobs_running_idx ON jobs (locked_until) WHERE status = 'running';

        ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;
        ALTER TABLE jobs FORCE ROW LEVEL SECURITY;

        CREATE POLICY jobs_insert ON jobs FOR INSERT TO planhaven_app
            WITH CHECK (
                status = 'queued' AND attempts = 0
                AND (app.is_system()
                     OR (user_id IS NOT NULL AND user_id = app.current_user_id()))
            );
        CREATE POLICY jobs_system_select ON jobs FOR SELECT TO planhaven_app
            USING (app.is_system());
        CREATE POLICY jobs_system_update ON jobs FOR UPDATE TO planhaven_app
            USING (app.is_system()) WITH CHECK (app.is_system());
        CREATE POLICY jobs_system_delete ON jobs FOR DELETE TO planhaven_app
            USING (app.is_system() AND status IN ('done', 'dead'));

        REVOKE ALL ON jobs FROM PUBLIC;
        GRANT SELECT, INSERT, DELETE ON jobs TO planhaven_app;
        GRANT UPDATE (status, attempts, run_after, locked_until, last_error, updated_at)
            ON jobs TO planhaven_app;

        CREATE TABLE worker_heartbeats (
            worker_id text PRIMARY KEY CHECK (length(worker_id) <= 100),
            seen_at   timestamptz NOT NULL DEFAULT now()
        );
        ALTER TABLE worker_heartbeats ENABLE ROW LEVEL SECURITY;
        ALTER TABLE worker_heartbeats FORCE ROW LEVEL SECURITY;
        CREATE POLICY heartbeats_system ON worker_heartbeats FOR ALL TO planhaven_app
            USING (app.is_system()) WITH CHECK (app.is_system());
        REVOKE ALL ON worker_heartbeats FROM PUBLIC;
        GRANT SELECT, INSERT, UPDATE, DELETE ON worker_heartbeats TO planhaven_app;
    """)


def downgrade() -> None:
    raise NotImplementedError("Downgrades are not supported; restore from backup.")
