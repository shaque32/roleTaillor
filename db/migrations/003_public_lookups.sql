-- Narrow owner-privileged lookups for requests that arrive without tenant context:
-- Stripe webhooks (identified by customer id) and public share links (by token hash).
-- Each returns only an organization id (plus the export id for share links), never rows.
BEGIN;

CREATE FUNCTION roletailor.organization_for_stripe_customer(p_customer_id text)
RETURNS uuid
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
    SELECT o.id FROM roletailor.organizations o WHERE o.stripe_customer_id = p_customer_id
$$;
REVOKE ALL ON FUNCTION roletailor.organization_for_stripe_customer(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION roletailor.organization_for_stripe_customer(text) TO rt_app;

-- Resolves an active (not revoked, not expired) share link.
CREATE FUNCTION roletailor.resolve_share_link(p_token_hash text)
RETURNS TABLE (organization_id uuid, export_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
    SELECT l.organization_id, l.export_id
    FROM roletailor.resume_share_links l
    WHERE l.token_hash = p_token_hash
      AND l.revoked_at IS NULL
      AND l.expires_at > now()
$$;
REVOKE ALL ON FUNCTION roletailor.resolve_share_link(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION roletailor.resolve_share_link(text) TO rt_app;

COMMIT;
