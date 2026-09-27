"""Trash: deleted things stay restorable for 30 days, then a system job removes them
for good (phase 0.2, milestone 6).

Deletes were already soft (`deleted_at`) and the app role still has no DELETE on these
tables. Permanent removal goes through one SECURITY DEFINER function that only works in the
system context and can only remove rows deleted more than 30 days ago; cascades take their
children (note updates, members, ...). Unreferenced files are then removed by the blob purge.

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-28
"""

from app.db.schema_migrations.sqlscript import execute_script

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    execute_script("""
        -- What the purge function (running as planhaven_owner) may see and remove.
        CREATE POLICY list_items_purge_read ON list_items FOR SELECT TO planhaven_owner
            USING (deleted_at < now() - interval '30 days');
        CREATE POLICY list_items_purge ON list_items FOR DELETE TO planhaven_owner
            USING (deleted_at < now() - interval '30 days');
        CREATE POLICY tasks_purge_read ON tasks FOR SELECT TO planhaven_owner
            USING (deleted_at < now() - interval '30 days');
        CREATE POLICY tasks_purge ON tasks FOR DELETE TO planhaven_owner
            USING (deleted_at < now() - interval '30 days');
        CREATE POLICY lists_purge_read ON lists FOR SELECT TO planhaven_owner
            USING (deleted_at < now() - interval '30 days');
        CREATE POLICY lists_purge ON lists FOR DELETE TO planhaven_owner
            USING (deleted_at < now() - interval '30 days');
        CREATE POLICY notes_purge_read ON notes FOR SELECT TO planhaven_owner
            USING (deleted_at < now() - interval '30 days');
        CREATE POLICY notes_purge ON notes FOR DELETE TO planhaven_owner
            USING (deleted_at < now() - interval '30 days');
        CREATE POLICY attachments_purge_read ON attachments FOR SELECT TO planhaven_owner
            USING (deleted_at < now() - interval '30 days');
        CREATE POLICY attachments_purge ON attachments FOR DELETE TO planhaven_owner
            USING (deleted_at < now() - interval '30 days');
        CREATE POLICY projects_purge_read ON projects FOR SELECT TO planhaven_owner
            USING (deleted_at < now() - interval '30 days');
        CREATE POLICY projects_purge ON projects FOR DELETE TO planhaven_owner
            USING (deleted_at < now() - interval '30 days');
        CREATE POLICY assets_purge_read ON assets FOR SELECT TO planhaven_owner
            USING (deleted_at < now() - interval '30 days');
        CREATE POLICY assets_purge ON assets FOR DELETE TO planhaven_owner
            USING (deleted_at < now() - interval '30 days');

        CREATE FUNCTION app.purge_trash() RETURNS integer
            LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public
            AS $$
            DECLARE
                removed integer := 0;
                n integer;
            BEGIN
                IF NOT app.is_system() THEN
                    RAISE EXCEPTION 'purge_trash is a system job'
                        USING ERRCODE = 'insufficient_privilege';
                END IF;
                DELETE FROM list_items WHERE deleted_at < now() - interval '30 days';
                GET DIAGNOSTICS n = ROW_COUNT; removed := removed + n;
                DELETE FROM tasks WHERE deleted_at < now() - interval '30 days';
                GET DIAGNOSTICS n = ROW_COUNT; removed := removed + n;
                DELETE FROM lists WHERE deleted_at < now() - interval '30 days';
                GET DIAGNOSTICS n = ROW_COUNT; removed := removed + n;
                DELETE FROM notes WHERE deleted_at < now() - interval '30 days';
                GET DIAGNOSTICS n = ROW_COUNT; removed := removed + n;
                DELETE FROM attachments WHERE deleted_at < now() - interval '30 days';
                GET DIAGNOSTICS n = ROW_COUNT; removed := removed + n;
                DELETE FROM projects WHERE deleted_at < now() - interval '30 days';
                GET DIAGNOSTICS n = ROW_COUNT; removed := removed + n;
                DELETE FROM assets WHERE deleted_at < now() - interval '30 days';
                GET DIAGNOSTICS n = ROW_COUNT; removed := removed + n;
                RETURN removed;
            END
            $$;
        REVOKE ALL ON FUNCTION app.purge_trash() FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app.purge_trash() TO planhaven_app;
    """)


def downgrade() -> None:
    raise NotImplementedError("Downgrades are not supported; restore from backup.")
