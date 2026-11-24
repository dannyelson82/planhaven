"""App sign-in for the native iPhone app (ADR 0021, phase 0.5).

- oauth_clients.first_party: built-in clients, created here, never by registration. The iPhone
  app's client `phc_planhaven_ios` has a private-use redirect (RFC 8252 §7.1) that dynamic
  registration still refuses for everyone else.
- oauth_requests / oauth_grants: scope `app` (the REST API, audience /api/v1) beside `read` and
  `write` (AI apps, /mcp); the device's name; the address the app was last used from.
- live_tickets: single-use, 30-second tickets for the live-update WebSockets, so a bearer token
  never travels in a WebSocket URL. System-only, hashed.

Revision ID: 0035
Revises: 0034
Create Date: 2026-11-24
"""

from app.db.schema_migrations.sqlscript import execute_script

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    execute_script("""
        ALTER TABLE oauth_clients ADD COLUMN first_party boolean NOT NULL DEFAULT false;
        ALTER TABLE oauth_clients DROP CONSTRAINT oauth_clients_client_id_check;
        ALTER TABLE oauth_clients ADD CONSTRAINT oauth_clients_client_id_check
            CHECK (length(client_id) BETWEEN 16 AND 80);
        -- The table forces RLS even on its owner; lifted for this one row, same transaction.
        ALTER TABLE oauth_clients NO FORCE ROW LEVEL SECURITY;
        INSERT INTO oauth_clients (client_id, client_name, redirect_uris, first_party)
        VALUES ('phc_planhaven_ios', 'PlanHaven for iPhone',
                ARRAY['app.planhaven.ios:/oauth/callback'], true);
        ALTER TABLE oauth_clients FORCE ROW LEVEL SECURITY;

        ALTER TABLE oauth_requests DROP CONSTRAINT oauth_requests_scope_check;
        ALTER TABLE oauth_requests ADD CONSTRAINT oauth_requests_scope_check
            CHECK (scope IN ('read', 'write', 'app'));
        ALTER TABLE oauth_requests ADD COLUMN device_name text
            CHECK (length(device_name) BETWEEN 1 AND 100);

        ALTER TABLE oauth_grants DROP CONSTRAINT oauth_grants_scope_check;
        ALTER TABLE oauth_grants ADD CONSTRAINT oauth_grants_scope_check
            CHECK (scope IN ('read', 'write', 'app'));
        ALTER TABLE oauth_grants ADD COLUMN device_name text
            CHECK (length(device_name) BETWEEN 1 AND 100);
        ALTER TABLE oauth_grants ADD COLUMN last_ip inet;
        GRANT UPDATE (device_name, last_ip) ON oauth_grants TO planhaven_app;

        CREATE TABLE live_tickets (
            ticket_hash  bytea PRIMARY KEY CHECK (length(ticket_hash) = 32),
            user_id      uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
            grant_id     uuid NOT NULL REFERENCES oauth_grants (id) ON DELETE CASCADE,
            expires_at   timestamptz NOT NULL
        );
        ALTER TABLE live_tickets ENABLE ROW LEVEL SECURITY;
        ALTER TABLE live_tickets FORCE ROW LEVEL SECURITY;
        CREATE POLICY live_tickets_system ON live_tickets FOR ALL TO planhaven_app
            USING (app.is_system()) WITH CHECK (app.is_system());
        REVOKE ALL ON live_tickets FROM PUBLIC;
        GRANT SELECT, INSERT, DELETE ON live_tickets TO planhaven_app;
    """)


def downgrade() -> None:
    raise NotImplementedError("Downgrades are not supported; restore from backup.")
