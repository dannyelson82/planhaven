"""The AI connector (ADR 0007, ADR 0019, A§12): OAuth 2.1 for AI apps, and what they change.

- oauth_clients: AI apps registered by themselves (dynamic client registration). A client has
  no access to anything until a person approves it.
- oauth_requests / oauth_codes: an authorization in progress (shown on the consent screen),
  and the single-use code it ends with (hashed, PKCE challenge kept).
- oauth_grants: a person's connection to one app: read or write, and for writes "approve"
  (suggestions wait for the person) or "apply" (with undo). Own rows only.
- oauth_tokens: access (1 hour) and refresh (30 days, rotated; reuse revokes the family) tokens,
  hashed.
- ai_suggestions: changes waiting for the person's approval. ai_changes: what an AI changed
  (applied directly or approved), so it can be undone. Own rows only.

The OAuth tables are system-only: the token endpoint and /mcp have no session; they look things
up by hash and then act as the grant's person (RLS).

Revision ID: 0034
Revises: 0033
Create Date: 2026-10-04
"""

from app.db.schema_migrations.sqlscript import execute_script

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    execute_script("""
        CREATE TABLE oauth_clients (
            id             uuid PRIMARY KEY DEFAULT uuidv7(),
            client_id      text NOT NULL UNIQUE CHECK (length(client_id) BETWEEN 20 AND 80),
            client_name    text NOT NULL CHECK (length(client_name) BETWEEN 1 AND 100),
            redirect_uris  text[] NOT NULL
                           CHECK (cardinality(redirect_uris) BETWEEN 1 AND 5),
            created_at     timestamptz NOT NULL DEFAULT now(),
            last_used_at   timestamptz
        );

        CREATE TABLE oauth_requests (
            id              uuid PRIMARY KEY DEFAULT uuidv7(),
            client_id       uuid NOT NULL REFERENCES oauth_clients (id) ON DELETE CASCADE,
            redirect_uri    text NOT NULL CHECK (length(redirect_uri) <= 500),
            code_challenge  text NOT NULL CHECK (code_challenge ~ '^[A-Za-z0-9_-]{43}$'),
            scope           text NOT NULL CHECK (scope IN ('read', 'write')),
            state           text CHECK (length(state) <= 500),
            created_at      timestamptz NOT NULL DEFAULT now(),
            expires_at      timestamptz NOT NULL
        );

        CREATE TABLE oauth_grants (
            id            uuid PRIMARY KEY DEFAULT uuidv7(),
            user_id       uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
            client_id     uuid NOT NULL REFERENCES oauth_clients (id) ON DELETE CASCADE,
            scope         text NOT NULL CHECK (scope IN ('read', 'write')),
            write_mode    text NOT NULL DEFAULT 'approve'
                          CHECK (write_mode IN ('approve', 'apply')),
            created_at    timestamptz NOT NULL DEFAULT now(),
            last_used_at  timestamptz,
            revoked_at    timestamptz
        );
        CREATE INDEX oauth_grants_user_idx ON oauth_grants (user_id) WHERE revoked_at IS NULL;

        CREATE TABLE oauth_codes (
            code_hash       bytea PRIMARY KEY CHECK (length(code_hash) = 32),
            grant_id        uuid NOT NULL REFERENCES oauth_grants (id) ON DELETE CASCADE,
            redirect_uri    text NOT NULL,
            code_challenge  text NOT NULL,
            expires_at      timestamptz NOT NULL,
            used_at         timestamptz
        );

        CREATE TABLE oauth_tokens (
            id          uuid PRIMARY KEY DEFAULT uuidv7(),
            grant_id    uuid NOT NULL REFERENCES oauth_grants (id) ON DELETE CASCADE,
            family_id   uuid NOT NULL,
            kind        text NOT NULL CHECK (kind IN ('access', 'refresh')),
            token_hash  bytea NOT NULL UNIQUE CHECK (length(token_hash) = 32),
            created_at  timestamptz NOT NULL DEFAULT now(),
            expires_at  timestamptz NOT NULL,
            used_at     timestamptz,
            revoked_at  timestamptz
        );
        CREATE INDEX oauth_tokens_family_idx ON oauth_tokens (family_id);
        CREATE INDEX oauth_tokens_grant_idx ON oauth_tokens (grant_id);

        CREATE TABLE ai_suggestions (
            id           uuid PRIMARY KEY DEFAULT uuidv7(),
            user_id      uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
            grant_id     uuid NOT NULL REFERENCES oauth_grants (id) ON DELETE CASCADE,
            project_id   uuid REFERENCES projects (id) ON DELETE CASCADE,
            tool         text NOT NULL CHECK (length(tool) <= 60),
            arguments    jsonb NOT NULL CHECK (octet_length(arguments::text) <= 65536),
            summary      text NOT NULL CHECK (length(summary) <= 2000),
            status       text NOT NULL DEFAULT 'pending'
                         CHECK (status IN ('pending', 'approved', 'declined', 'failed')),
            created_at   timestamptz NOT NULL DEFAULT now(),
            decided_at   timestamptz
        );
        CREATE INDEX ai_suggestions_pending_idx ON ai_suggestions (user_id)
            WHERE status = 'pending';

        CREATE TABLE ai_changes (
            id           uuid PRIMARY KEY DEFAULT uuidv7(),
            user_id      uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
            client_name  text NOT NULL CHECK (length(client_name) <= 100),
            project_id   uuid REFERENCES projects (id) ON DELETE CASCADE,
            kind         text NOT NULL CHECK (length(kind) <= 40),
            summary      text NOT NULL CHECK (length(summary) <= 2000),
            undo         jsonb NOT NULL CHECK (octet_length(undo::text) <= 65536),
            created_at   timestamptz NOT NULL DEFAULT now(),
            undone_at    timestamptz
        );
        CREATE INDEX ai_changes_user_idx ON ai_changes (user_id, created_at DESC);

        -- System only: no session behind these requests.
        ALTER TABLE oauth_clients ENABLE ROW LEVEL SECURITY;
        ALTER TABLE oauth_clients FORCE ROW LEVEL SECURITY;
        CREATE POLICY oauth_clients_system ON oauth_clients FOR ALL TO planhaven_app
            USING (app.is_system()) WITH CHECK (app.is_system());
        ALTER TABLE oauth_requests ENABLE ROW LEVEL SECURITY;
        ALTER TABLE oauth_requests FORCE ROW LEVEL SECURITY;
        CREATE POLICY oauth_requests_system ON oauth_requests FOR ALL TO planhaven_app
            USING (app.is_system()) WITH CHECK (app.is_system());
        ALTER TABLE oauth_codes ENABLE ROW LEVEL SECURITY;
        ALTER TABLE oauth_codes FORCE ROW LEVEL SECURITY;
        CREATE POLICY oauth_codes_system ON oauth_codes FOR ALL TO planhaven_app
            USING (app.is_system()) WITH CHECK (app.is_system());
        ALTER TABLE oauth_tokens ENABLE ROW LEVEL SECURITY;
        ALTER TABLE oauth_tokens FORCE ROW LEVEL SECURITY;
        CREATE POLICY oauth_tokens_system ON oauth_tokens FOR ALL TO planhaven_app
            USING (app.is_system()) WITH CHECK (app.is_system());
        REVOKE ALL ON oauth_clients, oauth_requests, oauth_codes, oauth_tokens FROM PUBLIC;
        GRANT SELECT, INSERT, DELETE ON oauth_clients, oauth_requests, oauth_codes, oauth_tokens
            TO planhaven_app;
        GRANT UPDATE (last_used_at) ON oauth_clients TO planhaven_app;
        GRANT UPDATE (used_at) ON oauth_codes TO planhaven_app;
        GRANT UPDATE (used_at, revoked_at) ON oauth_tokens TO planhaven_app;

        -- A person's own connections, suggestions and AI changes.
        ALTER TABLE oauth_grants ENABLE ROW LEVEL SECURITY;
        ALTER TABLE oauth_grants FORCE ROW LEVEL SECURITY;
        CREATE POLICY oauth_grants_own ON oauth_grants FOR ALL TO planhaven_app
            USING (app.is_system() OR user_id = app.current_user_id())
            WITH CHECK (app.is_system() OR user_id = app.current_user_id());
        ALTER TABLE ai_suggestions ENABLE ROW LEVEL SECURITY;
        ALTER TABLE ai_suggestions FORCE ROW LEVEL SECURITY;
        CREATE POLICY ai_suggestions_own ON ai_suggestions FOR ALL TO planhaven_app
            USING (app.is_system() OR user_id = app.current_user_id())
            WITH CHECK (app.is_system() OR user_id = app.current_user_id());
        ALTER TABLE ai_changes ENABLE ROW LEVEL SECURITY;
        ALTER TABLE ai_changes FORCE ROW LEVEL SECURITY;
        CREATE POLICY ai_changes_own ON ai_changes FOR ALL TO planhaven_app
            USING (app.is_system() OR user_id = app.current_user_id())
            WITH CHECK (app.is_system() OR user_id = app.current_user_id());
        REVOKE ALL ON oauth_grants, ai_suggestions, ai_changes FROM PUBLIC;
        GRANT SELECT, INSERT ON oauth_grants, ai_suggestions, ai_changes TO planhaven_app;
        GRANT UPDATE (scope, write_mode, last_used_at, revoked_at) ON oauth_grants TO planhaven_app;
        GRANT UPDATE (status, decided_at) ON ai_suggestions TO planhaven_app;
        GRANT UPDATE (undone_at) ON ai_changes TO planhaven_app;
    """)


def downgrade() -> None:
    raise NotImplementedError("Downgrades are not supported; restore from backup.")
