"""Notes are saved as a whole document when the person taps Done (owner decision
2026-09-28, docs/adr/0016-notes-save-on-done.md): no live co-editing, no automatic saving.

`content` holds the editor's JSON document, checked and cleaned by the server before it's
stored (app/services/note_content.py). Notes saved by the earlier live editor are converted
the first time they're opened; their old CRDT tables are kept, read-only, until every note has
been converted.

Revision ID: 0020
Revises: 0019
Create Date: 2026-09-28
"""

from app.db.schema_migrations.sqlscript import execute_script

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    execute_script("""
        ALTER TABLE notes ADD COLUMN content jsonb
            CHECK (content IS NULL OR (jsonb_typeof(content) = 'object'
                                       AND octet_length(content::text) <= 4194304));
        GRANT UPDATE (content) ON notes TO planhaven_app;
    """)


def downgrade() -> None:
    raise NotImplementedError("Downgrades are not supported; restore from backup.")
