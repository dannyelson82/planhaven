-- Database-level setup, run as the postgres superuser against the `planhaven` database.
-- Only what needs superuser lives here; everything else is an Alembic migration.
CREATE EXTENSION IF NOT EXISTS vector;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
ALTER SCHEMA public OWNER TO planhaven_owner;
GRANT USAGE ON SCHEMA public TO planhaven_app;
