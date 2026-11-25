-- Retention: a deleted (archived) resume is erased for good after the retention period.
-- The nightly purge job runs without tenant context, so it finds its work through a
-- narrow owner-privileged lookup that returns ids only, never resume content.
BEGIN;

ALTER TABLE roletailor.resumes ADD COLUMN purged_at timestamptz;
ALTER TABLE roletailor.resumes
    ADD CONSTRAINT resumes_purged_only_after_archive
    CHECK (purged_at IS NULL OR archived_at IS NOT NULL);

CREATE INDEX resumes_awaiting_purge ON roletailor.resumes (archived_at)
    WHERE archived_at IS NOT NULL AND purged_at IS NULL;

-- The floor of one day means a caller bug or a bad setting can never purge resumes
-- the moment they are deleted.
CREATE FUNCTION roletailor.resumes_due_for_purge(p_older_than interval, p_limit integer)
RETURNS TABLE (organization_id uuid, resume_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
    SELECT r.organization_id, r.id
    FROM roletailor.resumes r
    WHERE r.archived_at IS NOT NULL
      AND r.purged_at IS NULL
      AND r.archived_at < now() - GREATEST(p_older_than, interval '1 day')
    ORDER BY r.archived_at
    LIMIT GREATEST(p_limit, 0)
$$;
REVOKE ALL ON FUNCTION roletailor.resumes_due_for_purge(interval, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION roletailor.resumes_due_for_purge(interval, integer) TO rt_app;

COMMIT;
