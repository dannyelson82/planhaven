"""Rate limits: token buckets in PostgreSQL (SECURITY.md §7.11).

`app.rate_limit_take` refills a bucket for the elapsed time, then takes `cost` tokens if
available. It's one atomic statement, so concurrent requests can't overspend a bucket, and
buckets survive restarts. System context only.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-27
"""

from app.db.schema_migrations.sqlscript import execute_script

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    execute_script("""
        CREATE TABLE rate_limits (
            bucket_key text PRIMARY KEY CHECK (length(bucket_key) <= 200),
            tokens     double precision NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX rate_limits_updated_idx ON rate_limits (updated_at);
        ALTER TABLE rate_limits ENABLE ROW LEVEL SECURITY;
        ALTER TABLE rate_limits FORCE ROW LEVEL SECURITY;
        CREATE POLICY rate_limits_system ON rate_limits FOR ALL TO planhaven_app
            USING (app.is_system()) WITH CHECK (app.is_system());
        REVOKE ALL ON rate_limits FROM PUBLIC;
        GRANT SELECT, INSERT, UPDATE, DELETE ON rate_limits TO planhaven_app;

        -- Returns the seconds to wait: 0 means allowed (and the tokens were taken).
        CREATE FUNCTION app.rate_limit_take(
            p_key text, p_capacity double precision, p_refill_per_second double precision,
            p_cost double precision
        ) RETURNS double precision
            LANGUAGE plpgsql SET search_path = pg_catalog, public
            AS $$
            DECLARE
                available double precision;
            BEGIN
                INSERT INTO rate_limits AS r (bucket_key, tokens, updated_at)
                VALUES (p_key, p_capacity, now())
                ON CONFLICT (bucket_key) DO UPDATE
                    SET tokens = least(p_capacity, r.tokens
                                 + extract(epoch FROM now() - r.updated_at) * p_refill_per_second),
                        updated_at = now()
                RETURNING tokens INTO available;
                IF available >= p_cost THEN
                    UPDATE rate_limits SET tokens = available - p_cost WHERE bucket_key = p_key;
                    RETURN 0;
                END IF;
                RETURN ceil((p_cost - available) / p_refill_per_second);
            END
            $$;
        REVOKE ALL ON FUNCTION app.rate_limit_take(text, double precision, double precision,
                                                   double precision) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app.rate_limit_take(text, double precision, double precision,
                                                      double precision) TO planhaven_app;
    """)


def downgrade() -> None:
    raise NotImplementedError("Downgrades are not supported; restore from backup.")
