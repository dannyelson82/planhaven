"""Folders for the projects list, each person's own (maintainer, 2026-11-25; ADR 0022).

- project_folders: a person's folders. A folder may sit inside another of the same person's
  folders, at most 5 levels deep, never inside itself (checked by trigger).
- project_folder_items: which folder a project is in, for one person; a project is in at most
  one of their folders (or none). Only projects the person can read can be filed.

Both are each person's own rows: nobody else sees or changes them, and an admin can't read
them. A shared project can sit in different folders for different people.

Revision ID: 0037
Revises: 0036
Create Date: 2026-11-25
"""

from app.db.schema_migrations.sqlscript import execute_script

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    execute_script("""
        CREATE TABLE project_folders (
            id          uuid PRIMARY KEY DEFAULT uuidv7(),
            user_id     uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
            parent_id   uuid REFERENCES project_folders (id) ON DELETE CASCADE,
            name        text NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 100),
            position    double precision NOT NULL DEFAULT 0,
            created_at  timestamptz NOT NULL DEFAULT now(),
            updated_at  timestamptz NOT NULL DEFAULT now(),
            version     integer NOT NULL DEFAULT 1,
            CHECK (parent_id IS NULL OR parent_id <> id)
        );
        CREATE INDEX project_folders_user_idx ON project_folders (user_id, parent_id);

        CREATE TABLE project_folder_items (
            user_id     uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
            project_id  uuid NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
            folder_id   uuid NOT NULL REFERENCES project_folders (id) ON DELETE CASCADE,
            PRIMARY KEY (user_id, project_id)
        );
        CREATE INDEX project_folder_items_folder_idx ON project_folder_items (folder_id);

        -- A folder's parent is the same person's folder, never itself or one of its own
        -- subfolders, and no more than 5 levels deep. Runs as the caller (RLS applies).
        CREATE FUNCTION app.project_folders_check() RETURNS trigger
            LANGUAGE plpgsql SET search_path = pg_catalog, public
            AS $$
            DECLARE
                cursor_id uuid := NEW.parent_id;
                depth int := 1;
                owner uuid;
            BEGIN
                WHILE cursor_id IS NOT NULL LOOP
                    IF cursor_id = NEW.id THEN
                        RAISE EXCEPTION 'a folder cannot go inside itself'
                            USING ERRCODE = 'check_violation';
                    END IF;
                    SELECT user_id, parent_id INTO owner, cursor_id
                        FROM project_folders WHERE id = cursor_id;
                    IF owner IS NULL OR owner <> NEW.user_id THEN
                        RAISE EXCEPTION 'unknown parent folder' USING ERRCODE = 'check_violation';
                    END IF;
                    depth := depth + 1;
                    IF depth > 5 THEN
                        RAISE EXCEPTION 'folders go at most 5 levels deep'
                            USING ERRCODE = 'check_violation';
                    END IF;
                END LOOP;
                RETURN NEW;
            END
            $$;
        CREATE TRIGGER project_folders_check BEFORE INSERT OR UPDATE OF parent_id
            ON project_folders FOR EACH ROW EXECUTE FUNCTION app.project_folders_check();

        ALTER TABLE project_folders ENABLE ROW LEVEL SECURITY;
        ALTER TABLE project_folders FORCE ROW LEVEL SECURITY;
        CREATE POLICY project_folders_own ON project_folders FOR ALL TO planhaven_app
            USING (user_id = app.current_user_id())
            WITH CHECK (user_id = app.current_user_id());
        ALTER TABLE project_folder_items ENABLE ROW LEVEL SECURITY;
        ALTER TABLE project_folder_items FORCE ROW LEVEL SECURITY;
        CREATE POLICY project_folder_items_own ON project_folder_items FOR SELECT TO planhaven_app
            USING (user_id = app.current_user_id());
        CREATE POLICY project_folder_items_insert ON project_folder_items FOR INSERT
            TO planhaven_app
            WITH CHECK (user_id = app.current_user_id() AND app.can_read(project_id)
                        AND EXISTS (SELECT 1 FROM project_folders f
                                    WHERE f.id = folder_id AND f.user_id = app.current_user_id()));
        CREATE POLICY project_folder_items_update ON project_folder_items FOR UPDATE
            TO planhaven_app
            USING (user_id = app.current_user_id())
            WITH CHECK (user_id = app.current_user_id() AND app.can_read(project_id)
                        AND EXISTS (SELECT 1 FROM project_folders f
                                    WHERE f.id = folder_id AND f.user_id = app.current_user_id()));
        CREATE POLICY project_folder_items_delete ON project_folder_items FOR DELETE
            TO planhaven_app USING (user_id = app.current_user_id());
        REVOKE ALL ON project_folders, project_folder_items FROM PUBLIC;
        GRANT SELECT, INSERT, DELETE ON project_folders, project_folder_items TO planhaven_app;
        GRANT UPDATE (parent_id, name, position, updated_at, version) ON project_folders
            TO planhaven_app;
        GRANT UPDATE (folder_id) ON project_folder_items TO planhaven_app;
    """)


def downgrade() -> None:
    raise NotImplementedError("Downgrades are not supported; restore from backup.")
