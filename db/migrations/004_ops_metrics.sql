-- Operational metrics views (cost, latency, fallback, fabrication) for Grafana.
-- Run as the schema owner (rt_owner). Definitions follow docs/monitoring-contract.md.
--
-- SECURITY NOTE: these views run with the OWNER's rights, and RLS is not forced for the
-- owner, so they aggregate across ALL tenants by design. They expose organization ids
-- but never names, emails or resume text. Only the read-only role rt_metrics may read
-- them; rt_app (the request/worker role) gets nothing in this schema. rt_metrics must
-- stay read-only: never grant it INSERT/UPDATE/DELETE or any access to roletailor.*.
BEGIN;

CREATE SCHEMA roletailor_ops;
REVOKE ALL ON SCHEMA roletailor_ops FROM PUBLIC;

-- Keep the time-window and per-workflow scans cheap.
CREATE INDEX IF NOT EXISTS ai_metrics_created_at_idx ON roletailor.ai_metrics (created_at);
CREATE INDEX IF NOT EXISTS validation_results_created_at_idx ON roletailor.validation_results (created_at);
CREATE INDEX IF NOT EXISTS validation_results_workflow_idx ON roletailor.validation_results (workflow_id);

-- Hourly AI call aggregates. Stage is normalized (contract: "Stage normalization") and
-- route classified (contract: "Route classification"). Latency percentiles ignore
-- cached calls.
CREATE VIEW roletailor_ops.ai_calls_hourly AS
WITH calls AS (
    SELECT
        date_trunc('hour', m.created_at) AS bucket,
        CASE b.base WHEN 'structure_resume' THEN b.base WHEN 'analyze_job' THEN b.base
                    WHEN 'plan' THEN b.base WHEN 'rewrite' THEN b.base
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

-- One row per workflow that made AI calls. planned_blocks sums the pipeline.coverage rows
-- (one per iteration). Fabrication counts come from the pipeline.fabrication rows only:
-- iterations recorded before that row existed have unknown fabrication counts, so they add
-- to neither fabrication_flagged_blocks nor fabrication_planned_blocks (the rate's
-- denominator). A workflow with no pipeline.fabrication row has NULL for all three
-- fabrication columns (unknown, not zero).
CREATE VIEW roletailor_ops.generations AS
WITH call_agg AS (
    SELECT
        m.workflow_id,
        min(m.organization_id::text)::uuid AS organization_id,
        -- created_at is when a call finished (captured by the Gateway before validation
        -- and sink delays), so step back by its latency for the start.
        min(m.created_at - make_interval(secs => COALESCE(m.latency_ms, 0) / 1000.0)) AS started_at,
        max(m.created_at) AS finished_at,
        count(*)::bigint AS ai_calls,
        count(*) FILTER (WHERE m.status IN ('failed', 'timed_out'))::bigint AS failed_calls,
        count(*) FILTER (WHERE m.routing_reason LIKE '%escalated+%'
                            OR m.routing_reason LIKE '%failover#%')::bigint AS fallback_calls,
        COALESCE(sum(m.estimated_cost_usd), 0)::numeric AS cost_usd
    FROM roletailor.ai_metrics m
    GROUP BY m.workflow_id
),
coverage AS (
    SELECT workflow_id, created_at,
           COALESCE(sum((details->>'planned_blocks')::int), 0) AS planned
    FROM roletailor.validation_results
    WHERE rule_key = 'pipeline.coverage'
    GROUP BY workflow_id, created_at
),
-- pipeline.fabrication holds the distinct blocks flagged by any fabrication rule;
-- summing the per-rule rows would count a block once per rule it tripped. Planned blocks
-- are those of the same iteration (same created_at), so the rate's denominator covers
-- only iterations whose fabrication count is known.
fabrication AS (
    SELECT f.workflow_id,
           sum(COALESCE((f.details->>'flagged_blocks')::int, 0))::bigint AS flagged,
           sum(COALESCE(c.planned, (f.details->>'planned_blocks')::int, 0))::bigint AS planned
    FROM roletailor.validation_results f
    LEFT JOIN coverage c ON c.workflow_id = f.workflow_id AND c.created_at = f.created_at
    WHERE f.rule_key = 'pipeline.fabrication'
    GROUP BY f.workflow_id
),
rules AS (
    SELECT r.workflow_id,
           sum(CASE WHEN r.rule_key IN ('facts.numbers', 'facts.terms', 'facts.keywords', 'facts.claims',
                                        'layout.length', 'authenticity.phrases', 'authenticity.stuffing')
                    THEN COALESCE(jsonb_array_length(
                             CASE WHEN jsonb_typeof(r.details->'reverted_to_original') = 'array'
                                  THEN r.details->'reverted_to_original' END), 0)
                    ELSE 0 END)::bigint AS reverted
    FROM roletailor.validation_results r
    GROUP BY r.workflow_id
),
planned AS (
    SELECT workflow_id, sum(planned)::bigint AS planned_blocks FROM coverage GROUP BY workflow_id
),
iters AS (
    SELECT workflow_id, count(*)::bigint AS iterations
    FROM roletailor.generated_resumes GROUP BY workflow_id
)
SELECT
    a.workflow_id,
    a.organization_id,
    w.status,
    a.started_at,
    a.finished_at,
    extract(epoch FROM (a.finished_at - a.started_at))::double precision AS wall_seconds,
    COALESCE(i.iterations, 0)::bigint AS iterations,
    a.ai_calls, a.failed_calls, a.fallback_calls, a.cost_usd,
    COALESCE(p.planned_blocks, 0)::bigint AS planned_blocks,
    fb.flagged AS fabrication_flagged_blocks,
    fb.planned AS fabrication_planned_blocks,
    (fb.flagged::double precision / NULLIF(fb.planned, 0)) AS fabrication_attempt_rate,
    COALESCE(r.reverted, 0)::bigint AS reverted_blocks
FROM call_agg a
LEFT JOIN roletailor.tailoring_workflows w
       ON w.id = a.workflow_id AND w.organization_id = a.organization_id
LEFT JOIN iters i ON i.workflow_id = a.workflow_id
LEFT JOIN planned p ON p.workflow_id = a.workflow_id
LEFT JOIN fabrication fb ON fb.workflow_id = a.workflow_id
LEFT JOIN rules r ON r.workflow_id = a.workflow_id;

CREATE VIEW roletailor_ops.generations_daily AS
SELECT
    (started_at AT TIME ZONE 'UTC')::date AS day,
    status,
    count(*)::bigint AS generations,
    sum(cost_usd)::numeric AS cost_usd,
    avg(cost_usd)::numeric AS avg_cost_usd,
    (percentile_cont(0.5) WITHIN GROUP (ORDER BY cost_usd))::numeric AS p50_cost_usd,
    (percentile_cont(0.95) WITHIN GROUP (ORDER BY cost_usd))::numeric AS p95_cost_usd,
    (percentile_cont(0.95) WITHIN GROUP (ORDER BY wall_seconds))::double precision AS p95_wall_seconds,
    -- Only workflows with known fabrication counts contribute (sum ignores NULLs); NULL
    -- when the day has none.
    (sum(fabrication_flagged_blocks)::double precision
        / NULLIF(sum(fabrication_planned_blocks), 0)) AS fabrication_attempt_rate
FROM roletailor_ops.generations
GROUP BY 1, 2;

-- Per blocking rule and day: how many planned blocks the gate flagged / reverted.
CREATE VIEW roletailor_ops.validation_daily AS
WITH coverage AS (
    SELECT workflow_id, created_at, sum((details->>'planned_blocks')::int) AS planned
    FROM roletailor.validation_results
    WHERE rule_key = 'pipeline.coverage'
    GROUP BY workflow_id, created_at
),
rows_ AS (
    SELECT (r.created_at AT TIME ZONE 'UTC')::date AS day,
           r.rule_key, r.rule_version, r.workflow_id,
           COALESCE(c.planned, 0) AS planned,
           CASE WHEN r.score IS NOT NULL AND c.planned > 0
                THEN round((1 - r.score / 100) * c.planned) ELSE 0 END AS flagged,
           COALESCE(jsonb_array_length(
               CASE WHEN jsonb_typeof(r.details->'reverted_to_original') = 'array'
                    THEN r.details->'reverted_to_original' END), 0) AS reverted
    FROM roletailor.validation_results r
    LEFT JOIN coverage c ON c.workflow_id = r.workflow_id AND c.created_at = r.created_at
    WHERE r.rule_key IN ('facts.numbers', 'facts.terms', 'facts.keywords', 'facts.claims',
                         'layout.length', 'authenticity.phrases', 'authenticity.stuffing')
)
SELECT day, rule_key, rule_version,
       count(DISTINCT workflow_id)::bigint AS generations,
       sum(planned)::bigint AS planned_blocks,
       sum(flagged)::bigint AS flagged_blocks,
       sum(reverted)::bigint AS reverted_blocks,
       (sum(flagged)::double precision / NULLIF(sum(planned), 0)) AS flagged_rate
FROM rows_
GROUP BY day, rule_key, rule_version;

CREATE VIEW roletailor_ops.cost_by_org_daily AS
SELECT (started_at AT TIME ZONE 'UTC')::date AS day,
       organization_id,
       count(*)::bigint AS generations,
       sum(cost_usd)::numeric AS cost_usd
FROM roletailor_ops.generations
GROUP BY 1, 2;

-- Compare prompt/model releases: failure and fallback rates over non-cached calls.
CREATE VIEW roletailor_ops.release_quality_daily AS
WITH calls AS (
    SELECT
        (m.created_at AT TIME ZONE 'UTC')::date AS day,
        CASE b.base WHEN 'structure_resume' THEN b.base WHEN 'analyze_job' THEN b.base
                    WHEN 'plan' THEN b.base WHEN 'rewrite' THEN b.base
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

-- rt_metrics may be created outside this migration (managed role); grant only if present.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rt_metrics') THEN
        GRANT USAGE ON SCHEMA roletailor_ops TO rt_metrics;
        GRANT SELECT ON ALL TABLES IN SCHEMA roletailor_ops TO rt_metrics;
    END IF;
END
$$;

COMMIT;
