-- Cluster-level setup, run as the postgres superuser against the `postgres` database.
-- Idempotent: safe on every boot. Used by the container (db-bootstrap) and by CI.
SELECT 'CREATE ROLE planhaven_owner LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS'
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'planhaven_owner') \gexec
SELECT 'CREATE ROLE planhaven_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS'
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'planhaven_app') \gexec
ALTER ROLE planhaven_owner NOSUPERUSER NOBYPASSRLS;
ALTER ROLE planhaven_app NOSUPERUSER NOBYPASSRLS;
SELECT 'CREATE DATABASE planhaven OWNER planhaven_owner ENCODING ''UTF8'' TEMPLATE template0'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'planhaven') \gexec
REVOKE ALL ON DATABASE planhaven FROM PUBLIC;
GRANT CONNECT ON DATABASE planhaven TO planhaven_owner, planhaven_app;
