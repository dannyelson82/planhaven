"""Notes as collaborative (Yjs/CRDT) documents (ADR 0011, ARCHITECTURE.md §8.5).

- `notes`: metadata plus `text_content`, a plain-text copy for search, AI and export.
- `note_updates`: each accepted edit (binary CRDT update) with who made it; RLS lets members
  read and editors append. Never logged.
- `note_snapshots`: compacted state; older updates are folded in by a system job.

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-28
"""

from app.db.schema_migrations.sqlscript import execute_script

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    execute_script("""
        CREATE TABLE notes (
            id           uuid PRIMARY KEY DEFAULT uuidv7(),
            project_id   uuid NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
            title        text NOT NULL CHECK (length(title) BETWEEN 1 AND 200),
            text_content text NOT NULL DEFAULT '' CHECK (length(text_content) <= 200000),
            source       text NOT NULL DEFAULT 'user' CHECK (length(source) <= 120),
            created_by   uuid NOT NULL REFERENCES users (id),
            created_at   timestamptz NOT NULL DEFAULT now(),
            updated_at   timestamptz NOT NULL DEFAULT now(),
            version      integer NOT NULL DEFAULT 1,
            deleted_at   timestamptz
        );
        CREATE INDEX notes_project_idx ON notes (project_id, updated_at DESC)
            WHERE deleted_at IS NULL;

        CREATE TABLE note_updates (
            id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            note_id    uuid NOT NULL REFERENCES notes (id) ON DELETE CASCADE,
            project_id uuid NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
            user_id    uuid NOT NULL REFERENCES users (id),
            client     text NOT NULL DEFAULT 'web' CHECK (length(client) <= 120),
            update     bytea NOT NULL CHECK (octet_length(update) <= 1048576),
            created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX note_updates_note_idx ON note_updates (note_id, id);

        CREATE TABLE note_snapshots (
            note_id    uuid PRIMARY KEY REFERENCES notes (id) ON DELETE CASCADE,
            project_id uuid NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
            state      bytea NOT NULL,
            last_update_id bigint NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now()
        );

        ALTER TABLE notes ENABLE ROW LEVEL SECURITY;
        ALTER TABLE notes FORCE ROW LEVEL SECURITY;
        CREATE POLICY notes_select ON notes FOR SELECT TO planhaven_app
            USING (app.is_system() OR app.can_read(project_id));
        CREATE POLICY notes_insert ON notes FOR INSERT TO planhaven_app
            WITH CHECK (app.can_write(project_id) AND created_by = app.current_user_id());
        CREATE POLICY notes_update ON notes FOR UPDATE TO planhaven_app
            USING (app.can_write(project_id)) WITH CHECK (app.can_write(project_id));
        REVOKE ALL ON notes FROM PUBLIC;
        GRANT SELECT, INSERT ON notes TO planhaven_app;
        GRANT UPDATE (title, text_content, updated_at, version, deleted_at) ON notes
            TO planhaven_app;

        ALTER TABLE note_updates ENABLE ROW LEVEL SECURITY;
        ALTER TABLE note_updates FORCE ROW LEVEL SECURITY;
        CREATE POLICY note_updates_select ON note_updates FOR SELECT TO planhaven_app
            USING (app.is_system() OR app.can_read(project_id));
        CREATE POLICY note_updates_insert ON note_updates FOR INSERT TO planhaven_app
            WITH CHECK (app.can_write(project_id) AND user_id = app.current_user_id()
                        AND EXISTS (SELECT 1 FROM notes n WHERE n.id = note_id
                                    AND n.project_id = note_updates.project_id));
        CREATE POLICY note_updates_compact ON note_updates FOR DELETE TO planhaven_app
            USING (app.is_system());
        REVOKE ALL ON note_updates FROM PUBLIC;
        GRANT SELECT, INSERT, DELETE ON note_updates TO planhaven_app;

        ALTER TABLE note_snapshots ENABLE ROW LEVEL SECURITY;
        ALTER TABLE note_snapshots FORCE ROW LEVEL SECURITY;
        CREATE POLICY note_snapshots_select ON note_snapshots FOR SELECT TO planhaven_app
            USING (app.is_system() OR app.can_read(project_id));
        CREATE POLICY note_snapshots_system ON note_snapshots FOR ALL TO planhaven_app
            USING (app.is_system()) WITH CHECK (app.is_system());
        REVOKE ALL ON note_snapshots FROM PUBLIC;
        GRANT SELECT, INSERT, UPDATE ON note_snapshots TO planhaven_app;
    """)


def downgrade() -> None:
    raise NotImplementedError("Downgrades are not supported; restore from backup.")
