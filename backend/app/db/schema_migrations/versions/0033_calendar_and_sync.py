"""The calendar feed and iPhone Reminders sync (A§13.1, A§13.2, SECURITY.md §7.3).

- access_tokens: each person's feed and sync keys. 256-bit random, shown once, stored as
  SHA-256 hashes, revocable one by one; `phv_ics_` (read the calendar feed only; one live per
  person, regenerating replaces it) and `phv_sync_` (read lists chosen for Reminders, tick
  their items; one per device). Own rows only; looked up by hash in system context.
- list_sync: which lists a person sends to which Reminders list on their iPhone. Own rows
  only, and only for lists they can read (checked by trigger).

Revision ID: 0033
Revises: 0032
Create Date: 2026-10-02
"""

from app.db.schema_migrations.sqlscript import execute_script

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    execute_script("""
        CREATE TABLE access_tokens (
            id            uuid PRIMARY KEY DEFAULT uuidv7(),
            user_id       uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
            kind          text NOT NULL CHECK (kind IN ('ics', 'sync')),
            token_hash    bytea NOT NULL UNIQUE CHECK (length(token_hash) = 32),
            label         text NOT NULL DEFAULT '' CHECK (length(label) <= 80),
            details       boolean NOT NULL DEFAULT false,
            created_at    timestamptz NOT NULL DEFAULT now(),
            last_used_at  timestamptz,
            last_used_ip  inet,
            revoked_at    timestamptz
        );
        CREATE INDEX access_tokens_user_idx ON access_tokens (user_id) WHERE revoked_at IS NULL;
        CREATE UNIQUE INDEX access_tokens_one_feed ON access_tokens (user_id)
            WHERE kind = 'ics' AND revoked_at IS NULL;

        ALTER TABLE access_tokens ENABLE ROW LEVEL SECURITY;
        ALTER TABLE access_tokens FORCE ROW LEVEL SECURITY;
        CREATE POLICY access_tokens_select ON access_tokens FOR SELECT TO planhaven_app
            USING (app.is_system() OR user_id = app.current_user_id());
        CREATE POLICY access_tokens_insert ON access_tokens FOR INSERT TO planhaven_app
            WITH CHECK (user_id = app.current_user_id());
        CREATE POLICY access_tokens_update ON access_tokens FOR UPDATE TO planhaven_app
            USING (app.is_system() OR user_id = app.current_user_id())
            WITH CHECK (app.is_system() OR user_id = app.current_user_id());
        REVOKE ALL ON access_tokens FROM PUBLIC;
        GRANT SELECT, INSERT ON access_tokens TO planhaven_app;
        GRANT UPDATE (label, details, last_used_at, last_used_ip, revoked_at)
            ON access_tokens TO planhaven_app;

        CREATE TABLE list_sync (
            user_id         uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
            list_id         uuid NOT NULL REFERENCES lists (id) ON DELETE CASCADE,
            reminders_name  text NOT NULL CHECK (length(reminders_name) BETWEEN 1 AND 60),
            created_at      timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (user_id, list_id)
        );
        ALTER TABLE list_sync ENABLE ROW LEVEL SECURITY;
        ALTER TABLE list_sync FORCE ROW LEVEL SECURITY;
        CREATE POLICY list_sync_own ON list_sync FOR ALL TO planhaven_app
            USING (app.is_system() OR user_id = app.current_user_id())
            WITH CHECK (user_id = app.current_user_id());
        REVOKE ALL ON list_sync FROM PUBLIC;
        GRANT SELECT, INSERT, DELETE ON list_sync TO planhaven_app;
        GRANT UPDATE (reminders_name) ON list_sync TO planhaven_app;

        -- Only lists the person can read.
        CREATE FUNCTION app.list_sync_check() RETURNS trigger
            LANGUAGE plpgsql SET search_path = pg_catalog, public
            AS $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM lists l WHERE l.id = NEW.list_id
                               AND l.deleted_at IS NULL AND app.can_read(l.project_id)) THEN
                    RAISE EXCEPTION 'list not found' USING ERRCODE = 'insufficient_privilege';
                END IF;
                RETURN NEW;
            END
            $$;
        CREATE TRIGGER list_sync_check BEFORE INSERT OR UPDATE ON list_sync
            FOR EACH ROW EXECUTE FUNCTION app.list_sync_check();
    """)


def downgrade() -> None:
    raise NotImplementedError("Downgrades are not supported; restore from backup.")
