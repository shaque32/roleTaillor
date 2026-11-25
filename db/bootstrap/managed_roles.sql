-- One-time bootstrap for a managed PostgreSQL cluster (e.g. Fly Managed Postgres).
-- Run as the cluster admin user, connected to the target (empty) application database:
--
--   psql "postgresql://<admin-user>@<host>:<port>/<db>"   (no password in the URL; keep it in ~/.pgpass)
--     \prompt 'rt_owner password: ' owner_password
--     \prompt 'rt_app password: ' app_password
--     \i db/bootstrap/managed_roles.sql
--
-- Set the passwords at psql's prompts, not with -v on the command line, where they would
-- land in shell history and the process list. Do not pass psql a URL that holds the admin
-- password either.
--
-- Creates rt_owner (runs migrations; RT_MIGRATION_DATABASE_URL, direct connection) and
-- rt_app (runtime app/worker; RT_DATABASE_URL, pooled), and installs pgvector.
-- Idempotent: re-running updates passwords and re-applies grants.
--
-- If the provider's admin user lacks CREATEROLE, create users named rt_owner and rt_app through
-- the provider's user management instead, then run only the extension/grant statements below.
-- rt_app must NOT be a superuser, a database/schema owner, or have BYPASSRLS, otherwise
-- row-level security does not apply to it.

\set ON_ERROR_STOP on

SELECT NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rt_owner') AS create_owner \gset
\if :create_owner
  CREATE ROLE rt_owner LOGIN;
\endif
SELECT NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rt_app') AS create_app \gset
\if :create_app
  CREATE ROLE rt_app LOGIN NOBYPASSRLS;
\endif

ALTER ROLE rt_owner LOGIN PASSWORD :'owner_password';
ALTER ROLE rt_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD :'app_password';

-- pgvector is not a trusted extension, so the admin installs it up front.
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;

-- Let rt_owner create schema objects. Prefer making it the database owner (matches local
-- docker-compose); fall back to CREATE grants if the admin may not reassign ownership.
SELECT format($f$
DO $do$ BEGIN
  ALTER DATABASE %1$I OWNER TO rt_owner;
EXCEPTION WHEN insufficient_privilege THEN
  RAISE NOTICE 'cannot change database owner; granting CREATE instead';
  GRANT ALL ON DATABASE %1$I TO rt_owner;
END $do$;
$f$, current_database()) \gexec
SELECT format('GRANT CONNECT ON DATABASE %I TO rt_app', current_database()) \gexec
-- Cover databases created before the owner change, and PG15+ where public no longer grants CREATE.
DO $do$ BEGIN
  ALTER SCHEMA public OWNER TO rt_owner;
EXCEPTION WHEN insufficient_privilege THEN
  RAISE NOTICE 'cannot change public schema owner; granting CREATE instead';
  GRANT USAGE, CREATE ON SCHEMA public TO rt_owner;
END $do$;
GRANT USAGE ON SCHEMA public TO rt_app;
