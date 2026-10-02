"""Suppliers on list items, asset readings and service schedules, and archived notes
(maintainer's testing notes, 2026-10-02).

- Suppliers are contacts of kind 'supplier' (migration 0016: shared one by one, own roles),
  shown in their own Suppliers list in the app. A list item may name one; like a quote's
  contact, only a supplier you can see (trigger). Project members who can't see it just see
  the item without it (RLS on contacts).
- Asset readings (distance and/or hours), service schedules ("oil every 8,000 km or 12
  months") and service records belong to an asset: its members read them, its owners and
  editors write (asset_role, migration 0014). A record may name one of the asset's schedules.
- Notes can be archived (hidden from the project page, restorable). Share-link guests can't
  archive: the column guard (migration 0026) allows them only content changes.

Revision ID: 0028
Revises: 0027
Create Date: 2026-10-02
"""

from app.db.schema_migrations.sqlscript import execute_script

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    execute_script("""
        -- ---------------------------------------------------------- suppliers on items
        ALTER TABLE list_items
            ADD COLUMN supplier_id uuid REFERENCES contacts (id) ON DELETE SET NULL;
        CREATE INDEX list_items_supplier_idx ON list_items (supplier_id)
            WHERE supplier_id IS NOT NULL AND deleted_at IS NULL;
        GRANT UPDATE (supplier_id) ON list_items TO planhaven_app;

        CREATE FUNCTION app.list_items_check_supplier() RETURNS trigger
            LANGUAGE plpgsql SET search_path = pg_catalog, public
            AS $$
            BEGIN
                IF NOT app.is_system() AND NEW.supplier_id IS NOT NULL
                   AND (TG_OP = 'INSERT' OR NEW.supplier_id IS DISTINCT FROM OLD.supplier_id)
                   AND app.contact_role(NEW.supplier_id) IS NULL THEN
                    RAISE EXCEPTION 'supplier not found' USING ERRCODE = 'insufficient_privilege';
                END IF;
                RETURN NEW;
            END
            $$;
        CREATE TRIGGER list_items_check_supplier BEFORE INSERT OR UPDATE ON list_items
            FOR EACH ROW EXECUTE FUNCTION app.list_items_check_supplier();

        -- ---------------------------------------------------------- asset service
        ALTER TABLE assets
            ADD COLUMN distance_unit text NOT NULL DEFAULT 'km'
                CHECK (distance_unit IN ('km', 'mi'));
        GRANT UPDATE (distance_unit) ON assets TO planhaven_app;

        CREATE TABLE asset_readings (
            id          uuid PRIMARY KEY DEFAULT uuidv7(),
            asset_id    uuid NOT NULL REFERENCES assets (id) ON DELETE CASCADE,
            read_on     date NOT NULL DEFAULT current_date,
            distance    numeric(12, 1) CHECK (distance BETWEEN 0 AND 99999999),
            hours       numeric(10, 1) CHECK (hours BETWEEN 0 AND 9999999),
            created_by  uuid NOT NULL REFERENCES users (id),
            created_at  timestamptz NOT NULL DEFAULT now(),
            CHECK (distance IS NOT NULL OR hours IS NOT NULL)
        );
        CREATE INDEX asset_readings_asset_idx ON asset_readings (asset_id, read_on DESC);

        CREATE TABLE service_schedules (
            id              uuid PRIMARY KEY DEFAULT uuidv7(),
            asset_id        uuid NOT NULL REFERENCES assets (id) ON DELETE CASCADE,
            name            text NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
            every_distance  numeric(12, 1) CHECK (every_distance > 0 AND every_distance <= 9999999),
            every_hours     numeric(10, 1) CHECK (every_hours > 0 AND every_hours <= 999999),
            every_months    integer CHECK (every_months BETWEEN 1 AND 240),
            notes           text NOT NULL DEFAULT '' CHECK (length(notes) <= 4000),
            created_by      uuid NOT NULL REFERENCES users (id),
            created_at      timestamptz NOT NULL DEFAULT now(),
            updated_at      timestamptz NOT NULL DEFAULT now(),
            version         integer NOT NULL DEFAULT 1,
            deleted_at      timestamptz,
            CHECK (every_distance IS NOT NULL OR every_hours IS NOT NULL
                   OR every_months IS NOT NULL)
        );
        CREATE INDEX service_schedules_asset_idx ON service_schedules (asset_id)
            WHERE deleted_at IS NULL;

        CREATE TABLE service_records (
            id           uuid PRIMARY KEY DEFAULT uuidv7(),
            asset_id     uuid NOT NULL REFERENCES assets (id) ON DELETE CASCADE,
            schedule_id  uuid REFERENCES service_schedules (id) ON DELETE SET NULL,
            title        text NOT NULL CHECK (length(title) BETWEEN 1 AND 200),
            done_on      date NOT NULL DEFAULT current_date,
            distance     numeric(12, 1) CHECK (distance BETWEEN 0 AND 99999999),
            hours        numeric(10, 1) CHECK (hours BETWEEN 0 AND 9999999),
            cost_cents   bigint CHECK (cost_cents BETWEEN 0 AND 100000000000),
            notes        text NOT NULL DEFAULT '' CHECK (length(notes) <= 4000),
            created_by   uuid NOT NULL REFERENCES users (id),
            created_at   timestamptz NOT NULL DEFAULT now(),
            deleted_at   timestamptz
        );
        CREATE INDEX service_records_asset_idx ON service_records (asset_id, done_on DESC)
            WHERE deleted_at IS NULL;

        -- A record's schedule is one of the same asset's.
        CREATE FUNCTION app.service_records_check_schedule() RETURNS trigger
            LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public
            AS $$
            BEGIN
                IF NEW.schedule_id IS NOT NULL AND NOT EXISTS (
                    SELECT 1 FROM service_schedules s
                    WHERE s.id = NEW.schedule_id AND s.asset_id = NEW.asset_id) THEN
                    RAISE EXCEPTION 'schedule not on this asset'
                        USING ERRCODE = 'foreign_key_violation';
                END IF;
                RETURN NEW;
            END
            $$;
        CREATE TRIGGER service_records_check_schedule
            BEFORE INSERT OR UPDATE OF schedule_id, asset_id ON service_records
            FOR EACH ROW EXECUTE FUNCTION app.service_records_check_schedule();
        CREATE POLICY service_schedules_definer_read ON service_schedules FOR SELECT
            TO planhaven_owner USING (true);

        ALTER TABLE asset_readings ENABLE ROW LEVEL SECURITY;
        ALTER TABLE asset_readings FORCE ROW LEVEL SECURITY;
        CREATE POLICY asset_readings_select ON asset_readings FOR SELECT TO planhaven_app
            USING (app.is_system() OR app.asset_role(asset_id) IS NOT NULL);
        CREATE POLICY asset_readings_insert ON asset_readings FOR INSERT TO planhaven_app
            WITH CHECK (app.asset_role(asset_id) IN ('owner', 'editor')
                        AND created_by = app.current_user_id());
        CREATE POLICY asset_readings_delete ON asset_readings FOR DELETE TO planhaven_app
            USING (app.asset_role(asset_id) IN ('owner', 'editor'));
        REVOKE ALL ON asset_readings FROM PUBLIC;
        GRANT SELECT, INSERT, DELETE ON asset_readings TO planhaven_app;

        ALTER TABLE service_schedules ENABLE ROW LEVEL SECURITY;
        ALTER TABLE service_schedules FORCE ROW LEVEL SECURITY;
        CREATE POLICY service_schedules_select ON service_schedules FOR SELECT TO planhaven_app
            USING (app.is_system() OR app.asset_role(asset_id) IS NOT NULL);
        CREATE POLICY service_schedules_insert ON service_schedules FOR INSERT TO planhaven_app
            WITH CHECK (app.asset_role(asset_id) IN ('owner', 'editor')
                        AND created_by = app.current_user_id());
        CREATE POLICY service_schedules_update ON service_schedules FOR UPDATE TO planhaven_app
            USING (app.asset_role(asset_id) IN ('owner', 'editor'))
            WITH CHECK (app.asset_role(asset_id) IN ('owner', 'editor'));
        REVOKE ALL ON service_schedules FROM PUBLIC;
        GRANT SELECT, INSERT ON service_schedules TO planhaven_app;
        GRANT UPDATE (name, every_distance, every_hours, every_months, notes, updated_at,
                      version, deleted_at) ON service_schedules TO planhaven_app;

        ALTER TABLE service_records ENABLE ROW LEVEL SECURITY;
        ALTER TABLE service_records FORCE ROW LEVEL SECURITY;
        CREATE POLICY service_records_select ON service_records FOR SELECT TO planhaven_app
            USING (app.is_system() OR app.asset_role(asset_id) IS NOT NULL);
        CREATE POLICY service_records_insert ON service_records FOR INSERT TO planhaven_app
            WITH CHECK (app.asset_role(asset_id) IN ('owner', 'editor')
                        AND created_by = app.current_user_id());
        CREATE POLICY service_records_update ON service_records FOR UPDATE TO planhaven_app
            USING (app.asset_role(asset_id) IN ('owner', 'editor'))
            WITH CHECK (app.asset_role(asset_id) IN ('owner', 'editor'));
        REVOKE ALL ON service_records FROM PUBLIC;
        GRANT SELECT, INSERT ON service_records TO planhaven_app;
        GRANT UPDATE (deleted_at) ON service_records TO planhaven_app;

        -- Deleted schedules and records go after 30 days, like the rest of the trash.
        CREATE POLICY service_records_purge_read ON service_records FOR SELECT
            TO planhaven_owner USING (deleted_at < now() - interval '30 days');
        CREATE POLICY service_records_purge ON service_records FOR DELETE TO planhaven_owner
            USING (deleted_at < now() - interval '30 days');
        CREATE POLICY service_schedules_purge ON service_schedules FOR DELETE
            TO planhaven_owner USING (deleted_at < now() - interval '30 days');

        CREATE OR REPLACE FUNCTION app.purge_trash() RETURNS integer
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
                DELETE FROM cost_entries WHERE deleted_at < now() - interval '30 days';
                GET DIAGNOSTICS n = ROW_COUNT; removed := removed + n;
                DELETE FROM quotes WHERE deleted_at < now() - interval '30 days';
                GET DIAGNOSTICS n = ROW_COUNT; removed := removed + n;
                DELETE FROM attachments WHERE deleted_at < now() - interval '30 days';
                GET DIAGNOSTICS n = ROW_COUNT; removed := removed + n;
                DELETE FROM projects WHERE deleted_at < now() - interval '30 days';
                GET DIAGNOSTICS n = ROW_COUNT; removed := removed + n;
                DELETE FROM assets WHERE deleted_at < now() - interval '30 days';
                GET DIAGNOSTICS n = ROW_COUNT; removed := removed + n;
                DELETE FROM contacts WHERE deleted_at < now() - interval '30 days';
                GET DIAGNOSTICS n = ROW_COUNT; removed := removed + n;
                DELETE FROM service_records WHERE deleted_at < now() - interval '30 days';
                GET DIAGNOSTICS n = ROW_COUNT; removed := removed + n;
                DELETE FROM service_schedules WHERE deleted_at < now() - interval '30 days';
                GET DIAGNOSTICS n = ROW_COUNT; removed := removed + n;
                RETURN removed;
            END
            $$;

        -- ---------------------------------------------------------- archived notes
        ALTER TABLE notes ADD COLUMN archived_at timestamptz;
        GRANT UPDATE (archived_at) ON notes TO planhaven_app;
    """)


def downgrade() -> None:
    raise NotImplementedError("Downgrades are not supported; restore from backup.")
