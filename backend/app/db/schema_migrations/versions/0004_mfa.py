"""Second factors: TOTP and recovery codes; step-up and attempt tracking on sessions
(SECURITY.md §7.1).

TOTP secrets are encrypted with the master key (never readable from a database dump alone);
recovery codes are stored as SHA-256 hashes of 80-bit random codes.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-27
"""

from app.db.schema_migrations.sqlscript import execute_script

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    execute_script("""
        ALTER TABLE sessions
            ADD COLUMN reauth_at timestamptz,
            ADD COLUMN mfa_failures integer NOT NULL DEFAULT 0;
        GRANT UPDATE (reauth_at, mfa_failures) ON sessions TO planhaven_app;

        CREATE TABLE totp_credentials (
            id               uuid PRIMARY KEY DEFAULT uuidv7(),
            user_id          uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
            secret_encrypted bytea NOT NULL CHECK (length(secret_encrypted) <= 256),
            confirmed_at     timestamptz,
            last_used_step   bigint,
            created_at       timestamptz NOT NULL DEFAULT now()
        );
        -- At most one confirmed and one pending (being set up) secret per user.
        CREATE UNIQUE INDEX totp_one_confirmed ON totp_credentials (user_id)
            WHERE confirmed_at IS NOT NULL;
        CREATE UNIQUE INDEX totp_one_pending ON totp_credentials (user_id)
            WHERE confirmed_at IS NULL;
        ALTER TABLE totp_credentials ENABLE ROW LEVEL SECURITY;
        ALTER TABLE totp_credentials FORCE ROW LEVEL SECURITY;
        CREATE POLICY totp_own ON totp_credentials FOR ALL TO planhaven_app
            USING (app.is_system() OR user_id = app.current_user_id())
            WITH CHECK (app.is_system() OR user_id = app.current_user_id());
        REVOKE ALL ON totp_credentials FROM PUBLIC;
        GRANT SELECT, INSERT, DELETE ON totp_credentials TO planhaven_app;
        GRANT UPDATE (secret_encrypted, confirmed_at, last_used_step) ON totp_credentials
            TO planhaven_app;

        CREATE TABLE recovery_codes (
            id         uuid PRIMARY KEY DEFAULT uuidv7(),
            user_id    uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
            code_hash  bytea NOT NULL CHECK (length(code_hash) = 32),
            used_at    timestamptz,
            created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE UNIQUE INDEX recovery_codes_hash_key ON recovery_codes (user_id, code_hash);
        ALTER TABLE recovery_codes ENABLE ROW LEVEL SECURITY;
        ALTER TABLE recovery_codes FORCE ROW LEVEL SECURITY;
        CREATE POLICY recovery_own ON recovery_codes FOR ALL TO planhaven_app
            USING (app.is_system() OR user_id = app.current_user_id())
            WITH CHECK (app.is_system() OR user_id = app.current_user_id());
        REVOKE ALL ON recovery_codes FROM PUBLIC;
        GRANT SELECT, INSERT, DELETE ON recovery_codes TO planhaven_app;
        GRANT UPDATE (used_at) ON recovery_codes TO planhaven_app;
    """)


def downgrade() -> None:
    raise NotImplementedError("Downgrades are not supported; restore from backup.")
