"""Lists (shopping, parts, checklists) and their items (ARCHITECTURE.md §7.1).

Same access rules as tasks: members read, owners/editors write, soft deletes only. Items carry
their project_id so RLS needs no join. Idempotency keys let offline clients replay creates
safely (A§8.2, A§13.4).

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-28
"""

from app.db.schema_migrations.sqlscript import execute_script

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    execute_script("""
        CREATE TABLE lists (
            id          uuid PRIMARY KEY DEFAULT uuidv7(),
            project_id  uuid NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
            title       text NOT NULL CHECK (length(title) BETWEEN 1 AND 200),
            kind        text NOT NULL DEFAULT 'shopping'
                        CHECK (kind IN ('shopping', 'parts', 'checklist')),
            position    double precision NOT NULL DEFAULT 0,
            created_by  uuid NOT NULL REFERENCES users (id),
            created_at  timestamptz NOT NULL DEFAULT now(),
            updated_at  timestamptz NOT NULL DEFAULT now(),
            version     integer NOT NULL DEFAULT 1,
            deleted_at  timestamptz
        );
        CREATE INDEX lists_project_idx ON lists (project_id, position) WHERE deleted_at IS NULL;

        CREATE TABLE list_items (
            id          uuid PRIMARY KEY DEFAULT uuidv7(),
            list_id     uuid NOT NULL REFERENCES lists (id) ON DELETE CASCADE,
            project_id  uuid NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
            text        text NOT NULL CHECK (length(text) BETWEEN 1 AND 500),
            quantity    numeric(12, 3) CHECK (quantity IS NULL OR quantity >= 0),
            unit        text CHECK (length(unit) <= 30),
            price_cents bigint CHECK (price_cents IS NULL OR price_cents >= 0),
            position    double precision NOT NULL DEFAULT 0,
            checked_at  timestamptz,
            checked_by  uuid REFERENCES users (id) ON DELETE SET NULL,
            created_by  uuid NOT NULL REFERENCES users (id),
            created_at  timestamptz NOT NULL DEFAULT now(),
            updated_at  timestamptz NOT NULL DEFAULT now(),
            version     integer NOT NULL DEFAULT 1,
            deleted_at  timestamptz
        );
        CREATE INDEX list_items_list_idx ON list_items (list_id, checked_at, position)
            WHERE deleted_at IS NULL;

        -- An item's project must be its list's project.
        CREATE FUNCTION app.list_items_project_matches() RETURNS trigger
            LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public
            AS $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM lists l
                               WHERE l.id = NEW.list_id AND l.project_id = NEW.project_id) THEN
                    RAISE EXCEPTION 'list item project mismatch' USING ERRCODE = 'check_violation';
                END IF;
                RETURN NEW;
            END
            $$;
        CREATE TRIGGER list_items_project_matches BEFORE INSERT OR UPDATE OF list_id, project_id
            ON list_items FOR EACH ROW EXECUTE FUNCTION app.list_items_project_matches();
        CREATE POLICY lists_definer_read ON lists FOR SELECT TO planhaven_owner USING (true);

        ALTER TABLE lists ENABLE ROW LEVEL SECURITY;
        ALTER TABLE lists FORCE ROW LEVEL SECURITY;
        CREATE POLICY lists_select ON lists FOR SELECT TO planhaven_app
            USING (app.is_system() OR app.can_read(project_id));
        CREATE POLICY lists_insert ON lists FOR INSERT TO planhaven_app
            WITH CHECK (app.can_write(project_id) AND created_by = app.current_user_id());
        CREATE POLICY lists_update ON lists FOR UPDATE TO planhaven_app
            USING (app.can_write(project_id)) WITH CHECK (app.can_write(project_id));
        REVOKE ALL ON lists FROM PUBLIC;
        GRANT SELECT, INSERT ON lists TO planhaven_app;
        GRANT UPDATE (title, kind, position, updated_at, version, deleted_at) ON lists
            TO planhaven_app;

        ALTER TABLE list_items ENABLE ROW LEVEL SECURITY;
        ALTER TABLE list_items FORCE ROW LEVEL SECURITY;
        CREATE POLICY list_items_select ON list_items FOR SELECT TO planhaven_app
            USING (app.is_system() OR app.can_read(project_id));
        CREATE POLICY list_items_insert ON list_items FOR INSERT TO planhaven_app
            WITH CHECK (app.can_write(project_id) AND created_by = app.current_user_id());
        CREATE POLICY list_items_update ON list_items FOR UPDATE TO planhaven_app
            USING (app.can_write(project_id)) WITH CHECK (app.can_write(project_id));
        REVOKE ALL ON list_items FROM PUBLIC;
        GRANT SELECT, INSERT ON list_items TO planhaven_app;
        GRANT UPDATE (text, quantity, unit, price_cents, position, checked_at, checked_by,
                      updated_at, version, deleted_at) ON list_items TO planhaven_app;

        CREATE TABLE idempotency_keys (
            user_id     uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
            key         text NOT NULL CHECK (length(key) BETWEEN 8 AND 100),
            scope       text NOT NULL CHECK (length(scope) <= 100),
            resource_id uuid NOT NULL,
            created_at  timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (user_id, key)
        );
        ALTER TABLE idempotency_keys ENABLE ROW LEVEL SECURITY;
        ALTER TABLE idempotency_keys FORCE ROW LEVEL SECURITY;
        CREATE POLICY idempotency_own ON idempotency_keys FOR ALL TO planhaven_app
            USING (app.is_system() OR user_id = app.current_user_id())
            WITH CHECK (app.is_system() OR user_id = app.current_user_id());
        REVOKE ALL ON idempotency_keys FROM PUBLIC;
        GRANT SELECT, INSERT, DELETE ON idempotency_keys TO planhaven_app;
    """)


def downgrade() -> None:
    raise NotImplementedError("Downgrades are not supported; restore from backup.")
