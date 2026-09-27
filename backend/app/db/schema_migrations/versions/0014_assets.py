"""Assets: the durable things projects are about (vehicle, boat, house, ...) (ADR 0005, A§7.1).

Assets are shared like projects, with their own members and the same roles:
- Read: any member. Write: owner or editor. Membership and deleting: owner only.
- An asset always keeps an owner (constraint trigger), except for system jobs.
- A project may point at an asset (`projects.asset_id`); linking needs write access to the
  project and read access to the asset (trigger), so nobody can attach a project to an asset
  they can't see. Project members who can't read the asset just don't see it (RLS).
- An asset's projects are its service history; there's no separate history table.

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-28
"""

from app.db.schema_migrations.sqlscript import execute_script

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    execute_script("""
        CREATE TABLE assets (
            id          uuid PRIMARY KEY DEFAULT uuidv7(),
            name        text NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
            kind        text NOT NULL CHECK (kind IN
                        ('vehicle', 'boat', 'house', 'property', 'equipment', 'tool', 'other')),
            details     jsonb NOT NULL DEFAULT '[]'::jsonb
                        CHECK (jsonb_typeof(details) = 'array'
                               AND octet_length(details::text) <= 32768),
            notes       text NOT NULL DEFAULT '' CHECK (length(notes) <= 20000),
            created_by  uuid NOT NULL REFERENCES users (id),
            created_at  timestamptz NOT NULL DEFAULT now(),
            updated_at  timestamptz NOT NULL DEFAULT now(),
            version     integer NOT NULL DEFAULT 1,
            deleted_at  timestamptz
        );

        CREATE TABLE asset_members (
            asset_id   uuid NOT NULL REFERENCES assets (id) ON DELETE CASCADE,
            user_id    uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
            role       text NOT NULL CHECK (role IN ('owner', 'editor', 'viewer')),
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (asset_id, user_id)
        );
        CREATE INDEX asset_members_user_idx ON asset_members (user_id);

        ALTER TABLE projects ADD COLUMN asset_id uuid REFERENCES assets (id) ON DELETE SET NULL;
        CREATE INDEX projects_asset_idx ON projects (asset_id) WHERE deleted_at IS NULL;
        GRANT UPDATE (asset_id) ON projects TO planhaven_app;

        CREATE POLICY asset_members_definer_read ON asset_members FOR SELECT TO planhaven_owner
            USING (true);
        CREATE FUNCTION app.asset_role(p_asset uuid) RETURNS text
            LANGUAGE sql STABLE SECURITY DEFINER
            SET search_path = pg_catalog, public
            AS $$
                SELECT role FROM asset_members
                WHERE asset_id = p_asset AND user_id = app.current_user_id()
            $$;
        CREATE FUNCTION app.asset_has_members(p_asset uuid) RETURNS boolean
            LANGUAGE sql STABLE SECURITY DEFINER
            SET search_path = pg_catalog, public
            AS $$ SELECT EXISTS (SELECT 1 FROM asset_members WHERE asset_id = p_asset) $$;
        REVOKE ALL ON FUNCTION app.asset_role(uuid), app.asset_has_members(uuid) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app.asset_role(uuid), app.asset_has_members(uuid)
            TO planhaven_app;

        -- ---------------------------------------------------------- assets
        ALTER TABLE assets ENABLE ROW LEVEL SECURITY;
        ALTER TABLE assets FORCE ROW LEVEL SECURITY;
        CREATE POLICY assets_insert ON assets FOR INSERT TO planhaven_app
            WITH CHECK (created_by = app.current_user_id());
        CREATE POLICY assets_select ON assets FOR SELECT TO planhaven_app
            USING (app.is_system() OR app.asset_role(id) IS NOT NULL
                   OR (created_by = app.current_user_id() AND NOT app.asset_has_members(id)));
        CREATE POLICY assets_update ON assets FOR UPDATE TO planhaven_app
            USING (app.asset_role(id) IN ('owner', 'editor'))
            WITH CHECK (app.asset_role(id) IN ('owner', 'editor'));
        REVOKE ALL ON assets FROM PUBLIC;
        GRANT SELECT, INSERT ON assets TO planhaven_app;
        GRANT UPDATE (name, kind, details, notes, updated_at, version, deleted_at)
            ON assets TO planhaven_app;

        CREATE FUNCTION app.assets_guard_owner_fields() RETURNS trigger
            LANGUAGE plpgsql SET search_path = pg_catalog
            AS $$
            BEGIN
                IF NEW.deleted_at IS DISTINCT FROM OLD.deleted_at
                   AND app.asset_role(OLD.id) IS DISTINCT FROM 'owner' THEN
                    RAISE EXCEPTION 'only the asset owner can change this'
                        USING ERRCODE = 'insufficient_privilege';
                END IF;
                RETURN NEW;
            END
            $$;
        CREATE TRIGGER assets_guard_owner_fields BEFORE UPDATE ON assets
            FOR EACH ROW EXECUTE FUNCTION app.assets_guard_owner_fields();

        -- ---------------------------------------------------------- membership
        ALTER TABLE asset_members ENABLE ROW LEVEL SECURITY;
        ALTER TABLE asset_members FORCE ROW LEVEL SECURITY;
        CREATE POLICY asset_members_select ON asset_members FOR SELECT TO planhaven_app
            USING (app.is_system() OR app.asset_role(asset_id) IS NOT NULL);
        CREATE POLICY asset_members_insert ON asset_members FOR INSERT TO planhaven_app
            WITH CHECK (
                (NOT app.asset_has_members(asset_id) AND user_id = app.current_user_id()
                 AND role = 'owner'
                 AND EXISTS (SELECT 1 FROM assets a WHERE a.id = asset_id
                             AND a.created_by = app.current_user_id()))
                OR app.asset_role(asset_id) = 'owner'
            );
        CREATE POLICY asset_members_update ON asset_members FOR UPDATE TO planhaven_app
            USING (app.asset_role(asset_id) = 'owner')
            WITH CHECK (app.asset_role(asset_id) = 'owner');
        CREATE POLICY asset_members_delete ON asset_members FOR DELETE TO planhaven_app
            USING (app.asset_role(asset_id) = 'owner' OR user_id = app.current_user_id());
        REVOKE ALL ON asset_members FROM PUBLIC;
        GRANT SELECT, INSERT, DELETE ON asset_members TO planhaven_app;
        GRANT UPDATE (role) ON asset_members TO planhaven_app;

        CREATE FUNCTION app.asset_members_keep_an_owner() RETURNS trigger
            LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public
            AS $$
            BEGIN
                IF NOT app.is_system()
                   AND NOT EXISTS (SELECT 1 FROM asset_members m
                                   WHERE m.asset_id = OLD.asset_id AND m.role = 'owner') THEN
                    RAISE EXCEPTION 'an asset must keep at least one owner'
                        USING ERRCODE = 'check_violation';
                END IF;
                RETURN NULL;
            END
            $$;
        CREATE CONSTRAINT TRIGGER asset_members_keep_an_owner
            AFTER UPDATE OR DELETE ON asset_members DEFERRABLE INITIALLY IMMEDIATE
            FOR EACH ROW EXECUTE FUNCTION app.asset_members_keep_an_owner();

        -- ---------------------------------------------------------- project link
        CREATE FUNCTION app.projects_guard_asset_link() RETURNS trigger
            LANGUAGE plpgsql SET search_path = pg_catalog
            AS $$
            BEGIN
                IF NEW.asset_id IS NOT NULL
                   AND NEW.asset_id IS DISTINCT FROM OLD.asset_id
                   AND NOT app.is_system()
                   AND app.asset_role(NEW.asset_id) IS NULL THEN
                    RAISE EXCEPTION 'asset not found'
                        USING ERRCODE = 'insufficient_privilege';
                END IF;
                RETURN NEW;
            END
            $$;
        CREATE TRIGGER projects_guard_asset_link BEFORE UPDATE OF asset_id ON projects
            FOR EACH ROW EXECUTE FUNCTION app.projects_guard_asset_link();
    """)


def downgrade() -> None:
    raise NotImplementedError("Downgrades are not supported; restore from backup.")
