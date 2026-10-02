"""Notifications screen, preferences and Web Push (ADR 0018, A§13.3, A§15).

- notifications gain a dedupe key (one reminder per task per day, one "service due" per
  service and status) and a push state: new notifications start 'pending' and the worker
  sends them to the person's devices, or skips them (their settings, no devices); rows from
  before this migration are 'none' and never pushed.
- notification_settings: one row per person (per kind of notification: on the phone, in the
  app only, or off; quiet hours in their own time zone; message previews). Own row only; the
  worker reads them in system context.
- push_subscriptions: each device that turned on phone alerts (the browser's push endpoint
  and keys). Own rows only; the worker reads them and removes the ones the push service
  says are gone.

Revision ID: 0029
Revises: 0028
Create Date: 2026-10-02
"""

from app.db.schema_migrations.sqlscript import execute_script

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    execute_script("""
        ALTER TABLE notifications
            ADD COLUMN dedupe_key text CHECK (length(dedupe_key) <= 200),
            ADD COLUMN push_state text NOT NULL DEFAULT 'none'
                CHECK (push_state IN ('none', 'pending', 'sent', 'skipped', 'failed')),
            ADD COLUMN push_after timestamptz,
            ADD COLUMN push_attempts integer NOT NULL DEFAULT 0;
        ALTER TABLE notifications ALTER COLUMN push_state SET DEFAULT 'pending';
        ALTER TABLE notifications ALTER COLUMN push_after SET DEFAULT now();
        CREATE UNIQUE INDEX notifications_dedupe_idx ON notifications (user_id, dedupe_key)
            WHERE dedupe_key IS NOT NULL;
        CREATE INDEX notifications_push_idx ON notifications (push_after)
            WHERE push_state = 'pending';
        CREATE INDEX notifications_unread_idx ON notifications (user_id)
            WHERE read_at IS NULL;
        -- The worker records what it did with each notification.
        CREATE POLICY notifications_system_update ON notifications FOR UPDATE TO planhaven_app
            USING (app.is_system()) WITH CHECK (app.is_system());
        GRANT UPDATE (push_state, push_after, push_attempts) ON notifications TO planhaven_app;

        CREATE TABLE notification_settings (
            user_id     uuid PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
            prefs       jsonb NOT NULL DEFAULT '{}'::jsonb
                        CHECK (jsonb_typeof(prefs) = 'object'
                               AND octet_length(prefs::text) <= 2048),
            quiet_from  time,
            quiet_to    time,
            time_zone   text NOT NULL DEFAULT 'UTC' CHECK (length(time_zone) <= 64),
            previews    boolean NOT NULL DEFAULT true,
            updated_at  timestamptz NOT NULL DEFAULT now(),
            CHECK ((quiet_from IS NULL) = (quiet_to IS NULL))
        );
        ALTER TABLE notification_settings ENABLE ROW LEVEL SECURITY;
        ALTER TABLE notification_settings FORCE ROW LEVEL SECURITY;
        CREATE POLICY notification_settings_own ON notification_settings FOR ALL
            TO planhaven_app
            USING (app.is_system() OR user_id = app.current_user_id())
            WITH CHECK (user_id = app.current_user_id());
        REVOKE ALL ON notification_settings FROM PUBLIC;
        GRANT SELECT, INSERT ON notification_settings TO planhaven_app;
        GRANT UPDATE (prefs, quiet_from, quiet_to, time_zone, previews, updated_at)
            ON notification_settings TO planhaven_app;

        CREATE TABLE push_subscriptions (
            id               uuid PRIMARY KEY DEFAULT uuidv7(),
            user_id          uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
            endpoint         text NOT NULL UNIQUE
                             CHECK (length(endpoint) <= 1000 AND endpoint LIKE 'https://%'),
            p256dh           text NOT NULL CHECK (length(p256dh) <= 200),
            auth             text NOT NULL CHECK (length(auth) <= 100),
            label            text NOT NULL DEFAULT '' CHECK (length(label) <= 120),
            created_at       timestamptz NOT NULL DEFAULT now(),
            last_success_at  timestamptz,
            failures         integer NOT NULL DEFAULT 0
        );
        CREATE INDEX push_subscriptions_user_idx ON push_subscriptions (user_id);
        ALTER TABLE push_subscriptions ENABLE ROW LEVEL SECURITY;
        ALTER TABLE push_subscriptions FORCE ROW LEVEL SECURITY;
        CREATE POLICY push_subscriptions_select ON push_subscriptions FOR SELECT TO planhaven_app
            USING (app.is_system() OR user_id = app.current_user_id());
        CREATE POLICY push_subscriptions_insert ON push_subscriptions FOR INSERT TO planhaven_app
            WITH CHECK (user_id = app.current_user_id());
        CREATE POLICY push_subscriptions_delete ON push_subscriptions FOR DELETE TO planhaven_app
            USING (app.is_system() OR user_id = app.current_user_id());
        CREATE POLICY push_subscriptions_update ON push_subscriptions FOR UPDATE TO planhaven_app
            USING (app.is_system()) WITH CHECK (app.is_system());
        REVOKE ALL ON push_subscriptions FROM PUBLIC;
        GRANT SELECT, INSERT, DELETE ON push_subscriptions TO planhaven_app;
        GRANT UPDATE (last_success_at, failures) ON push_subscriptions TO planhaven_app;

        -- A browser has one push endpoint. When someone else signs in on the same browser and
        -- turns on phone alerts, the endpoint becomes theirs: the previous person's
        -- registration of it is removed, so their alerts don't reach the next person.
        CREATE POLICY push_subscriptions_definer_delete ON push_subscriptions FOR DELETE
            TO planhaven_owner USING (true);
        CREATE POLICY push_subscriptions_definer_read ON push_subscriptions FOR SELECT
            TO planhaven_owner USING (true);
        CREATE FUNCTION app.release_push_endpoint(p_endpoint text) RETURNS void
            LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, public
            AS $$
                DELETE FROM push_subscriptions
                WHERE endpoint = p_endpoint AND app.current_user_id() IS NOT NULL
                  AND user_id <> app.current_user_id()
            $$;
        REVOKE ALL ON FUNCTION app.release_push_endpoint(text) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app.release_push_endpoint(text) TO planhaven_app;
    """)


def downgrade() -> None:
    raise NotImplementedError("Downgrades are not supported; restore from backup.")
