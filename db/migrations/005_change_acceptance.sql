-- Edit acceptance analytics, and the summary stage in the ops views.
-- Run as the schema owner (rt_owner). Same security model as 004: the roletailor_ops
-- views aggregate across tenants, expose ids but never resume text, and only the
-- read-only role rt_metrics may read them.
BEGIN;

-- What kind of block a proposed change edits, and which stage wrote it. Null on rows
-- written before this migration. Together with decision and decided_at (set by the
-- review screen) this is what acceptance is analysed by.
ALTER TABLE roletailor.resume_changes
    ADD COLUMN scope text CHECK (scope IN ('summary', 'bullet', 'skills')),
    ADD COLUMN source_stage text CHECK (source_stage IN ('summary', 'rewrite'));

CREATE INDEX IF NOT EXISTS resume_changes_generated_idx
    ON roletailor.resume_changes (organization_id, generated_resume_id);

-- One row per proposed change, without its text. `outcome` is what the candidate ended
-- up with: an explicit accept or reject, `kept_by_default` when the change was left
-- pending on a resume the candidate approved or exported (exports apply every change
-- that was not rejected), and `unreviewed` otherwise. The prompt version and model are
-- those of the last successful call of the stage that wrote the change.
CREATE VIEW roletailor_ops.change_decisions AS
SELECT c.organization_id,
       g.workflow_id,
       c.generated_resume_id,
       g.iteration,
       c.id AS change_id,
       g.created_at AS proposed_at,
       c.scope,
       c.source_stage,
       c.decision,
       c.decided_at,
       CASE WHEN c.decision <> 'pending' THEN c.decision
            WHEN g.approved_at IS NOT NULL OR x.exported THEN 'kept_by_default'
            ELSE 'unreviewed' END AS outcome,
       cardinality(c.prioritized_keywords) AS keywords,
       char_length(coalesce(c.proposed_text, '')) - char_length(coalesce(c.prior_text, '')) AS length_delta,
       w.prompt_key,
       w.prompt_version,
       w.model
FROM roletailor.resume_changes c
JOIN roletailor.generated_resumes g
  ON g.organization_id = c.organization_id AND g.id = c.generated_resume_id
CROSS JOIN LATERAL (
    SELECT EXISTS (SELECT 1 FROM roletailor.resume_exports e
                   WHERE e.organization_id = g.organization_id
                     AND e.resume_version_id = g.resume_version_id) AS exported
) x
LEFT JOIN LATERAL (
    SELECT p.prompt_key, p.version_number AS prompt_version, v.model_name AS model
    FROM roletailor.ai_metrics m
    JOIN roletailor.ai_model_versions v ON v.id = m.model_version_id
    LEFT JOIN roletailor.prompt_versions p ON p.id = m.prompt_version_id
    WHERE m.organization_id = g.organization_id AND m.workflow_id = g.workflow_id
      AND m.status IN ('succeeded', 'cached')
      AND m.stage LIKE 'it' || g.iteration || ':' || c.source_stage || ':%'
    ORDER BY m.created_at DESC
    LIMIT 1
) w ON true;

-- Acceptance by day, block kind, writing stage, prompt version and model.
-- acceptance_rate is over explicit decisions only; kept_rate also counts changes the
-- candidate let stand on a resume they approved or exported.
CREATE VIEW roletailor_ops.change_acceptance_daily AS
SELECT (proposed_at AT TIME ZONE 'UTC')::date AS day,
       scope, source_stage, prompt_key, prompt_version, model,
       count(*)::bigint AS proposed,
       (count(*) FILTER (WHERE outcome = 'accepted'))::bigint AS accepted,
       (count(*) FILTER (WHERE outcome = 'rejected'))::bigint AS rejected,
       (count(*) FILTER (WHERE outcome = 'kept_by_default'))::bigint AS kept_by_default,
       (count(*) FILTER (WHERE outcome = 'unreviewed'))::bigint AS unreviewed,
       (count(*) FILTER (WHERE outcome = 'accepted'))::double precision
           / NULLIF(count(*) FILTER (WHERE outcome IN ('accepted', 'rejected')), 0) AS acceptance_rate,
       (count(*) FILTER (WHERE outcome IN ('accepted', 'kept_by_default')))::double precision
           / NULLIF(count(*) FILTER (WHERE outcome <> 'unreviewed'), 0) AS kept_rate
FROM roletailor_ops.change_decisions
GROUP BY 1, 2, 3, 4, 5, 6;

-- The summary stage gets its own row in the per-stage views (it was folded into 'other').
CREATE OR REPLACE VIEW roletailor_ops.ai_calls_hourly AS
WITH calls AS (
    SELECT
        date_trunc('hour', m.created_at) AS bucket,
        CASE b.base WHEN 'structure_resume' THEN b.base WHEN 'analyze_job' THEN b.base
                    WHEN 'plan' THEN b.base WHEN 'summary' THEN b.base
                    WHEN 'rewrite' THEN b.base
                    WHEN 'verify_claims' THEN b.base WHEN 'feedback' THEN b.base
                    ELSE 'other' END AS stage,
        v.provider,
        v.model_name AS model,
        v.capability_tier AS tier,
        m.status,
        CASE WHEN m.routing_reason LIKE '%escalated+%' THEN 'escalated'
             WHEN m.routing_reason LIKE '%failover#%' THEN 'failover'
             WHEN m.routing_reason = 'cache_hit' THEN 'cache'
             ELSE 'primary' END AS route,
        m.estimated_cost_usd, m.input_tokens, m.output_tokens, m.latency_ms
    FROM roletailor.ai_metrics m
    JOIN roletailor.ai_model_versions v ON v.id = m.model_version_id
    CROSS JOIN LATERAL (
        SELECT CASE WHEN m.stage ~ '^it[0-9]+:' THEN split_part(m.stage, ':', 2)
                    ELSE split_part(m.stage, ':', 1) END AS base
    ) b
)
SELECT
    bucket, stage, provider, model, tier, status, route,
    count(*)::bigint AS calls,
    COALESCE(sum(estimated_cost_usd), 0)::numeric AS cost_usd,
    COALESCE(sum(input_tokens), 0)::bigint AS input_tokens,
    COALESCE(sum(output_tokens), 0)::bigint AS output_tokens,
    (percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms)
        FILTER (WHERE status <> 'cached'))::double precision AS p50_latency_ms,
    (percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms)
        FILTER (WHERE status <> 'cached'))::double precision AS p95_latency_ms
FROM calls
GROUP BY bucket, stage, provider, model, tier, status, route;

CREATE OR REPLACE VIEW roletailor_ops.release_quality_daily AS
WITH calls AS (
    SELECT
        (m.created_at AT TIME ZONE 'UTC')::date AS day,
        CASE b.base WHEN 'structure_resume' THEN b.base WHEN 'analyze_job' THEN b.base
                    WHEN 'plan' THEN b.base WHEN 'summary' THEN b.base
                    WHEN 'rewrite' THEN b.base
                    WHEN 'verify_claims' THEN b.base WHEN 'feedback' THEN b.base
                    ELSE 'other' END AS stage,
        p.prompt_key,
        p.version_number AS prompt_version,
        v.provider,
        v.model_name AS model,
        m.status,
        (m.routing_reason LIKE '%escalated+%' OR m.routing_reason LIKE '%failover#%') AS is_fallback,
        m.estimated_cost_usd, m.latency_ms
    FROM roletailor.ai_metrics m
    JOIN roletailor.ai_model_versions v ON v.id = m.model_version_id
    LEFT JOIN roletailor.prompt_versions p ON p.id = m.prompt_version_id
    CROSS JOIN LATERAL (
        SELECT CASE WHEN m.stage ~ '^it[0-9]+:' THEN split_part(m.stage, ':', 2)
                    ELSE split_part(m.stage, ':', 1) END AS base
    ) b
    WHERE m.status <> 'cached'
)
SELECT day, stage, prompt_key, prompt_version, provider, model,
       count(*)::bigint AS calls,
       (count(*) FILTER (WHERE status IN ('failed', 'timed_out')))::double precision
           / count(*) AS failure_rate,
       (count(*) FILTER (WHERE is_fallback))::double precision / count(*) AS fallback_rate,
       avg(estimated_cost_usd)::numeric AS avg_cost_usd,
       (percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms))::double precision AS p95_latency_ms
FROM calls
GROUP BY day, stage, prompt_key, prompt_version, provider, model;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rt_metrics') THEN
        GRANT SELECT ON ALL TABLES IN SCHEMA roletailor_ops TO rt_metrics;
    END IF;
END
$$;

COMMIT;
