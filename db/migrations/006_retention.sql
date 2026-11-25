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
      -- A resume with a run in flight is left for a later night. Leaving it out here,
      -- before the limit, keeps a backlog of busy resumes from filling every batch.
      AND NOT EXISTS (
          SELECT 1 FROM roletailor.tailoring_workflows w
          JOIN roletailor.resume_versions v
            ON v.organization_id = w.organization_id AND v.id = w.source_resume_version_id
          WHERE v.organization_id = r.organization_id AND v.resume_id = r.id
            AND w.status IN ('queued', 'running'))
    ORDER BY r.archived_at
    LIMIT GREATEST(p_limit, 0)
$$;
REVOKE ALL ON FUNCTION roletailor.resumes_due_for_purge(interval, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION roletailor.resumes_due_for_purge(interval, integer) TO rt_app;

-- Storage objects whose rows a purge has removed. The row is written in the purge's own
-- transaction and removed only once the object store confirms the delete, so a failed
-- delete or a worker crash is retried by the next run instead of leaving the file behind.
-- Holds object keys only (no tenant data), so like stripe_webhook_events it is not
-- tenant scoped.
CREATE TABLE roletailor.pending_object_deletions (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    object_key text NOT NULL,
    object_version text,
    attempts integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT, UPDATE, DELETE ON roletailor.pending_object_deletions TO rt_app;

COMMIT;
