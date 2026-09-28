"""Items a task needs, picked from the project's lists (owner request, 2026-09-28).

A task can point at list items (e.g. "Change oil" needs the oil and the filter from the
Hardware store list); the task then shows how many are still to get. Both must belong to
the same project (trigger). Members read; editors change.

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-28
"""

from app.db.schema_migrations.sqlscript import execute_script

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    execute_script("""
        CREATE TABLE task_needs (
            task_id      uuid NOT NULL REFERENCES tasks (id) ON DELETE CASCADE,
            list_item_id uuid NOT NULL REFERENCES list_items (id) ON DELETE CASCADE,
            project_id   uuid NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
            created_at   timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (task_id, list_item_id)
        );
        CREATE INDEX task_needs_project_idx ON task_needs (project_id);
        CREATE INDEX task_needs_item_idx ON task_needs (list_item_id);

        ALTER TABLE task_needs ENABLE ROW LEVEL SECURITY;
        ALTER TABLE task_needs FORCE ROW LEVEL SECURITY;
        CREATE POLICY task_needs_select ON task_needs FOR SELECT TO planhaven_app
            USING (app.is_system() OR app.can_read(project_id));
        CREATE POLICY task_needs_insert ON task_needs FOR INSERT TO planhaven_app
            WITH CHECK (app.can_write(project_id));
        CREATE POLICY task_needs_delete ON task_needs FOR DELETE TO planhaven_app
            USING (app.can_write(project_id));
        REVOKE ALL ON task_needs FROM PUBLIC;
        GRANT SELECT, INSERT, DELETE ON task_needs TO planhaven_app;

        CREATE FUNCTION app.task_needs_same_project() RETURNS trigger
            LANGUAGE plpgsql SET search_path = pg_catalog, public
            AS $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM tasks t WHERE t.id = NEW.task_id
                               AND t.project_id = NEW.project_id)
                   OR NOT EXISTS (SELECT 1 FROM list_items i WHERE i.id = NEW.list_item_id
                                  AND i.project_id = NEW.project_id) THEN
                    RAISE EXCEPTION 'task and item must be in the same project'
                        USING ERRCODE = 'foreign_key_violation';
                END IF;
                RETURN NEW;
            END
            $$;
        CREATE TRIGGER task_needs_same_project BEFORE INSERT ON task_needs
            FOR EACH ROW EXECUTE FUNCTION app.task_needs_same_project();
    """)


def downgrade() -> None:
    raise NotImplementedError("Downgrades are not supported; restore from backup.")
