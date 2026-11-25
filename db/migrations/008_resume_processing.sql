-- Asynchronous processing of uploads that need OCR (scanned PDFs).
-- Run as the schema owner (rt_owner). A resume is "ready" when processing_status is NULL.
-- While OCR runs, the resume has no version yet; processing_file_id points at the stored
-- upload so the worker can read it and a failed read can be retried. It is cleared once
-- the first version exists (that version carries the file as source_file_id).
-- rt_app already has table-level SELECT/INSERT/UPDATE/DELETE on roletailor.* (002 plus
-- default privileges), so the new columns need no extra grant.
BEGIN;

ALTER TABLE roletailor.resumes
    ADD COLUMN processing_status text CHECK (processing_status IN ('processing', 'failed')),
    ADD COLUMN processing_error text,
    ADD COLUMN processing_started_at timestamptz,
    ADD COLUMN processing_file_id uuid,
    ADD CONSTRAINT resumes_processing_file_fkey
        FOREIGN KEY (organization_id, processing_file_id)
        REFERENCES roletailor.stored_files (organization_id, id);

COMMIT;
