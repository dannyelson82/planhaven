"""The change feed for the iPhone app's offline copy (ADR 0021, phase 0.5 milestone 3).

- changes: one row per change to synced content, written by triggers in the same transaction
  as the change itself. It records what changed (kind, id, op) and its scope (project, asset
  or contact, or the person whose access changed), never content. System-only: the feed
  reads it for one person, filtered to the scopes they belong to, and fetches the items
  themselves as that person (RLS).
- Ordered by the writing transaction's id (`txid`, xid8) and then `id`. The feed only returns
  rows from transactions older than every running one (pg_snapshot_xmin), so a later page can
  never hold a change from before an earlier page's cursor.
- changes_purged: the newest transaction id cleared by housekeeping (after 30 days); a cursor
  from before it gets "start over".

Revision ID: 0036
Revises: 0035
Create Date: 2026-11-25
"""

from app.db.schema_migrations.sqlscript import execute_script

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    execute_script("""
        CREATE TABLE changes (
            id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            txid         xid8 NOT NULL DEFAULT pg_current_xact_id(),
            created_at   timestamptz NOT NULL DEFAULT now(),
            kind         text NOT NULL CHECK (length(kind) <= 40),
            item_id      uuid NOT NULL,
            op           text NOT NULL
                         CHECK (op IN ('upsert', 'delete', 'access_gained', 'access_lost')),
            project_id   uuid,
            asset_id     uuid,
            contact_id   uuid,
            user_id      uuid
        );
        CREATE INDEX changes_order_idx ON changes (txid, id);
        CREATE INDEX changes_project_idx ON changes (project_id, txid) WHERE project_id IS NOT NULL;
        CREATE INDEX changes_asset_idx ON changes (asset_id, txid) WHERE asset_id IS NOT NULL;
        CREATE INDEX changes_contact_idx ON changes (contact_id, txid) WHERE contact_id IS NOT NULL;
        CREATE INDEX changes_user_idx ON changes (user_id, txid) WHERE user_id IS NOT NULL;

        CREATE TABLE changes_purged (
            only_row  boolean PRIMARY KEY DEFAULT true CHECK (only_row),
            txid      xid8 NOT NULL
        );

        -- What changed and where; never content. Soft deletes (deleted_at set) are deletes,
        -- restores are upserts. Membership rows say whose access changed.
        CREATE FUNCTION app.record_change() RETURNS trigger
            LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public
            AS $$
            DECLARE
                r jsonb := to_jsonb(CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END);
                kind text := TG_TABLE_NAME;
                op text;
                item uuid;
            BEGIN
                IF TG_TABLE_NAME IN ('project_members', 'asset_members', 'contact_members') THEN
                    IF TG_OP = 'UPDATE' THEN
                        RETURN NULL;  -- a role change: the items stay visible
                    END IF;
                    op := CASE WHEN TG_OP = 'DELETE' THEN 'access_lost' ELSE 'access_gained' END;
                    item := coalesce(r->>'project_id', r->>'asset_id', r->>'contact_id')::uuid;
                    kind := CASE TG_TABLE_NAME WHEN 'project_members' THEN 'projects'
                                               WHEN 'asset_members' THEN 'assets'
                                               ELSE 'contacts' END;
                    INSERT INTO changes (kind, item_id, op, user_id)
                    VALUES (kind, item, op, (r->>'user_id')::uuid);
                    RETURN NULL;
                END IF;
                op := CASE WHEN TG_OP = 'DELETE' OR r->>'deleted_at' IS NOT NULL
                           THEN 'delete' ELSE 'upsert' END;
                item := (r->>'id')::uuid;
                INSERT INTO changes (kind, item_id, op, project_id, asset_id, contact_id)
                VALUES (
                    kind, item, op,
                    CASE WHEN kind = 'projects' THEN item ELSE (r->>'project_id')::uuid END,
                    CASE WHEN kind = 'assets' THEN item ELSE (r->>'asset_id')::uuid END,
                    CASE WHEN kind = 'contacts' THEN item ELSE (r->>'contact_id')::uuid END
                );
                RETURN NULL;
            END
            $$;
        CREATE TRIGGER projects_change AFTER INSERT OR UPDATE OR DELETE ON projects
            FOR EACH ROW EXECUTE FUNCTION app.record_change();
        CREATE TRIGGER tasks_change AFTER INSERT OR UPDATE OR DELETE ON tasks
            FOR EACH ROW EXECUTE FUNCTION app.record_change();
        CREATE TRIGGER lists_change AFTER INSERT OR UPDATE OR DELETE ON lists
            FOR EACH ROW EXECUTE FUNCTION app.record_change();
        CREATE TRIGGER list_items_change AFTER INSERT OR UPDATE OR DELETE ON list_items
            FOR EACH ROW EXECUTE FUNCTION app.record_change();
        CREATE TRIGGER notes_change AFTER INSERT OR UPDATE OR DELETE ON notes
            FOR EACH ROW EXECUTE FUNCTION app.record_change();
        CREATE TRIGGER attachments_change AFTER INSERT OR UPDATE OR DELETE ON attachments
            FOR EACH ROW EXECUTE FUNCTION app.record_change();
        CREATE TRIGGER quotes_change AFTER INSERT OR UPDATE OR DELETE ON quotes
            FOR EACH ROW EXECUTE FUNCTION app.record_change();
        CREATE TRIGGER cost_entries_change AFTER INSERT OR UPDATE OR DELETE ON cost_entries
            FOR EACH ROW EXECUTE FUNCTION app.record_change();
        CREATE TRIGGER assets_change AFTER INSERT OR UPDATE OR DELETE ON assets
            FOR EACH ROW EXECUTE FUNCTION app.record_change();
        CREATE TRIGGER asset_readings_change AFTER INSERT OR UPDATE OR DELETE ON asset_readings
            FOR EACH ROW EXECUTE FUNCTION app.record_change();
        CREATE TRIGGER service_schedules_change AFTER INSERT OR UPDATE OR DELETE
            ON service_schedules
            FOR EACH ROW EXECUTE FUNCTION app.record_change();
        CREATE TRIGGER service_records_change AFTER INSERT OR UPDATE OR DELETE ON service_records
            FOR EACH ROW EXECUTE FUNCTION app.record_change();
        CREATE TRIGGER contacts_change AFTER INSERT OR UPDATE OR DELETE ON contacts
            FOR EACH ROW EXECUTE FUNCTION app.record_change();
        CREATE TRIGGER project_members_change AFTER INSERT OR UPDATE OR DELETE ON project_members
            FOR EACH ROW EXECUTE FUNCTION app.record_change();
        CREATE TRIGGER asset_members_change AFTER INSERT OR UPDATE OR DELETE ON asset_members
            FOR EACH ROW EXECUTE FUNCTION app.record_change();
        CREATE TRIGGER contact_members_change AFTER INSERT OR UPDATE OR DELETE ON contact_members
            FOR EACH ROW EXECUTE FUNCTION app.record_change();

        ALTER TABLE changes ENABLE ROW LEVEL SECURITY;
        ALTER TABLE changes FORCE ROW LEVEL SECURITY;
        CREATE POLICY changes_system ON changes FOR ALL TO planhaven_app
            USING (app.is_system()) WITH CHECK (app.is_system());
        CREATE POLICY changes_definer_write ON changes FOR INSERT TO planhaven_owner
            WITH CHECK (true);
        ALTER TABLE changes_purged ENABLE ROW LEVEL SECURITY;
        ALTER TABLE changes_purged FORCE ROW LEVEL SECURITY;
        CREATE POLICY changes_purged_system ON changes_purged FOR ALL TO planhaven_app
            USING (app.is_system()) WITH CHECK (app.is_system());
        REVOKE ALL ON changes, changes_purged FROM PUBLIC;
        GRANT SELECT, DELETE ON changes TO planhaven_app;
        GRANT SELECT, INSERT, UPDATE ON changes_purged TO planhaven_app;
    """)


def downgrade() -> None:
    raise NotImplementedError("Downgrades are not supported; restore from backup.")
