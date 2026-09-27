"""Foundation: RLS helper functions, audit log, event outbox.

Every user-content table in Planhaven follows the pattern set here (ARCHITECTURE.md §8.3,
ADR 0004): owned by planhaven_owner, ROW LEVEL SECURITY enabled *and* forced, explicit
per-command grants to planhaven_app, and policies that fail closed when no identity is set.

Revision ID: 0001
Revises:
Create Date: 2026-09-27
"""

import re

from alembic import op


def execute_script(sql: str) -> None:
    """Run a block of statements one at a time (asyncpg executes a single statement per
    call). Statements end with ';' at the end of a line; function bodies stay on one line."""
    for statement in re.split(r";\s*\n", sql):
        if statement.strip():
            op.execute(statement)


revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The version table is readable by the app so /readyz can check it's migrated.
    op.execute("GRANT SELECT ON alembic_version TO planhaven_app")

    # ---------------------------------------------------------------- identity helpers
    execute_script("""
        CREATE SCHEMA app AUTHORIZATION planhaven_owner;
        REVOKE ALL ON SCHEMA app FROM PUBLIC;
        GRANT USAGE ON SCHEMA app TO planhaven_app;

        -- The user the current transaction acts for, or NULL (never an error) if unset.
        CREATE FUNCTION app.current_user_id() RETURNS uuid
            LANGUAGE sql STABLE PARALLEL SAFE
            SET search_path = pg_catalog
            AS $$ SELECT nullif(current_setting('app.user_id', true), '')::uuid $$;

        -- True only inside Database.system_transaction().
        CREATE FUNCTION app.is_system() RETURNS boolean
            LANGUAGE sql STABLE PARALLEL SAFE
            SET search_path = pg_catalog
            AS $$ SELECT coalesce(current_setting('app.system', true), '') = 'true' $$;

        REVOKE ALL ON FUNCTION app.current_user_id(), app.is_system() FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app.current_user_id(), app.is_system() TO planhaven_app;
    """)

    # ---------------------------------------------------------------- audit log
    # Append-only for the app: INSERT and SELECT only, no UPDATE/DELETE/TRUNCATE
    # (SECURITY.md §7.12). Visibility is widened to project members with projects (step 9).
    execute_script("""
        CREATE TABLE audit_events (
            id            uuid PRIMARY KEY DEFAULT uuidv7(),
            occurred_at   timestamptz NOT NULL DEFAULT now(),
            actor_user_id uuid,
            actor_client  text NOT NULL CHECK (length(actor_client) <= 200),
            action        text NOT NULL CHECK (length(action) <= 100),
            resource_type text CHECK (length(resource_type) <= 100),
            resource_id   uuid,
            project_id    uuid,
            ip            inet,
            details       jsonb NOT NULL DEFAULT '{}'::jsonb
        );
        CREATE INDEX audit_events_actor_idx ON audit_events (actor_user_id, occurred_at);
        CREATE INDEX audit_events_project_idx ON audit_events (project_id, occurred_at);

        ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY;
        ALTER TABLE audit_events FORCE ROW LEVEL SECURITY;

        CREATE POLICY audit_insert ON audit_events FOR INSERT TO planhaven_app
            WITH CHECK (
                app.is_system()
                OR (actor_user_id IS NOT NULL AND actor_user_id = app.current_user_id())
            );
        CREATE POLICY audit_select_own ON audit_events FOR SELECT TO planhaven_app
            USING (actor_user_id IS NOT NULL AND actor_user_id = app.current_user_id());

        REVOKE ALL ON audit_events FROM PUBLIC;
        GRANT SELECT, INSERT ON audit_events TO planhaven_app;
    """)

    # ---------------------------------------------------------------- event outbox
    # Domain events written in the same transaction as the change (ARCHITECTURE.md §8.4).
    # Users may only append events for themselves; only system context reads or marks them.
    execute_script("""
        CREATE TABLE events (
            id           uuid PRIMARY KEY DEFAULT uuidv7(),
            created_at   timestamptz NOT NULL DEFAULT now(),
            type         text NOT NULL CHECK (length(type) <= 100),
            user_id      uuid,
            project_id   uuid,
            payload      jsonb NOT NULL DEFAULT '{}'::jsonb,
            processed_at timestamptz
        );
        CREATE INDEX events_unprocessed_idx ON events (created_at) WHERE processed_at IS NULL;

        ALTER TABLE events ENABLE ROW LEVEL SECURITY;
        ALTER TABLE events FORCE ROW LEVEL SECURITY;

        CREATE POLICY events_insert ON events FOR INSERT TO planhaven_app
            WITH CHECK (
                app.is_system() OR (user_id IS NOT NULL AND user_id = app.current_user_id())
            );
        CREATE POLICY events_system_select ON events FOR SELECT TO planhaven_app
            USING (app.is_system());
        CREATE POLICY events_system_update ON events FOR UPDATE TO planhaven_app
            USING (app.is_system()) WITH CHECK (app.is_system());

        REVOKE ALL ON events FROM PUBLIC;
        GRANT SELECT, INSERT ON events TO planhaven_app;
        GRANT UPDATE (processed_at) ON events TO planhaven_app;
    """)


def downgrade() -> None:
    raise NotImplementedError("Downgrades are not supported; restore from backup.")
