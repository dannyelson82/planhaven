"""Purchases: a cost entry may carry its store, a receipt and item lines (owner request,
2026-09-28; docs/roadmap/phase-0.2.md, Milestone 7).

A cost entry stays one line ("Hardware store, $84.12"); the details are optional. Items can
come from a list of the same project (checked-off items with their estimated prices, then
edited to what was paid). The receipt is an attachment of the same project. Members read;
editors change. The entry's amount stays what was actually paid (tax included); the items
are a breakdown.

Revision ID: 0023
Revises: 0022
Create Date: 2026-09-28
"""

from app.db.schema_migrations.sqlscript import execute_script

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    execute_script("""
        ALTER TABLE cost_entries
            ADD COLUMN store text NOT NULL DEFAULT '' CHECK (length(store) <= 200),
            ADD COLUMN receipt_id uuid REFERENCES attachments (id) ON DELETE SET NULL;
        GRANT UPDATE (store, receipt_id) ON cost_entries TO planhaven_app;

        CREATE FUNCTION app.cost_entries_check_receipt() RETURNS trigger
            LANGUAGE plpgsql SET search_path = pg_catalog, public
            AS $$
            BEGIN
                IF NOT app.is_system() AND NEW.receipt_id IS NOT NULL
                   AND NOT EXISTS (SELECT 1 FROM attachments a WHERE a.id = NEW.receipt_id
                                   AND a.project_id = NEW.project_id) THEN
                    RAISE EXCEPTION 'receipt not in this project'
                        USING ERRCODE = 'foreign_key_violation';
                END IF;
                RETURN NEW;
            END
            $$;
        CREATE TRIGGER cost_entries_check_receipt BEFORE INSERT OR UPDATE ON cost_entries
            FOR EACH ROW EXECUTE FUNCTION app.cost_entries_check_receipt();

        CREATE TABLE cost_items (
            id           uuid PRIMARY KEY DEFAULT uuidv7(),
            cost_id      uuid NOT NULL REFERENCES cost_entries (id) ON DELETE CASCADE,
            project_id   uuid NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
            text         text NOT NULL CHECK (length(text) BETWEEN 1 AND 500),
            quantity     numeric(12, 3) CHECK (quantity IS NULL OR quantity >= 0),
            price_cents  bigint CHECK (price_cents IS NULL
                                       OR price_cents BETWEEN 0 AND 1000000000000),
            list_item_id uuid REFERENCES list_items (id) ON DELETE SET NULL,
            created_by   uuid NOT NULL REFERENCES users (id),
            created_at   timestamptz NOT NULL DEFAULT now(),
            updated_at   timestamptz NOT NULL DEFAULT now(),
            version      integer NOT NULL DEFAULT 1
        );
        CREATE INDEX cost_items_cost_idx ON cost_items (cost_id, created_at);
        CREATE INDEX cost_items_project_idx ON cost_items (project_id);
        CREATE INDEX cost_items_list_item_idx ON cost_items (list_item_id);

        ALTER TABLE cost_items ENABLE ROW LEVEL SECURITY;
        ALTER TABLE cost_items FORCE ROW LEVEL SECURITY;
        CREATE POLICY cost_items_select ON cost_items FOR SELECT TO planhaven_app
            USING (app.is_system() OR app.can_read(project_id));
        CREATE POLICY cost_items_insert ON cost_items FOR INSERT TO planhaven_app
            WITH CHECK (app.can_write(project_id) AND created_by = app.current_user_id());
        CREATE POLICY cost_items_update ON cost_items FOR UPDATE TO planhaven_app
            USING (app.can_write(project_id)) WITH CHECK (app.can_write(project_id));
        CREATE POLICY cost_items_delete ON cost_items FOR DELETE TO planhaven_app
            USING (app.can_write(project_id));
        REVOKE ALL ON cost_items FROM PUBLIC;
        GRANT SELECT, INSERT, DELETE ON cost_items TO planhaven_app;
        GRANT UPDATE (text, quantity, price_cents, updated_at, version) ON cost_items
            TO planhaven_app;

        -- An item belongs to a cost entry, and comes from a list item, of the same project.
        CREATE FUNCTION app.cost_items_same_project() RETURNS trigger
            LANGUAGE plpgsql SET search_path = pg_catalog, public
            AS $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM cost_entries c WHERE c.id = NEW.cost_id
                               AND c.project_id = NEW.project_id)
                   OR (NEW.list_item_id IS NOT NULL
                       AND NOT EXISTS (SELECT 1 FROM list_items i WHERE i.id = NEW.list_item_id
                                       AND i.project_id = NEW.project_id)) THEN
                    RAISE EXCEPTION 'cost item must be in the same project'
                        USING ERRCODE = 'foreign_key_violation';
                END IF;
                RETURN NEW;
            END
            $$;
        CREATE TRIGGER cost_items_same_project BEFORE INSERT ON cost_items
            FOR EACH ROW EXECUTE FUNCTION app.cost_items_same_project();
    """)


def downgrade() -> None:
    raise NotImplementedError("Downgrades are not supported; restore from backup.")
