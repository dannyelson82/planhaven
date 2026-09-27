"""Plugins: which are enabled, and their namespaced data (ARCHITECTURE.md §14.5).

Plugins don't create tables. Their JSON documents live in plugin_data, scoped to a project or a
user, under the same RLS as everything else: project-scoped data follows project membership,
user-scoped data is private to that user.

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-27
"""

from app.db.schema_migrations.sqlscript import execute_script

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    execute_script("""
        CREATE TABLE plugin_states (
            plugin_id  text PRIMARY KEY CHECK (plugin_id ~ '^[a-z][a-z0-9_]{1,39}$'),
            enabled    boolean NOT NULL DEFAULT false,
            changed_by uuid REFERENCES users (id) ON DELETE SET NULL,
            changed_at timestamptz NOT NULL DEFAULT now()
        );
        ALTER TABLE plugin_states ENABLE ROW LEVEL SECURITY;
        ALTER TABLE plugin_states FORCE ROW LEVEL SECURITY;
        CREATE POLICY plugin_states_system ON plugin_states FOR ALL TO planhaven_app
            USING (app.is_system()) WITH CHECK (app.is_system());
        REVOKE ALL ON plugin_states FROM PUBLIC;
        GRANT SELECT, INSERT, UPDATE ON plugin_states TO planhaven_app;

        CREATE TABLE plugin_data (
            plugin_id  text NOT NULL CHECK (plugin_id ~ '^[a-z][a-z0-9_]{1,39}$'),
            scope      text NOT NULL CHECK (scope IN ('project', 'user')),
            scope_id   uuid NOT NULL,
            key        text NOT NULL CHECK (length(key) BETWEEN 1 AND 100),
            value      jsonb NOT NULL,
            updated_by uuid NOT NULL REFERENCES users (id),
            updated_at timestamptz NOT NULL DEFAULT now(),
            version    integer NOT NULL DEFAULT 1,
            PRIMARY KEY (plugin_id, scope, scope_id, key),
            CHECK (octet_length(value::text) <= 65536)
        );
        ALTER TABLE plugin_data ENABLE ROW LEVEL SECURITY;
        ALTER TABLE plugin_data FORCE ROW LEVEL SECURITY;
        CREATE POLICY plugin_data_select ON plugin_data FOR SELECT TO planhaven_app
            USING ((scope = 'project' AND app.can_read(scope_id))
                   OR (scope = 'user' AND scope_id = app.current_user_id()));
        CREATE POLICY plugin_data_insert ON plugin_data FOR INSERT TO planhaven_app
            WITH CHECK (updated_by = app.current_user_id()
                        AND ((scope = 'project' AND app.can_write(scope_id))
                             OR (scope = 'user' AND scope_id = app.current_user_id())));
        CREATE POLICY plugin_data_update ON plugin_data FOR UPDATE TO planhaven_app
            USING ((scope = 'project' AND app.can_write(scope_id))
                   OR (scope = 'user' AND scope_id = app.current_user_id()))
            WITH CHECK (updated_by = app.current_user_id()
                        AND ((scope = 'project' AND app.can_write(scope_id))
                             OR (scope = 'user' AND scope_id = app.current_user_id())));
        REVOKE ALL ON plugin_data FROM PUBLIC;
        GRANT SELECT, INSERT ON plugin_data TO planhaven_app;
        GRANT UPDATE (value, updated_by, updated_at, version) ON plugin_data TO planhaven_app;
    """)


def downgrade() -> None:
    raise NotImplementedError("Downgrades are not supported; restore from backup.")
