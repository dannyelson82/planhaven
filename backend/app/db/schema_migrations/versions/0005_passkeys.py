"""Passkeys (WebAuthn) and their one-time challenges (SECURITY.md §7.1); system-context read
access to the audit log.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-27
"""

from app.db.schema_migrations.sqlscript import execute_script

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    execute_script("""
        -- System context (security jobs, admin metadata views) may read the audit log.
        CREATE POLICY audit_system_select ON audit_events FOR SELECT TO planhaven_app
            USING (app.is_system());

        CREATE TABLE webauthn_credentials (
            id            uuid PRIMARY KEY DEFAULT uuidv7(),
            user_id       uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
            credential_id bytea NOT NULL CHECK (length(credential_id) BETWEEN 16 AND 1023),
            public_key    bytea NOT NULL CHECK (length(public_key) <= 2048),
            sign_count    bigint NOT NULL DEFAULT 0 CHECK (sign_count >= 0),
            transports    text[] NOT NULL DEFAULT '{}',
            name          text NOT NULL CHECK (length(name) BETWEEN 1 AND 100),
            created_at    timestamptz NOT NULL DEFAULT now(),
            last_used_at  timestamptz
        );
        CREATE UNIQUE INDEX webauthn_credential_id_key ON webauthn_credentials (credential_id);
        CREATE INDEX webauthn_user_idx ON webauthn_credentials (user_id);
        ALTER TABLE webauthn_credentials ENABLE ROW LEVEL SECURITY;
        ALTER TABLE webauthn_credentials FORCE ROW LEVEL SECURITY;
        CREATE POLICY webauthn_own ON webauthn_credentials FOR ALL TO planhaven_app
            USING (app.is_system() OR user_id = app.current_user_id())
            WITH CHECK (app.is_system() OR user_id = app.current_user_id());
        REVOKE ALL ON webauthn_credentials FROM PUBLIC;
        GRANT SELECT, INSERT, DELETE ON webauthn_credentials TO planhaven_app;
        GRANT UPDATE (sign_count, last_used_at, name) ON webauthn_credentials TO planhaven_app;

        -- Challenges are single use, expire after 5 minutes, and are bound to the session
        -- (or, for passkey-only sign-in, to a one-time challenge ID the browser holds).
        CREATE TABLE webauthn_challenges (
            id         uuid PRIMARY KEY DEFAULT uuidv7(),
            challenge  bytea NOT NULL CHECK (length(challenge) BETWEEN 32 AND 64),
            purpose    text NOT NULL CHECK (purpose IN ('register', 'verify', 'login')),
            user_id    uuid REFERENCES users (id) ON DELETE CASCADE,
            session_id uuid REFERENCES sessions (id) ON DELETE CASCADE,
            expires_at timestamptz NOT NULL,
            used_at    timestamptz
        );
        ALTER TABLE webauthn_challenges ENABLE ROW LEVEL SECURITY;
        ALTER TABLE webauthn_challenges FORCE ROW LEVEL SECURITY;
        CREATE POLICY webauthn_challenges_system ON webauthn_challenges FOR ALL TO planhaven_app
            USING (app.is_system()) WITH CHECK (app.is_system());
        REVOKE ALL ON webauthn_challenges FROM PUBLIC;
        GRANT SELECT, INSERT, UPDATE, DELETE ON webauthn_challenges TO planhaven_app;
    """)


def downgrade() -> None:
    raise NotImplementedError("Downgrades are not supported; restore from backup.")
