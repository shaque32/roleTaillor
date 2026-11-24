-- Privileges for the request/worker role (rt_app, NOBYPASSRLS) and the login lookup.
-- Run as the schema owner. Tenant rows stay protected by the RLS policies from 001.
BEGIN;

GRANT USAGE ON SCHEMA roletailor TO rt_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA roletailor TO rt_app;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA roletailor TO rt_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA roletailor
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO rt_app;

-- Login must find a user's organizations before any tenant context exists. This
-- function runs as the owner (which is exempt from non-forced RLS) and exposes only
-- the membership pairs of the user id it is given.
CREATE FUNCTION roletailor.user_memberships(p_user_id uuid)
RETURNS TABLE (organization_id uuid, role text)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
    SELECT m.organization_id, m.role
    FROM roletailor.organization_members m
    WHERE m.user_id = p_user_id
    ORDER BY m.joined_at, m.organization_id
$$;
REVOKE ALL ON FUNCTION roletailor.user_memberships(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION roletailor.user_memberships(uuid) TO rt_app;

COMMIT;
