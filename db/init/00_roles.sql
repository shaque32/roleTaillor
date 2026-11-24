-- Bootstrap for a fresh PostgreSQL cluster (docker-compose runs this once as the
-- superuser). Creates the schema owner, the RLS-bound app role and the database.
-- Replace the passwords outside local development.
CREATE ROLE rt_owner LOGIN PASSWORD 'rt_owner';
CREATE ROLE rt_app LOGIN PASSWORD 'rt_app' NOBYPASSRLS;
CREATE DATABASE roletailor OWNER rt_owner;
\connect roletailor
-- pgvector is not a trusted extension, so the superuser installs it up front.
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;
