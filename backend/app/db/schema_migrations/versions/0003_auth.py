"""Users, sessions and the first-boot setup token (SECURITY.md §7.1, §7.2).

Credential checks (login, setup) run in system context because they happen before anyone is
identified. Once signed in, a user can read and update only their own row, and can't make
themselves an admin: a trigger rejects `is_admin` changes outside system context.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-27
"""

from app.db.schema_migrations.sqlscript import execute_script

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    execute_script("""
        CREATE TABLE users (
            id            uuid PRIMARY KEY DEFAULT uuidv7(),
            email         text NOT NULL CHECK (length(email) BETWEEN 3 AND 254
                                               AND email = lower(email)),
            display_name  text NOT NULL CHECK (length(display_name) BETWEEN 1 AND 100),
            password_hash text NOT NULL CHECK (length(password_hash) <= 512),
            is_admin      boolean NOT NULL DEFAULT false,
            disabled_at   timestamptz,
            created_at    timestamptz NOT NULL DEFAULT now(),
            updated_at    timestamptz NOT NULL DEFAULT now(),
            version       integer NOT NULL DEFAULT 1
        );
        CREATE UNIQUE INDEX users_email_key ON users (email);

        ALTER TABLE users ENABLE ROW LEVEL SECURITY;
        ALTER TABLE users FORCE ROW LEVEL SECURITY;
        CREATE POLICY users_select ON users FOR SELECT TO planhaven_app
            USING (app.is_system() OR id = app.current_user_id());
        CREATE POLICY users_insert ON users FOR INSERT TO planhaven_app
            WITH CHECK (app.is_system());
        CREATE POLICY users_update ON users FOR UPDATE TO planhaven_app
            USING (app.is_system() OR id = app.current_user_id())
            WITH CHECK (app.is_system() OR id = app.current_user_id());

        CREATE FUNCTION app.users_guard_admin() RETURNS trigger
            LANGUAGE plpgsql SET search_path = pg_catalog
            AS $$
            BEGIN
                IF NEW.is_admin IS DISTINCT FROM OLD.is_admin AND NOT app.is_system() THEN
                    RAISE EXCEPTION 'is_admin can only change in system context'
                        USING ERRCODE = 'insufficient_privilege';
                END IF;
                RETURN NEW;
            END
            $$;
        CREATE TRIGGER users_guard_admin BEFORE UPDATE ON users
            FOR EACH ROW EXECUTE FUNCTION app.users_guard_admin();

        REVOKE ALL ON users FROM PUBLIC;
        GRANT SELECT, INSERT ON users TO planhaven_app;
        GRANT UPDATE (display_name, password_hash, is_admin, disabled_at, updated_at, version)
            ON users TO planhaven_app;

        CREATE TABLE sessions (
            id                 uuid PRIMARY KEY DEFAULT uuidv7(),
            token_hash         bytea NOT NULL CHECK (length(token_hash) = 32),
            user_id            uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
            mfa_verified       boolean NOT NULL DEFAULT false,
            created_at         timestamptz NOT NULL DEFAULT now(),
            last_seen_at       timestamptz NOT NULL DEFAULT now(),
            idle_expires_at    timestamptz NOT NULL,
            absolute_expires_at timestamptz NOT NULL,
            ip                 inet,
            user_agent         text CHECK (length(user_agent) <= 200),
            revoked_at         timestamptz
        );
        CREATE UNIQUE INDEX sessions_token_key ON sessions (token_hash);
        CREATE INDEX sessions_user_idx ON sessions (user_id);

        ALTER TABLE sessions ENABLE ROW LEVEL SECURITY;
        ALTER TABLE sessions FORCE ROW LEVEL SECURITY;
        CREATE POLICY sessions_system ON sessions FOR ALL TO planhaven_app
            USING (app.is_system()) WITH CHECK (app.is_system());
        CREATE POLICY sessions_own_select ON sessions FOR SELECT TO planhaven_app
            USING (user_id = app.current_user_id());
        CREATE POLICY sessions_own_revoke ON sessions FOR UPDATE TO planhaven_app
            USING (user_id = app.current_user_id())
            WITH CHECK (user_id = app.current_user_id());

        REVOKE ALL ON sessions FROM PUBLIC;
        GRANT SELECT, INSERT, DELETE ON sessions TO planhaven_app;
        GRANT UPDATE (mfa_verified, last_seen_at, idle_expires_at, revoked_at)
            ON sessions TO planhaven_app;

        CREATE TABLE setup_tokens (
            id         uuid PRIMARY KEY DEFAULT uuidv7(),
            token_hash bytea NOT NULL CHECK (length(token_hash) = 32),
            created_at timestamptz NOT NULL DEFAULT now(),
            expires_at timestamptz NOT NULL,
            used_at    timestamptz
        );
        ALTER TABLE setup_tokens ENABLE ROW LEVEL SECURITY;
        ALTER TABLE setup_tokens FORCE ROW LEVEL SECURITY;
        CREATE POLICY setup_tokens_system ON setup_tokens FOR ALL TO planhaven_app
            USING (app.is_system()) WITH CHECK (app.is_system());
        REVOKE ALL ON setup_tokens FROM PUBLIC;
        GRANT SELECT, INSERT, UPDATE, DELETE ON setup_tokens TO planhaven_app;
    """)


def downgrade() -> None:
    raise NotImplementedError("Downgrades are not supported; restore from backup.")
