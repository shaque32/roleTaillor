# Monitoring contract (cost, latency, errors, fabrication)

This file fixes the names that the code, the SQL views, the alert rules and the
dashboards share. Change a name here first, then everywhere it is used.

## Principles

- Two signal paths. Prometheus metrics from the worker drive real-time alerts.
  SQL views over `ai_metrics` and `validation_results` drive drill-down, finance
  and release comparison in Grafana (Postgres datasource). Both are host-agnostic.
- No tenant or user identifiers as Prometheus labels (cardinality and privacy).
  Organization ids appear only in the SQL ops views, never names, emails or text.
- Labels hold bounded values only.

## Stage normalization

`ai_metrics.stage` / `CallRecord.stage` is a per-call label such as
`it1:rewrite:r0b2`, `it1:plan`, `it2:verify_claims:r1`. The metric `stage` label is
the base stage: the second `:`-separated segment when the first looks like `it<N>`,
else the first segment. Allowed values: `structure_resume`, `analyze_job`, `plan`,
`rewrite`, `verify_claims`, `feedback`; anything else becomes `other`.
The same rule in SQL: `split_part(stage, ':', 2)` when `stage ~ '^it[0-9]+:'`, else
`split_part(stage, ':', 1)`.

## Route classification (fallback)

From `routing_reason`: `escalated` if it contains `escalated+`; else `failover` if it
contains `failover#`; else `cache` if it equals `cache_hit`; else `primary`.
A "fallback" is route `failover` or `escalated`.

## Fabrication rules

`FABRICATION_RULES = ("facts.numbers", "facts.terms", "facts.keywords", "facts.claims")`.
These gates catch content the model invented (new numbers, new names/technologies,
unsupported job keywords, claims the verifier could not support). Caught content is
retried and, if still failing, reverted to the original text, so a flag is an
attempted fabrication that the gates stopped. The other blocking rules
(`layout.length`, `authenticity.phrases`, `authenticity.stuffing`) are quality gates.

Fabrication attempt rate = distinct blocks flagged by any fabrication rule / planned blocks.
A block that trips several fabrication rules counts once. The pipeline writes that distinct
count per iteration as a `pipeline.fabrication` validation row (`details.flagged_blocks`,
`details.reverted_blocks`); per-rule counts overlap and are for breakdown only, never summed
into the rate.

Per generation, from `TailoringResult.validations`:
- planned blocks: `details.planned_blocks` of the `pipeline.coverage` outcome.
- flagged blocks for a blocking rule: `round((1 - score / 100) * planned)` (the score is
  `100 * (1 - distinct_flagged_blocks / planned)`); 0 when planned is 0 or score is None.
- reverted blocks for a rule: `len(details.reverted_to_original)`.

## Prometheus metrics (worker process registry; multiprocess-safe, no gauges)

AI calls, emitted once per `CallRecord` by `PrometheusSink` (in `roletailor/ai/telemetry.py`
or a sibling module), wrapped together with the DB sink by `TeeSink`:

| metric | type | labels |
|---|---|---|
| `roletailor_ai_calls_total` | counter | stage, provider, model, tier, status, route |
| `roletailor_ai_call_seconds` | histogram, buckets 0.5,1,2,5,10,20,30,45,60,90 | stage, provider, model |
| `roletailor_ai_cost_usd_total` | counter | stage, provider, model |
| `roletailor_ai_tokens_total` | counter | stage, provider, kind (input, output, cache_read) |
| `roletailor_ai_errors_total` | counter | stage, provider, error_code |

`status` is the CallRecord status (succeeded, failed, timed_out, cached). Latency is
observed only for non-cached calls. `error_code` is lower-cased, characters outside
`[a-z0-9_]` replaced by `_`, cut to 32 chars; missing becomes `unknown`.

Generations, emitted in the worker after a run:

| metric | type | labels | when |
|---|---|---|---|
| `roletailor_workflow_runs_total` | counter (exists) | outcome | every run |
| `roletailor_workflow_run_seconds` | histogram (exists) | none | every run |
| `roletailor_generation_cost_usd` | histogram, buckets 0.005,0.01,0.02,0.03,0.04,0.05,0.06,0.08,0.10,0.15,0.25,0.5,1 | none | completed runs, value `result.total_cost_usd` |
| `roletailor_generation_failed_cost_usd_total` | counter | none | AI spend of runs that failed or were discarded (from the sink's running total) |
| `roletailor_validation_planned_blocks_total` | counter | none | completed runs |
| `roletailor_validation_flagged_blocks_total` | counter | rule (the 7 blocking rules) | completed runs |
| `roletailor_validation_reverted_blocks_total` | counter | rule | completed runs |
| `roletailor_validation_fabrication_blocks_total` | counter | none | completed runs, distinct blocks flagged by any fabrication rule |
| `roletailor_generation_checks_total` | counter | check, result | completed runs |

`roletailor_generation_checks_total` values: check `page_limit` (result pass, fail,
skipped when details has `skipped`), `degraded_structure` and `degraded_job` (result
fail when the `pipeline.degraded` outcome flags it, else pass), `degraded_any` (fail when
either is flagged, so a generation counts once), `document_authenticity`
(result fail when the `authenticity.document` score is below its threshold, else pass).

## Recording rules (Prometheus)

- `roletailor:generation_cost_usd:mean_30m` = sum(rate(_sum[30m])) / sum(rate(_count[30m]))
- `roletailor:generation_cost_usd:p95_1h`
- `roletailor:ai_spend_usd:increase_1h`, `roletailor:ai_spend_usd:increase_24h`
- `roletailor:workflow_run_seconds:p95_15m`
- `roletailor:ai_call_seconds:p95_15m` by (stage, provider)
- `roletailor:workflow_failure_ratio:15m` = failed / (completed + failed)
- `roletailor:ai_call_failure_ratio:10m` by (provider) = failed+timed_out / non-cached
- `roletailor:ai_fallback_ratio:15m` = route in (failover, escalated) / non-cached
- `roletailor:fabrication_attempt_ratio:1h` and `:6h` and `:7d`
- `roletailor:validation_reverted_ratio:1h` by (rule)

## SQL ops views (migration 004, schema `roletailor_ops`, owned by the schema owner)

Views run with the owner's rights, so they aggregate across tenants (RLS is not
forced for the owner). Only role `rt_metrics` (read-only, for Grafana) gets
SELECT. `rt_app` gets nothing on `roletailor_ops`.

- `roletailor_ops.ai_calls_hourly(bucket, stage, provider, model, tier, status, route, calls, cost_usd, input_tokens, output_tokens, p50_latency_ms, p95_latency_ms)`
- `roletailor_ops.generations(workflow_id, organization_id, status, started_at, finished_at, wall_seconds, iterations, ai_calls, failed_calls, fallback_calls, cost_usd, planned_blocks, fabrication_flagged_blocks, reverted_blocks)`
- `roletailor_ops.generations_daily(day, status, generations, cost_usd, avg_cost_usd, p50_cost_usd, p95_cost_usd, p95_wall_seconds, fabrication_attempt_rate)`
- `roletailor_ops.validation_daily(day, rule_key, rule_version, generations, planned_blocks, flagged_blocks, reverted_blocks, flagged_rate)`
- `roletailor_ops.cost_by_org_daily(day, organization_id, generations, cost_usd)`
- `roletailor_ops.release_quality_daily(day, stage, prompt_key, prompt_version, provider, model, calls, failure_rate, fallback_rate, avg_cost_usd, p95_latency_ms)`

Grafana datasource uids: `prometheus` and `roletailor-pg`.
