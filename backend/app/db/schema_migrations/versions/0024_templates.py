"""Templates: lists and task sets saved for later projects (owner request, 2026-09-28).

A template is private to the person who made it until they share it, one person at a time,
like contacts (owner, editor, viewer; at least one owner). Items keep the text, quantity,
unit and estimated price (lists) or the title and notes (tasks).

Templates are deleted outright by an owner (they're copies; the lists and tasks made from
them stay). Members and items go with them.

Revision ID: 0024
Revises: 0023
Create Date: 2026-09-28
"""

from app.db.schema_migrations.sqlscript import execute_script

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    execute_script("""
        CREATE TABLE templates (
            id          uuid PRIMARY KEY DEFAULT uuidv7(),
            kind        text NOT NULL CHECK (kind IN ('list', 'tasks')),
            list_kind   text CHECK ((kind = 'list'
                                     AND list_kind IN ('shopping', 'parts', 'checklist'))
                                    OR (kind = 'tasks' AND list_kind IS NULL)),
            name        text NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
            created_by  uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
            created_at  timestamptz NOT NULL DEFAULT now(),
            updated_at  timestamptz NOT NULL DEFAULT now(),
            version     integer NOT NULL DEFAULT 1
        );
        CREATE TABLE template_items (
            id          uuid PRIMARY KEY DEFAULT uuidv7(),
            template_id uuid NOT NULL REFERENCES templates (id) ON DELETE CASCADE,
            position    integer NOT NULL CHECK (position >= 0),
            text        text NOT NULL CHECK (length(text) BETWEEN 1 AND 500),
            quantity    numeric(12, 3) CHECK (quantity IS NULL OR quantity >= 0),
            unit        text CHECK (length(unit) <= 30),
            price_cents bigint CHECK (price_cents IS NULL
                                      OR price_cents BETWEEN 0 AND 1000000000000),
            notes       text NOT NULL DEFAULT '' CHECK (length(notes) <= 20000)
        );
        CREATE INDEX template_items_template_idx ON template_items (template_id, position);
        CREATE TABLE template_members (
            template_id uuid NOT NULL REFERENCES templates (id) ON DELETE CASCADE,
            user_id     uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
            role        text NOT NULL CHECK (role IN ('owner', 'editor', 'viewer')),
            created_at  timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (template_id, user_id)
        );
        CREATE INDEX template_members_user_idx ON template_members (user_id);

        -- ---------------------------------------------------------- roles (as for contacts)
        CREATE POLICY template_members_definer_read ON template_members FOR SELECT
            TO planhaven_owner USING (true);
        CREATE FUNCTION app.template_role(p_template uuid) RETURNS text
            LANGUAGE sql STABLE SECURITY DEFINER
            SET search_path = pg_catalog, public
            AS $$
                SELECT role FROM template_members
                WHERE template_id = p_template AND user_id = app.current_user_id()
            $$;
        CREATE FUNCTION app.template_has_members(p_template uuid) RETURNS boolean
            LANGUAGE sql STABLE SECURITY DEFINER
            SET search_path = pg_catalog, public
            AS $$ SELECT EXISTS (SELECT 1 FROM template_members WHERE template_id = p_template) $$;
        REVOKE ALL ON FUNCTION app.template_role(uuid), app.template_has_members(uuid)
            FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app.template_role(uuid), app.template_has_members(uuid)
            TO planhaven_app;

        ALTER TABLE templates ENABLE ROW LEVEL SECURITY;
        ALTER TABLE templates FORCE ROW LEVEL SECURITY;
        CREATE POLICY templates_insert ON templates FOR INSERT TO planhaven_app
            WITH CHECK (created_by = app.current_user_id());
        CREATE POLICY templates_select ON templates FOR SELECT TO planhaven_app
            USING (app.is_system() OR app.template_role(id) IS NOT NULL
                   OR (created_by = app.current_user_id() AND NOT app.template_has_members(id)));
        CREATE POLICY templates_update ON templates FOR UPDATE TO planhaven_app
            USING (app.template_role(id) IN ('owner', 'editor'))
            WITH CHECK (app.template_role(id) IN ('owner', 'editor'));
        CREATE POLICY templates_delete ON templates FOR DELETE TO planhaven_app
            USING (app.template_role(id) = 'owner');
        REVOKE ALL ON templates FROM PUBLIC;
        GRANT SELECT, INSERT, DELETE ON templates TO planhaven_app;
        GRANT UPDATE (name, updated_at, version) ON templates TO planhaven_app;

        ALTER TABLE template_items ENABLE ROW LEVEL SECURITY;
        ALTER TABLE template_items FORCE ROW LEVEL SECURITY;
        CREATE POLICY template_items_select ON template_items FOR SELECT TO planhaven_app
            USING (app.template_role(template_id) IS NOT NULL);
        CREATE POLICY template_items_insert ON template_items FOR INSERT TO planhaven_app
            WITH CHECK (app.template_role(template_id) IN ('owner', 'editor'));
        CREATE POLICY template_items_delete ON template_items FOR DELETE TO planhaven_app
            USING (app.template_role(template_id) IN ('owner', 'editor'));
        REVOKE ALL ON template_items FROM PUBLIC;
        GRANT SELECT, INSERT, DELETE ON template_items TO planhaven_app;

        ALTER TABLE template_members ENABLE ROW LEVEL SECURITY;
        ALTER TABLE template_members FORCE ROW LEVEL SECURITY;
        CREATE POLICY template_members_select ON template_members FOR SELECT TO planhaven_app
            USING (app.is_system() OR app.template_role(template_id) IS NOT NULL);
        CREATE POLICY template_members_insert ON template_members FOR INSERT TO planhaven_app
            WITH CHECK (
                (NOT app.template_has_members(template_id) AND user_id = app.current_user_id()
                 AND role = 'owner'
                 AND EXISTS (SELECT 1 FROM templates t WHERE t.id = template_id
                             AND t.created_by = app.current_user_id()))
                OR app.template_role(template_id) = 'owner'
            );
        CREATE POLICY template_members_update ON template_members FOR UPDATE TO planhaven_app
            USING (app.template_role(template_id) = 'owner')
            WITH CHECK (app.template_role(template_id) = 'owner');
        CREATE POLICY template_members_delete ON template_members FOR DELETE TO planhaven_app
            USING (app.template_role(template_id) = 'owner' OR user_id = app.current_user_id());
        REVOKE ALL ON template_members FROM PUBLIC;
        GRANT SELECT, INSERT, DELETE ON template_members TO planhaven_app;
        GRANT UPDATE (role) ON template_members TO planhaven_app;

        -- At least one owner, unless the template itself is being deleted.
        CREATE FUNCTION app.template_members_keep_an_owner() RETURNS trigger
            LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public
            AS $$
            BEGIN
                IF NOT app.is_system()
                   AND EXISTS (SELECT 1 FROM templates t WHERE t.id = OLD.template_id)
                   AND NOT EXISTS (SELECT 1 FROM template_members m
                                   WHERE m.template_id = OLD.template_id
                                     AND m.role = 'owner') THEN
                    RAISE EXCEPTION 'a template must keep at least one owner'
                        USING ERRCODE = 'check_violation';
                END IF;
                RETURN NULL;
            END
            $$;
        CREATE CONSTRAINT TRIGGER template_members_keep_an_owner
            AFTER UPDATE OR DELETE ON template_members DEFERRABLE INITIALLY IMMEDIATE
            FOR EACH ROW EXECUTE FUNCTION app.template_members_keep_an_owner();
    """)


def downgrade() -> None:
    raise NotImplementedError("Downgrades are not supported; restore from backup.")
