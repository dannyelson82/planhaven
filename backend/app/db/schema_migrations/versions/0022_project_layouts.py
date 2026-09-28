"""Each person's arrangement of a project page as tiles (owner request, 2026-09-28).

The page is a grid of tiles: the groups (tasks, lists, notes, files, quotes and costs) and
single notes, lists or files pulled out into their own tile, each narrow, wide or full width.
`tiles` is the ordered list, checked by the API (kinds, sizes, ids) before it's stored.

A person who hasn't arranged a project's page follows the project owner's arrangement (the
person who shared it); once they arrange it, they keep their own. Members can read the
layouts of projects they're in (tile kinds, sizes and ids of things they can already see);
each person writes only their own.

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-28
"""

from app.db.schema_migrations.sqlscript import execute_script

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    execute_script("""
        CREATE TABLE project_layouts (
            project_id uuid NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
            user_id    uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
            tiles      jsonb NOT NULL
                       CHECK (jsonb_typeof(tiles) = 'array' AND jsonb_array_length(tiles) <= 100
                              AND octet_length(tiles::text) <= 20000),
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (project_id, user_id)
        );
        CREATE INDEX project_layouts_user_idx ON project_layouts (user_id);

        ALTER TABLE project_layouts ENABLE ROW LEVEL SECURITY;
        ALTER TABLE project_layouts FORCE ROW LEVEL SECURITY;
        CREATE POLICY project_layouts_select ON project_layouts FOR SELECT TO planhaven_app
            USING (app.is_system() OR app.can_read(project_id));
        CREATE POLICY project_layouts_insert ON project_layouts FOR INSERT TO planhaven_app
            WITH CHECK (user_id = app.current_user_id() AND app.can_read(project_id));
        CREATE POLICY project_layouts_update ON project_layouts FOR UPDATE TO planhaven_app
            USING (user_id = app.current_user_id() AND app.can_read(project_id))
            WITH CHECK (user_id = app.current_user_id() AND app.can_read(project_id));
        CREATE POLICY project_layouts_delete ON project_layouts FOR DELETE TO planhaven_app
            USING (user_id = app.current_user_id());
        REVOKE ALL ON project_layouts FROM PUBLIC;
        GRANT SELECT, INSERT, DELETE ON project_layouts TO planhaven_app;
        GRANT UPDATE (tiles, updated_at) ON project_layouts TO planhaven_app;
    """)


def downgrade() -> None:
    raise NotImplementedError("Downgrades are not supported; restore from backup.")
