"""Attachments: files and photos on a project (ARCHITECTURE.md §10, SECURITY.md §7.5).

The bytes live in the content-addressed blob store under /data; this table holds what the
file is, who added it and which blobs it uses. A blob is deleted by the purge job once no
attachment row refers to it. Members read; editors add and delete.

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-28
"""

from app.db.schema_migrations.sqlscript import execute_script

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    execute_script("""
        CREATE TABLE attachments (
            id             uuid PRIMARY KEY DEFAULT uuidv7(),
            project_id     uuid NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
            filename       text NOT NULL CHECK (length(filename) BETWEEN 1 AND 255),
            kind           text NOT NULL
                           CHECK (kind IN ('image', 'pdf', 'document', 'text', 'model', 'archive')),
            content_type   text NOT NULL CHECK (length(content_type) <= 120),
            size           bigint NOT NULL CHECK (size >= 0),
            blob_sha256    text NOT NULL CHECK (blob_sha256 ~ '^[0-9a-f]{64}$'),
            thumb_sha256   text CHECK (thumb_sha256 ~ '^[0-9a-f]{64}$'),
            metadata_kept  boolean NOT NULL DEFAULT false,
            created_by     uuid NOT NULL REFERENCES users (id),
            created_at     timestamptz NOT NULL DEFAULT now(),
            deleted_at     timestamptz
        );
        CREATE INDEX attachments_project_idx ON attachments (project_id, created_at DESC)
            WHERE deleted_at IS NULL;
        CREATE INDEX attachments_blob_idx ON attachments (blob_sha256);
        CREATE INDEX attachments_thumb_idx ON attachments (thumb_sha256);

        ALTER TABLE attachments ENABLE ROW LEVEL SECURITY;
        ALTER TABLE attachments FORCE ROW LEVEL SECURITY;
        CREATE POLICY attachments_select ON attachments FOR SELECT TO planhaven_app
            USING (app.is_system() OR app.can_read(project_id));
        CREATE POLICY attachments_insert ON attachments FOR INSERT TO planhaven_app
            WITH CHECK (app.can_write(project_id) AND created_by = app.current_user_id());
        CREATE POLICY attachments_update ON attachments FOR UPDATE TO planhaven_app
            USING (app.can_write(project_id)) WITH CHECK (app.can_write(project_id));
        REVOKE ALL ON attachments FROM PUBLIC;
        GRANT SELECT, INSERT ON attachments TO planhaven_app;
        GRANT UPDATE (filename, deleted_at) ON attachments TO planhaven_app;
    """)


def downgrade() -> None:
    raise NotImplementedError("Downgrades are not supported; restore from backup.")
