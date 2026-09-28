"""Share links for people without an account (ADR 0015; owner decisions 2026-09-28).

A link belongs to a project and says, box by box, what whoever holds it may see and do. It is
a capability: the token is stored only as a SHA-256 hash, it expires (1 year at most), and it
can be revoked. A guest opens it once (name, and PIN if set) and gets a short-lived session.

The database checks every guest read and write item by item (owner's choice, 2026-09-28):
guest transactions set `app.share_link`, and `app.link_allows(project, what, item)` answers
from the link's boxes and chosen items. Extra policies on projects, tasks, notes, lists, list
items and attachments grant guests exactly that and nothing else (they have no user id, so
the existing member policies give them nothing). Triggers stop a guest from changing any
column but the one their action needs (ticking a task or item, adding to a note). A link
stops working when it's revoked or expired, or when its creator can no longer edit the
project; the app also checks the creator's account and the project on every request.

Revision ID: 0026
Revises: 0025
Create Date: 2026-09-28
"""

from app.db.schema_migrations.sqlscript import execute_script

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    execute_script("""
        CREATE TABLE share_links (
            id             uuid PRIMARY KEY DEFAULT uuidv7(),
            project_id     uuid NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
            created_by     uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
            name           text NOT NULL CHECK (length(name) BETWEEN 1 AND 100),
            token_hash     text NOT NULL UNIQUE CHECK (token_hash ~ '^[0-9a-f]{64}$'),
            pin_hash       text CHECK (length(pin_hash) <= 300),
            tasks_view     text NOT NULL DEFAULT 'none'
                           CHECK (tasks_view IN ('none', 'all', 'chosen')),
            tasks_tick     boolean NOT NULL DEFAULT false,
            files_view     boolean NOT NULL DEFAULT false,
            files_add      boolean NOT NULL DEFAULT false,
            lists_tick     boolean NOT NULL DEFAULT false,
            append_note_id uuid REFERENCES notes (id) ON DELETE SET NULL,
            created_at     timestamptz NOT NULL DEFAULT now(),
            expires_at     timestamptz NOT NULL,
            revoked_at     timestamptz,
            last_used_at   timestamptz,
            CHECK (expires_at <= created_at + interval '366 days'),
            CHECK (NOT tasks_tick OR tasks_view <> 'none')
        );
        CREATE INDEX share_links_project_idx ON share_links (project_id);
        CREATE TABLE share_link_items (
            link_id uuid NOT NULL REFERENCES share_links (id) ON DELETE CASCADE,
            kind    text NOT NULL CHECK (kind IN ('task', 'note', 'list')),
            item_id uuid NOT NULL,
            PRIMARY KEY (link_id, kind, item_id)
        );
        CREATE TABLE share_sessions (
            token_hash text PRIMARY KEY CHECK (token_hash ~ '^[0-9a-f]{64}$'),
            link_id    uuid NOT NULL REFERENCES share_links (id) ON DELETE CASCADE,
            guest_name text NOT NULL CHECK (length(guest_name) BETWEEN 1 AND 60),
            created_at timestamptz NOT NULL DEFAULT now(),
            expires_at timestamptz NOT NULL
        );
        CREATE INDEX share_sessions_link_idx ON share_sessions (link_id);
        CREATE TABLE share_link_events (
            id         uuid PRIMARY KEY DEFAULT uuidv7(),
            link_id    uuid NOT NULL REFERENCES share_links (id) ON DELETE CASCADE,
            at         timestamptz NOT NULL DEFAULT now(),
            guest_name text NOT NULL CHECK (length(guest_name) BETWEEN 1 AND 60),
            action     text NOT NULL CHECK (length(action) BETWEEN 1 AND 40),
            detail     text NOT NULL DEFAULT '' CHECK (length(detail) <= 300)
        );
        CREATE INDEX share_link_events_link_idx ON share_link_events (link_id, at DESC);

        -- ---------------------------------------------------------- the guest's link
        CREATE FUNCTION app.current_share_link() RETURNS uuid
            LANGUAGE sql STABLE PARALLEL SAFE SET search_path = pg_catalog
            AS $$ SELECT nullif(current_setting('app.share_link', true), '')::uuid $$;

        CREATE POLICY share_links_definer_read ON share_links FOR SELECT
            TO planhaven_owner USING (true);
        CREATE POLICY share_link_items_definer_read ON share_link_items FOR SELECT
            TO planhaven_owner USING (true);

        -- What the current link allows, for one thing in one project. Only for a live link
        -- (not revoked, not expired) whose creator can still edit the project.
        CREATE FUNCTION app.link_allows(p_project uuid, p_what text, p_item uuid)
            RETURNS boolean
            LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
            AS $$
                SELECT EXISTS (
                    SELECT 1 FROM share_links l
                    JOIN project_members m ON m.project_id = l.project_id
                                          AND m.user_id = l.created_by
                                          AND m.role IN ('owner', 'editor')
                    WHERE l.id = app.current_share_link()
                      AND l.project_id = p_project
                      AND l.revoked_at IS NULL AND l.expires_at > now()
                      AND CASE p_what
                          WHEN 'project' THEN true
                          WHEN 'task.read' THEN
                              l.tasks_view = 'all'
                              OR (l.tasks_view = 'chosen' AND EXISTS (
                                  SELECT 1 FROM share_link_items i WHERE i.link_id = l.id
                                  AND i.kind = 'task' AND i.item_id = p_item))
                          WHEN 'task.tick' THEN
                              l.tasks_tick AND (
                                  l.tasks_view = 'all'
                                  OR (l.tasks_view = 'chosen' AND EXISTS (
                                      SELECT 1 FROM share_link_items i WHERE i.link_id = l.id
                                      AND i.kind = 'task' AND i.item_id = p_item)))
                          WHEN 'note.read' THEN
                              l.append_note_id = p_item OR EXISTS (
                                  SELECT 1 FROM share_link_items i WHERE i.link_id = l.id
                                  AND i.kind = 'note' AND i.item_id = p_item)
                          WHEN 'note.append' THEN l.append_note_id = p_item
                          WHEN 'list.read' THEN EXISTS (
                              SELECT 1 FROM share_link_items i WHERE i.link_id = l.id
                              AND i.kind = 'list' AND i.item_id = p_item)
                          WHEN 'list.tick' THEN l.lists_tick AND EXISTS (
                              SELECT 1 FROM share_link_items i WHERE i.link_id = l.id
                              AND i.kind = 'list' AND i.item_id = p_item)
                          WHEN 'file.read' THEN l.files_view
                          WHEN 'file.add' THEN l.files_add
                          ELSE false
                      END
                )
            $$;
        CREATE FUNCTION app.link_creator() RETURNS uuid
            LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
            AS $$ SELECT created_by FROM share_links WHERE id = app.current_share_link() $$;
        REVOKE ALL ON FUNCTION app.current_share_link(), app.link_allows(uuid, text, uuid),
            app.link_creator() FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app.current_share_link(), app.link_allows(uuid, text, uuid),
            app.link_creator() TO planhaven_app;

        -- ---------------------------------------------------------- guests' access to data
        CREATE POLICY projects_link_select ON projects FOR SELECT TO planhaven_app
            USING (app.link_allows(id, 'project', NULL));
        CREATE POLICY tasks_link_select ON tasks FOR SELECT TO planhaven_app
            USING (app.link_allows(project_id, 'task.read', id));
        CREATE POLICY tasks_link_update ON tasks FOR UPDATE TO planhaven_app
            USING (app.link_allows(project_id, 'task.tick', id))
            WITH CHECK (app.link_allows(project_id, 'task.tick', id));
        CREATE POLICY notes_link_select ON notes FOR SELECT TO planhaven_app
            USING (app.link_allows(project_id, 'note.read', id));
        CREATE POLICY notes_link_update ON notes FOR UPDATE TO planhaven_app
            USING (app.link_allows(project_id, 'note.append', id))
            WITH CHECK (app.link_allows(project_id, 'note.append', id));
        CREATE POLICY lists_link_select ON lists FOR SELECT TO planhaven_app
            USING (app.link_allows(project_id, 'list.read', id));
        CREATE POLICY list_items_link_select ON list_items FOR SELECT TO planhaven_app
            USING (app.link_allows(project_id, 'list.read', list_id));
        CREATE POLICY list_items_link_update ON list_items FOR UPDATE TO planhaven_app
            USING (app.link_allows(project_id, 'list.tick', list_id))
            WITH CHECK (app.link_allows(project_id, 'list.tick', list_id));
        CREATE POLICY attachments_link_select ON attachments FOR SELECT TO planhaven_app
            USING (app.link_allows(project_id, 'file.read', id));
        CREATE POLICY attachments_link_insert ON attachments FOR INSERT TO planhaven_app
            WITH CHECK (app.link_allows(project_id, 'file.add', id)
                        AND created_by = app.link_creator());

        -- A guest changes only what their action needs.
        CREATE FUNCTION app.link_guard_columns() RETURNS trigger
            LANGUAGE plpgsql SET search_path = pg_catalog
            AS $$
            BEGIN
                IF app.current_share_link() IS NOT NULL
                   AND (to_jsonb(NEW) - TG_ARGV) IS DISTINCT FROM (to_jsonb(OLD) - TG_ARGV) THEN
                    RAISE EXCEPTION 'a share link can''t change this'
                        USING ERRCODE = 'insufficient_privilege';
                END IF;
                RETURN NEW;
            END
            $$;
        CREATE TRIGGER tasks_link_guard BEFORE UPDATE ON tasks FOR EACH ROW
            EXECUTE FUNCTION app.link_guard_columns('done_at', 'done_by', 'updated_at', 'version');
        CREATE TRIGGER list_items_link_guard BEFORE UPDATE ON list_items FOR EACH ROW
            EXECUTE FUNCTION app.link_guard_columns('checked_at', 'checked_by', 'updated_at',
                                                    'version');
        CREATE TRIGGER notes_link_guard BEFORE UPDATE ON notes FOR EACH ROW
            EXECUTE FUNCTION app.link_guard_columns('content', 'text_content', 'updated_at',
                                                    'version');

        -- ---------------------------------------------------------- the link tables
        ALTER TABLE share_links ENABLE ROW LEVEL SECURITY;
        ALTER TABLE share_links FORCE ROW LEVEL SECURITY;
        CREATE POLICY share_links_select ON share_links FOR SELECT TO planhaven_app
            USING (app.is_system() OR app.can_write(project_id));
        CREATE POLICY share_links_insert ON share_links FOR INSERT TO planhaven_app
            WITH CHECK (app.can_write(project_id) AND created_by = app.current_user_id());
        CREATE POLICY share_links_update ON share_links FOR UPDATE TO planhaven_app
            USING (app.is_system() OR app.can_write(project_id))
            WITH CHECK (app.is_system() OR app.can_write(project_id));
        REVOKE ALL ON share_links FROM PUBLIC;
        GRANT SELECT, INSERT ON share_links TO planhaven_app;
        GRANT UPDATE (revoked_at, last_used_at) ON share_links TO planhaven_app;

        ALTER TABLE share_link_items ENABLE ROW LEVEL SECURITY;
        ALTER TABLE share_link_items FORCE ROW LEVEL SECURITY;
        CREATE POLICY share_link_items_select ON share_link_items FOR SELECT TO planhaven_app
            USING (app.is_system() OR EXISTS (SELECT 1 FROM share_links l
                                              WHERE l.id = link_id));
        CREATE POLICY share_link_items_insert ON share_link_items FOR INSERT TO planhaven_app
            WITH CHECK (EXISTS (SELECT 1 FROM share_links l WHERE l.id = link_id
                                AND l.created_by = app.current_user_id()
                                AND app.can_write(l.project_id)));
        REVOKE ALL ON share_link_items FROM PUBLIC;
        GRANT SELECT, INSERT ON share_link_items TO planhaven_app;

        ALTER TABLE share_sessions ENABLE ROW LEVEL SECURITY;
        ALTER TABLE share_sessions FORCE ROW LEVEL SECURITY;
        CREATE POLICY share_sessions_system ON share_sessions FOR ALL TO planhaven_app
            USING (app.is_system()) WITH CHECK (app.is_system());
        REVOKE ALL ON share_sessions FROM PUBLIC;
        GRANT SELECT, INSERT, DELETE ON share_sessions TO planhaven_app;

        ALTER TABLE share_link_events ENABLE ROW LEVEL SECURITY;
        ALTER TABLE share_link_events FORCE ROW LEVEL SECURITY;
        CREATE POLICY share_link_events_select ON share_link_events FOR SELECT TO planhaven_app
            USING (app.is_system() OR EXISTS (SELECT 1 FROM share_links l
                                              WHERE l.id = link_id));
        CREATE POLICY share_link_events_insert ON share_link_events FOR INSERT TO planhaven_app
            WITH CHECK (app.is_system() OR link_id = app.current_share_link());
        REVOKE ALL ON share_link_events FROM PUBLIC;
        GRANT SELECT, INSERT ON share_link_events TO planhaven_app;
    """)


def downgrade() -> None:
    raise NotImplementedError("Downgrades are not supported; restore from backup.")
