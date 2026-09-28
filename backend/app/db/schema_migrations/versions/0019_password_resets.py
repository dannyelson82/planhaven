"""Password reset links, made by an admin for one person (SECURITY.md §7.1).

`BASE_URL/reset#phv_rst_<token>`: 256-bit token in the URL fragment (never sent to servers
or logs), stored only as a hash, single use, valid 24 hours. A new link for the same person
cancels the older ones. Only the system context touches this table.

Revision ID: 0019
Revises: 0018
Create Date: 2026-09-28
"""

from app.db.schema_migrations.sqlscript import execute_script

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    execute_script("""
        CREATE TABLE password_resets (
            id         uuid PRIMARY KEY DEFAULT uuidv7(),
            user_id    uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
            token_hash bytea NOT NULL CHECK (length(token_hash) = 32),
            created_by uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
            created_at timestamptz NOT NULL DEFAULT now(),
            expires_at timestamptz NOT NULL,
            used_at    timestamptz,
            revoked_at timestamptz
        );
        CREATE UNIQUE INDEX password_resets_token_key ON password_resets (token_hash);
        CREATE INDEX password_resets_user_idx ON password_resets (user_id);
        ALTER TABLE password_resets ENABLE ROW LEVEL SECURITY;
        ALTER TABLE password_resets FORCE ROW LEVEL SECURITY;
        CREATE POLICY password_resets_system ON password_resets FOR ALL TO planhaven_app
            USING (app.is_system()) WITH CHECK (app.is_system());
        REVOKE ALL ON password_resets FROM PUBLIC;
        GRANT SELECT, INSERT ON password_resets TO planhaven_app;
        GRANT UPDATE (used_at, revoked_at) ON password_resets TO planhaven_app;
    """)


def downgrade() -> None:
    raise NotImplementedError("Downgrades are not supported; restore from backup.")
