"""The welcome tour and "What's new" (maintainer request, 2026-10-02): per person, whether the
welcome tour was finished or skipped, and the latest "What's new" they've seen. Own row only.

Revision ID: 0031
Revises: 0030
Create Date: 2026-10-02
"""

from app.db.schema_migrations.sqlscript import execute_script

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    execute_script("""
        CREATE TABLE onboarding (
            user_id          uuid PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
            welcome_done_at  timestamptz,
            whats_new_seen   text CHECK (whats_new_seen ~ '^[0-9]{1,4}\\.[0-9]{1,4}\\.[0-9]{1,4}$'),
            updated_at       timestamptz NOT NULL DEFAULT now()
        );
        ALTER TABLE onboarding ENABLE ROW LEVEL SECURITY;
        ALTER TABLE onboarding FORCE ROW LEVEL SECURITY;
        CREATE POLICY onboarding_own ON onboarding FOR ALL TO planhaven_app
            USING (user_id = app.current_user_id())
            WITH CHECK (user_id = app.current_user_id());
        REVOKE ALL ON onboarding FROM PUBLIC;
        GRANT SELECT, INSERT ON onboarding TO planhaven_app;
        GRANT UPDATE (welcome_done_at, whats_new_seen, updated_at) ON onboarding TO planhaven_app;
    """)


def downgrade() -> None:
    raise NotImplementedError("Downgrades are not supported; restore from backup.")
