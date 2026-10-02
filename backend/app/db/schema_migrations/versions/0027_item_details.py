"""Details for list items: notes, a website, and attached photos and files; and moving items
to another list of the same project (owner requests, 2026-10-02).

An attachment can belong to one list item of its own project; it stays one of the project's
files either way, and deleting the item leaves the file in place. Share links can't change the
new columns or move items (the column guard on list_items lets guests change only the tick).
An item can only move within its project (list_items_project_matches, migration 0011).

Revision ID: 0027
Revises: 0026
Create Date: 2026-10-02
"""

from app.db.schema_migrations.sqlscript import execute_script

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    execute_script("""
        ALTER TABLE list_items
            ADD COLUMN notes text NOT NULL DEFAULT '' CHECK (length(notes) <= 4000),
            ADD COLUMN website text NOT NULL DEFAULT ''
                CHECK (length(website) <= 500 AND (website = '' OR website ~ '^https?://'));
        GRANT UPDATE (notes, website, list_id) ON list_items TO planhaven_app;

        ALTER TABLE attachments
            ADD COLUMN list_item_id uuid REFERENCES list_items (id) ON DELETE SET NULL;
        CREATE INDEX attachments_list_item_idx ON attachments (list_item_id)
            WHERE list_item_id IS NOT NULL AND deleted_at IS NULL;

        -- An attachment's item must be in the attachment's project.
        CREATE FUNCTION app.attachments_item_matches() RETURNS trigger
            LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public
            AS $$
            BEGIN
                IF NEW.list_item_id IS NOT NULL AND NOT EXISTS (
                    SELECT 1 FROM list_items i
                    WHERE i.id = NEW.list_item_id AND i.project_id = NEW.project_id) THEN
                    RAISE EXCEPTION 'attachment item project mismatch'
                        USING ERRCODE = 'check_violation';
                END IF;
                RETURN NEW;
            END
            $$;
        CREATE TRIGGER attachments_item_matches BEFORE INSERT OR UPDATE OF list_item_id, project_id
            ON attachments FOR EACH ROW EXECUTE FUNCTION app.attachments_item_matches();
        CREATE POLICY list_items_definer_read ON list_items FOR SELECT TO planhaven_owner
            USING (true);
    """)


def downgrade() -> None:
    raise NotImplementedError("Downgrades are not supported; restore from backup.")
