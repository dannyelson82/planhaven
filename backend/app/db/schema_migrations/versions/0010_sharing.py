"""Sharing: members may leave a project themselves; owners manage everyone else.

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-27
"""

from app.db.schema_migrations.sqlscript import execute_script

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    execute_script("""
        DROP POLICY members_delete ON project_members;
        CREATE POLICY members_delete ON project_members FOR DELETE TO planhaven_app
            USING (app.project_role(project_id) = 'owner' OR user_id = app.current_user_id());

        -- System context (notifications, reminders, member names) may read projects, tasks and
        -- memberships. It never writes them through these policies.
        DROP POLICY projects_select ON projects;
        CREATE POLICY projects_select ON projects FOR SELECT TO planhaven_app
            USING (app.is_system() OR app.can_read(id)
                   OR (created_by = app.current_user_id() AND NOT app.project_has_members(id)));
        DROP POLICY tasks_select ON tasks;
        CREATE POLICY tasks_select ON tasks FOR SELECT TO planhaven_app
            USING (app.is_system() OR app.can_read(project_id)
                   OR assignee_id = app.current_user_id());

        DROP POLICY members_select ON project_members;
        CREATE POLICY members_select ON project_members FOR SELECT TO planhaven_app
            USING (app.is_system() OR app.can_read(project_id));

        -- A project always keeps at least one owner (checked after each change). System jobs
        -- that remove whole projects (trash purge) are exempt.
        CREATE FUNCTION app.members_keep_an_owner() RETURNS trigger
            LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public
            AS $$
            BEGIN
                IF NOT app.is_system()
                   AND NOT EXISTS (SELECT 1 FROM project_members m
                                   WHERE m.project_id = OLD.project_id AND m.role = 'owner') THEN
                    RAISE EXCEPTION 'a project must keep at least one owner'
                        USING ERRCODE = 'check_violation';
                END IF;
                RETURN NULL;
            END
            $$;
        CREATE CONSTRAINT TRIGGER members_keep_an_owner
            AFTER UPDATE OR DELETE ON project_members DEFERRABLE INITIALLY IMMEDIATE
            FOR EACH ROW EXECUTE FUNCTION app.members_keep_an_owner();
    """)


def downgrade() -> None:
    raise NotImplementedError("Downgrades are not supported; restore from backup.")
