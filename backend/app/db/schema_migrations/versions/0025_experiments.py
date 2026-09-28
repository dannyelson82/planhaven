"""Experimental features (ADR 0012; owner request, 2026-09-28).

`experiments` holds the admin's choices: the master switch (the row named "experimental")
and which features are available; only the system context reads or writes it (the admin API
runs there after its step-up check). `experiment_optins` is each person's own opt-in to an
available feature.

Revision ID: 0025
Revises: 0024
Create Date: 2026-09-28
"""

from app.db.schema_migrations.sqlscript import execute_script

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    execute_script("""
        CREATE TABLE experiments (
            name       text PRIMARY KEY CHECK (name ~ '^[a-z][a-z0-9_.]{1,59}$'),
            available  boolean NOT NULL DEFAULT false,
            changed_by uuid REFERENCES users (id) ON DELETE SET NULL,
            changed_at timestamptz NOT NULL DEFAULT now()
        );
        ALTER TABLE experiments ENABLE ROW LEVEL SECURITY;
        ALTER TABLE experiments FORCE ROW LEVEL SECURITY;
        CREATE POLICY experiments_system ON experiments FOR ALL TO planhaven_app
            USING (app.is_system()) WITH CHECK (app.is_system());
        REVOKE ALL ON experiments FROM PUBLIC;
        GRANT SELECT, INSERT, UPDATE ON experiments TO planhaven_app;

        CREATE TABLE experiment_optins (
            user_id    uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
            name       text NOT NULL CHECK (name ~ '^[a-z][a-z0-9_.]{1,59}$'),
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (user_id, name)
        );
        ALTER TABLE experiment_optins ENABLE ROW LEVEL SECURITY;
        ALTER TABLE experiment_optins FORCE ROW LEVEL SECURITY;
        CREATE POLICY experiment_optins_own ON experiment_optins FOR ALL TO planhaven_app
            USING (user_id = app.current_user_id())
            WITH CHECK (user_id = app.current_user_id());
        REVOKE ALL ON experiment_optins FROM PUBLIC;
        GRANT SELECT, INSERT, DELETE ON experiment_optins TO planhaven_app;
    """)


def downgrade() -> None:
    raise NotImplementedError("Downgrades are not supported; restore from backup.")
