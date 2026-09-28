"""A photo for each asset, shown on its card (owner request, 2026-09-28).

The photo and its thumbnail are blobs in the content-addressed store, cleaned like any
uploaded photo. The blob purge keeps them while an asset refers to them.

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-28
"""

from app.db.schema_migrations.sqlscript import execute_script

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    execute_script("""
        ALTER TABLE assets
            ADD COLUMN photo_sha256 text CHECK (photo_sha256 ~ '^[0-9a-f]{64}$'),
            ADD COLUMN photo_thumb_sha256 text CHECK (photo_thumb_sha256 ~ '^[0-9a-f]{64}$'),
            ADD COLUMN photo_type text CHECK (length(photo_type) <= 60);
        GRANT UPDATE (photo_sha256, photo_thumb_sha256, photo_type) ON assets TO planhaven_app;
    """)


def downgrade() -> None:
    raise NotImplementedError("Downgrades are not supported; restore from backup.")
