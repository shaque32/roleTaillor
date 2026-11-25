-- One-time bootstrap for a managed PostgreSQL cluster (e.g. Fly Managed Postgres).
-- Run as the cluster admin user, connected to the target (empty) application database,
-- from the repo root:
--
--   psql "postgresql://<admin-user>@localhost:<port>/<db>" -f db/bootstrap/managed_roles.sql
--
-- Connect through "fly mpg proxy" with no password in the URL; keep the admin password in
-- ~/.pgpass (mode 600). A direct connection to a remote host must add sslmode=verify-full.
--
-- The script creates the roles first, then asks for each role's password with psql's
-- \password, which does not echo what you type and sends the server only a hashed password.
-- The plaintext never appears on screen, on a command line, in shell history, in the
-- process list or in the server log. Paste each password from your password manager.
--
-- It prompts only for roles it creates, so re-running re-applies grants and leaves existing
-- passwords alone. Add -v set_passwords=1 to be asked for both passwords again. To rotate one
-- password later, connect the same way and run: \password rt_app
-- An empty answer at a prompt clears that role's password; run \password <role> again to fix it.
--
-- Creates rt_owner (runs migrations; RT_MIGRATION_DATABASE_URL, direct connection) and
-- rt_app (runtime app/worker; RT_DATABASE_URL, pooled), and installs pgvector.
--
-- If the provider's admin user lacks CREATEROLE, create users named rt_owner and rt_app through
-- the provider's user management instead, then run only the extension/grant statements below.
-- On that path this script does not set the passwords: build the database URLs from the passwords
-- the provider holds for those users. If CREATE EXTENSION is refused, enable "vector" through the
-- provider first.
-- rt_app must NOT be a superuser, a database/schema owner, or have BYPASSRLS, otherwise
-- row-level security does not apply to it.

\set ON_ERROR_STOP on

-- Role creation and password prompts commit together. If a prompt fails or psql is stopped
-- before COMMIT, newly created roles roll back and the next run prompts again.
BEGIN;

SELECT NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rt_owner') AS create_owner \gset
\if :create_owner
  CREATE ROLE rt_owner LOGIN;
\endif
SELECT NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rt_app') AS create_app \gset
\if :create_app
  CREATE ROLE rt_app LOGIN NOBYPASSRLS;
\endif

ALTER ROLE rt_owner LOGIN;
ALTER ROLE rt_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;

-- Hidden password prompts, only for a role created just now unless set_passwords is given.
\if :{?set_passwords}
  \set create_owner true
  \set create_app true
\endif
\if :create_owner
  \set need_prompt true
\elif :create_app
  \set need_prompt true
\else
  \set need_prompt false
\endif

\if :need_prompt
  -- \password reads from the controlling terminal. Without one it reads stdin, where end of
  -- input is an empty answer that clears the password. Stop first, so nothing is changed.
  \set has_tty `(: </dev/tty) 2>/dev/null && echo true || echo false`
  \if :has_tty
  \else
    \echo 'No terminal: run this script from an interactive shell to set passwords.'
    \echo 'Nothing was changed. Without -v set_passwords=1, a re-run on existing roles needs no terminal.'
    DO $$ BEGIN RAISE EXCEPTION 'managed_roles.sql needs a terminal for the password prompts'; END $$;
  \endif
\endif

\if :create_owner
  \echo 'Set the rt_owner password (input is hidden; paste it from your password manager):'
  \password rt_owner
\else
  \echo 'rt_owner already existed: kept its current password (use -v set_passwords=1 to set it)'
\endif
\if :create_app
  \echo 'Set the rt_app password (input is hidden; paste it from your password manager):'
  \password rt_app
\else
  \echo 'rt_app already existed: kept its current password (use -v set_passwords=1 to set it)'
\endif

COMMIT;

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
