"""Invites and in-app notifications (SECURITY.md §7.1, §7.12).

Invites are created by admins, work once, and expire after 72 hours; only a hash of the
token is stored. Admin operations run in system context after the service layer has checked
that the caller is an admin (admins manage accounts, never project data).

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-27
"""

from app.db.schema_migrations.sqlscript import execute_script

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    execute_script("""
        CREATE TABLE invites (
            id         uuid PRIMARY KEY DEFAULT uuidv7(),
            token_hash bytea NOT NULL CHECK (length(token_hash) = 32),
            email      text CHECK (email = lower(email) AND length(email) <= 254),
            created_by uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
            created_at timestamptz NOT NULL DEFAULT now(),
            expires_at timestamptz NOT NULL,
            used_at    timestamptz,
            used_by    uuid REFERENCES users (id) ON DELETE SET NULL,
            revoked_at timestamptz
        );
        CREATE UNIQUE INDEX invites_token_key ON invites (token_hash);
        ALTER TABLE invites ENABLE ROW LEVEL SECURITY;
        ALTER TABLE invites FORCE ROW LEVEL SECURITY;
        CREATE POLICY invites_system ON invites FOR ALL TO planhaven_app
            USING (app.is_system()) WITH CHECK (app.is_system());
        REVOKE ALL ON invites FROM PUBLIC;
        GRANT SELECT, INSERT, DELETE ON invites TO planhaven_app;
        GRANT UPDATE (used_at, used_by, revoked_at) ON invites TO planhaven_app;

        CREATE TABLE notifications (
            id         uuid PRIMARY KEY DEFAULT uuidv7(),
            user_id    uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
            kind       text NOT NULL CHECK (length(kind) <= 50),
            data       jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            read_at    timestamptz
        );
        CREATE INDEX notifications_user_idx ON notifications (user_id, created_at DESC);
        ALTER TABLE notifications ENABLE ROW LEVEL SECURITY;
        ALTER TABLE notifications FORCE ROW LEVEL SECURITY;
        CREATE POLICY notifications_own ON notifications FOR SELECT TO planhaven_app
            USING (app.is_system() OR user_id = app.current_user_id());
        CREATE POLICY notifications_own_update ON notifications FOR UPDATE TO planhaven_app
            USING (user_id = app.current_user_id()) WITH CHECK (user_id = app.current_user_id());
        CREATE POLICY notifications_insert ON notifications FOR INSERT TO planhaven_app
            WITH CHECK (app.is_system() OR user_id = app.current_user_id());
        REVOKE ALL ON notifications FROM PUBLIC;
        GRANT SELECT, INSERT ON notifications TO planhaven_app;
        GRANT UPDATE (read_at) ON notifications TO planhaven_app;
    """)


def downgrade() -> None:
    raise NotImplementedError("Downgrades are not supported; restore from backup.")
