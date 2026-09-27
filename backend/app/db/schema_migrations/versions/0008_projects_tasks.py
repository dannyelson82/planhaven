"""Projects, membership and tasks: the first user content (ARCHITECTURE.md §7, §8.3).

Membership drives access in the database itself. `app.project_role(project_id)` returns the
current user's role (owner / editor / viewer) or NULL. It is SECURITY DEFINER so policies can
consult project_members without recursive RLS; it runs as planhaven_owner, which gets a
read-only policy on project_members for exactly this purpose.

- Read: any member. Tasks are also readable by their assignee (chores, ADR 0013).
- Write: owner or editor.
- Membership, `local_ai_only`, and deleting a project: owner only.
- Deletes are soft (`deleted_at`); the app role has no DELETE on these tables.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-27
"""

from app.db.schema_migrations.sqlscript import execute_script

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    execute_script("""
        CREATE TABLE projects (
            id            uuid PRIMARY KEY DEFAULT uuidv7(),
            title         text NOT NULL CHECK (length(title) BETWEEN 1 AND 200),
            description   text NOT NULL DEFAULT '' CHECK (length(description) <= 20000),
            stage         text NOT NULL DEFAULT 'idea' CHECK (stage IN
                          ('idea', 'planning', 'ready', 'in_progress', 'done', 'archived')),
            local_ai_only boolean NOT NULL DEFAULT false,
            created_by    uuid NOT NULL REFERENCES users (id),
            created_at    timestamptz NOT NULL DEFAULT now(),
            updated_at    timestamptz NOT NULL DEFAULT now(),
            version       integer NOT NULL DEFAULT 1,
            deleted_at    timestamptz
        );
        CREATE INDEX projects_updated_idx ON projects (updated_at DESC, id DESC)
            WHERE deleted_at IS NULL;

        CREATE TABLE project_members (
            project_id uuid NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
            user_id    uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
            role       text NOT NULL CHECK (role IN ('owner', 'editor', 'viewer')),
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (project_id, user_id)
        );
        CREATE INDEX project_members_user_idx ON project_members (user_id);

        CREATE TABLE tasks (
            id          uuid PRIMARY KEY DEFAULT uuidv7(),
            project_id  uuid NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
            title       text NOT NULL CHECK (length(title) BETWEEN 1 AND 300),
            notes       text NOT NULL DEFAULT '' CHECK (length(notes) <= 20000),
            due_at      timestamptz,
            due_all_day boolean NOT NULL DEFAULT false,
            assignee_id uuid REFERENCES users (id) ON DELETE SET NULL,
            position    double precision NOT NULL DEFAULT 0,
            done_at     timestamptz,
            done_by     uuid REFERENCES users (id) ON DELETE SET NULL,
            created_by  uuid NOT NULL REFERENCES users (id),
            created_at  timestamptz NOT NULL DEFAULT now(),
            updated_at  timestamptz NOT NULL DEFAULT now(),
            version     integer NOT NULL DEFAULT 1,
            deleted_at  timestamptz
        );
        CREATE INDEX tasks_project_idx ON tasks (project_id, done_at, position)
            WHERE deleted_at IS NULL;
        CREATE INDEX tasks_assignee_idx ON tasks (assignee_id) WHERE deleted_at IS NULL;

        -- Membership lookups for policies (see module docstring).
        CREATE POLICY members_definer_read ON project_members FOR SELECT TO planhaven_owner
            USING (true);

        CREATE FUNCTION app.project_role(p_project uuid) RETURNS text
            LANGUAGE sql STABLE SECURITY DEFINER
            SET search_path = pg_catalog, public
            AS $$
                SELECT role FROM project_members
                WHERE project_id = p_project AND user_id = app.current_user_id()
            $$;
        CREATE FUNCTION app.project_has_members(p_project uuid) RETURNS boolean
            LANGUAGE sql STABLE SECURITY DEFINER
            SET search_path = pg_catalog, public
            AS $$ SELECT EXISTS (SELECT 1 FROM project_members WHERE project_id = p_project) $$;
        CREATE FUNCTION app.can_read(p_project uuid) RETURNS boolean
            LANGUAGE sql STABLE SET search_path = pg_catalog
            AS $$ SELECT app.project_role(p_project) IS NOT NULL $$;
        CREATE FUNCTION app.can_write(p_project uuid) RETURNS boolean
            LANGUAGE sql STABLE SET search_path = pg_catalog
            AS $$ SELECT app.project_role(p_project) IN ('owner', 'editor') $$;
        REVOKE ALL ON FUNCTION app.project_role(uuid), app.project_has_members(uuid),
            app.can_read(uuid), app.can_write(uuid) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app.project_role(uuid), app.project_has_members(uuid),
            app.can_read(uuid), app.can_write(uuid) TO planhaven_app;

        -- ---------------------------------------------------------- projects
        ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
        ALTER TABLE projects FORCE ROW LEVEL SECURITY;
        -- The creator may insert (and see) a new project before its owner membership exists.
        CREATE POLICY projects_insert ON projects FOR INSERT TO planhaven_app
            WITH CHECK (created_by = app.current_user_id());
        CREATE POLICY projects_select ON projects FOR SELECT TO planhaven_app
            USING (app.can_read(id)
                   OR (created_by = app.current_user_id() AND NOT app.project_has_members(id)));
        CREATE POLICY projects_update ON projects FOR UPDATE TO planhaven_app
            USING (app.can_write(id)) WITH CHECK (app.can_write(id));
        REVOKE ALL ON projects FROM PUBLIC;
        GRANT SELECT, INSERT ON projects TO planhaven_app;
        GRANT UPDATE (title, description, stage, local_ai_only, updated_at, version, deleted_at)
            ON projects TO planhaven_app;

        CREATE FUNCTION app.projects_guard_owner_fields() RETURNS trigger
            LANGUAGE plpgsql SET search_path = pg_catalog
            AS $$
            BEGIN
                IF (NEW.local_ai_only IS DISTINCT FROM OLD.local_ai_only
                    OR NEW.deleted_at IS DISTINCT FROM OLD.deleted_at)
                   AND app.project_role(OLD.id) IS DISTINCT FROM 'owner' THEN
                    RAISE EXCEPTION 'only the project owner can change this'
                        USING ERRCODE = 'insufficient_privilege';
                END IF;
                RETURN NEW;
            END
            $$;
        CREATE TRIGGER projects_guard_owner_fields BEFORE UPDATE ON projects
            FOR EACH ROW EXECUTE FUNCTION app.projects_guard_owner_fields();

        -- ---------------------------------------------------------- membership
        ALTER TABLE project_members ENABLE ROW LEVEL SECURITY;
        ALTER TABLE project_members FORCE ROW LEVEL SECURITY;
        CREATE POLICY members_select ON project_members FOR SELECT TO planhaven_app
            USING (app.can_read(project_id));
        -- The first member of a new project must be its creator, as owner; after that only
        -- owners manage membership.
        CREATE POLICY members_insert ON project_members FOR INSERT TO planhaven_app
            WITH CHECK (
                (NOT app.project_has_members(project_id) AND user_id = app.current_user_id()
                 AND role = 'owner'
                 AND EXISTS (SELECT 1 FROM projects p WHERE p.id = project_id
                             AND p.created_by = app.current_user_id()))
                OR app.project_role(project_id) = 'owner'
            );
        CREATE POLICY members_update ON project_members FOR UPDATE TO planhaven_app
            USING (app.project_role(project_id) = 'owner')
            WITH CHECK (app.project_role(project_id) = 'owner');
        CREATE POLICY members_delete ON project_members FOR DELETE TO planhaven_app
            USING (app.project_role(project_id) = 'owner');
        REVOKE ALL ON project_members FROM PUBLIC;
        GRANT SELECT, INSERT, DELETE ON project_members TO planhaven_app;
        GRANT UPDATE (role) ON project_members TO planhaven_app;

        -- ---------------------------------------------------------- tasks
        ALTER TABLE tasks ENABLE ROW LEVEL SECURITY;
        ALTER TABLE tasks FORCE ROW LEVEL SECURITY;
        CREATE POLICY tasks_select ON tasks FOR SELECT TO planhaven_app
            USING (app.can_read(project_id) OR assignee_id = app.current_user_id());
        CREATE POLICY tasks_insert ON tasks FOR INSERT TO planhaven_app
            WITH CHECK (app.can_write(project_id) AND created_by = app.current_user_id());
        CREATE POLICY tasks_update ON tasks FOR UPDATE TO planhaven_app
            USING (app.can_write(project_id)) WITH CHECK (app.can_write(project_id));
        REVOKE ALL ON tasks FROM PUBLIC;
        GRANT SELECT, INSERT ON tasks TO planhaven_app;
        GRANT UPDATE (title, notes, due_at, due_all_day, assignee_id, position, done_at,
                      done_by, updated_at, version, deleted_at) ON tasks TO planhaven_app;
    """)


def downgrade() -> None:
    raise NotImplementedError("Downgrades are not supported; restore from backup.")
