# AI alert runbook

One section per alert in `ops/monitoring/prometheus/rules/alerts.yml`. Dashboards: `RoleTailor AI overview` (Prometheus, uid `roletailor-ai-overview`) and `RoleTailor AI quality and cost (SQL)` (uid `roletailor-ai-quality`). SQL views live in schema `roletailor_ops` (see `docs/monitoring-contract.md`).

Common tools:
- Logs are JSON. Useful fields: `correlation_id`, `workflow_id`, `stage`, `provider`, `model`. Find one bad run by `workflow_id`, then follow its `correlation_id` across API and worker.
- Routing, tiers and prompt pins are in `config/models.yaml`. Edit, then redeploy (or reload) the worker.
- Slowest and most expensive runs: `SELECT * FROM roletailor_ops.generations WHERE started_at > now() - interval '1 hour' ORDER BY cost_usd DESC LIMIT 20;`

## generationcosthigh

**Means**: mean cost per completed generation over 30m is above $0.06 (target about $0.04).
**Likely causes**: a stage escalated to a higher tier too often, a prompt change that made outputs longer or caused more retries, a provider price change, or unusually long resumes.
**First checks**: overview panels "Spend per hour by stage" and "Spend per hour by model" (which stage or model grew), "Fallback ratio". SQL: `SELECT stage, model, sum(cost_usd), sum(calls) FROM roletailor_ops.ai_calls_hourly WHERE bucket > now() - interval '2 hours' GROUP BY 1,2 ORDER BY 3 DESC;` Then the most expensive runs in `roletailor_ops.generations`, and their logs by `workflow_id`.
**Mitigations**: check the prices in `config/models.yaml`; put a cheaper model first in the affected tier, or lower `max_tier` for the expensive stage; pin the previous prompt version in `prompt_pins` and redeploy; if only retries are the cause, see the validation alerts.
**Escalate** if it passes $0.10 (see generationcostcritical) or the cause is unclear after 30 minutes.

## generationcostcritical

**Means**: mean cost per generation is above $0.10 for 15m, more than twice the target.
**Likely causes**: same as generationcosthigh, but more severe: a retry loop, a wrong price entry, or all traffic on the high tier.
**First checks**: same as generationcosthigh. Also look for a single org or run: `SELECT organization_id, sum(cost_usd) FROM roletailor_ops.cost_by_org_daily WHERE day = current_date GROUP BY 1 ORDER BY 2 DESC LIMIT 5;`
**Mitigations**: roll back the last prompt or `config/models.yaml` change first. If spend is runaway and unexplained, pause new generations (stop the worker) until understood.
**Escalate** immediately to the on-call owner; this burns money.

## dailyaispendoverbudget

**Means**: AI spend over the last 24h exceeds `roletailor:ai_spend_budget_usd:daily` (edit it in `rules/recording.yml`, default $50).
**Likely causes**: real traffic growth, or a cost problem that did not trip the per-generation alerts.
**First checks**: overview "AI spend 24h vs daily budget" and "Spend per hour by model"; quality dashboard "Daily cost per generation" and "Top organizations by cost" (ids only).
**Mitigations**: if traffic is legitimate, raise the budget in `recording.yml` and reload Prometheus. Otherwise treat it as a cost incident (see generationcosthigh).
**Escalate** if the budget is exceeded by more than 50% or one organization dominates.

## aispendspike

**Means**: spend in the last hour is more than 3x the 24h hourly average and above $1.
**Likely causes**: a burst of traffic, a batch import, a retry storm after a provider incident, or a bot.
**First checks**: overview "AI call outcomes by status" and "AI errors by provider"; run count in "Generation runs by outcome". SQL: `roletailor_ops.cost_by_org_daily` for a single org.
**Mitigations**: if it is a retry storm, fix the provider problem first (see aiprovidererrorratehigh). If abuse, rate limit the org (planned in the security work).
**Escalate** if spend keeps rising for two more hours.

## failedrunspend

**Means**: runs that failed or were discarded spent more than $2 in the last hour. Money with no output.
**Likely causes**: failures late in the pipeline (verification, validation) after expensive stages ran, or timeouts after long calls.
**First checks**: "Generation runs by outcome", "AI errors by provider and error code". SQL: `SELECT workflow_id, cost_usd, failed_calls, wall_seconds FROM roletailor_ops.generations WHERE status <> 'completed' AND started_at > now() - interval '1 hour' ORDER BY cost_usd DESC;` Then the logs for those `workflow_id` values and the failing `stage`.
**Mitigations**: fix the failing stage; reduce attempts in `routing.attempts_per_model` if retries are the waste.
**Escalate** if failure rate alerts also fire.

## generationlatencyhigh

**Means**: p95 run time over 15m is above 120s for 15m.
**Likely causes**: a slow provider, fallbacks, queue backlog (not enough worker concurrency), long resumes.
**First checks**: overview "AI call latency p95 by stage", "Fallback ratio". SQL: `SELECT workflow_id, wall_seconds, iterations, fallback_calls FROM roletailor_ops.generations ORDER BY started_at DESC LIMIT 50;` High `iterations` means rewrite retries. Check the Celery queue length and worker CPU.
**Mitigations**: move the slow provider behind another in the tier order in `config/models.yaml`; raise worker `--concurrency` or add a worker.
**Escalate** if it reaches 300s (generationlatencycritical).

## generationlatencycritical

**Means**: p95 run time is above 300s for 10m. Users are likely abandoning.
**Likely causes**: provider outage, stuck workers, queue backed up.
**First checks**: same as generationlatencyhigh; also confirm the worker is up (workermetricsdown) and the queue is draining.
**Mitigations**: fail over away from the slow provider (reorder the tier in `config/models.yaml`, redeploy); restart stuck workers; scale workers.
**Escalate** immediately.

## aistagelatencyhigh

**Means**: p95 latency of AI calls for one stage and provider is above 30s for 15m. The request timeout is 45s, so timeouts are close.
**Likely causes**: provider slowness, large prompts for that stage, long outputs (high `max_tokens`).
**First checks**: overview "AI call latency p95 by stage"; "AI call outcomes by status" for `timed_out`. SQL: `SELECT model, p95_latency_ms, calls FROM roletailor_ops.ai_calls_hourly WHERE stage = '<stage>' AND bucket > now() - interval '3 hours' ORDER BY bucket DESC;`
**Mitigations**: put another provider first in that tier; reduce `max_tokens` for the stage in `config/models.yaml`.
**Escalate** if timeouts begin (aiprovidererrorratehigh fires).

## generationfailureratehigh

**Means**: more than 5% of runs failed over 15m, with at least 5 runs.
**Likely causes**: provider errors, schema-invalid model output, a bad prompt version, bad input (unreadable PDFs), a database or Redis problem.
**First checks**: "Failure rate" tile, "AI errors by provider and error code". Logs: search `workflow_id` of failed runs: `SELECT workflow_id, started_at FROM roletailor_ops.generations WHERE status = 'failed' ORDER BY started_at DESC LIMIT 20;` and read the final error and `stage`.
**Mitigations**: if one provider, reorder the tier; if after a release, pin the previous prompt version and redeploy; if input related, it may be expected.
**Escalate** if above 20% (generationfailureratecritical).

## generationfailureratecritical

**Means**: more than 20% of runs failed over 10m.
**Likely causes**: provider outage or a broken release.
**First checks**: same as generationfailureratehigh, plus recent deploys.
**Mitigations**: roll back the last release or prompt version; switch the failing provider out of the tier order.
**Escalate** immediately.

## aiprovidererrorratehigh

**Means**: more than 20% of non-cached calls to one provider failed or timed out over 10m.
**Likely causes**: provider outage or rate limiting, expired or wrong API key, network issue.
**First checks**: "AI errors by provider and error code" (the `error_code` names the cause: auth, rate limit, timeout). Provider status page. Logs filtered by `provider`.
**Mitigations**: the router already fails over inside the tier; verify "Fallback ratio" is picking it up. Fix the key (`ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY`) if auth errors. If the provider is down for long, move it to the end of the tier in `config/models.yaml`.
**Escalate** if all providers in a tier are affected.

## aifallbackratehigh

**Means**: more than 25% of AI calls needed failover or escalation to a higher tier over 15m.
**Likely causes**: primary model failing or returning schema-invalid output, or a prompt change that makes the low tier struggle. This raises cost and latency.
**First checks**: "Fallback ratio", "Spend per hour by model". SQL: `SELECT stage, model, route, sum(calls) FROM roletailor_ops.ai_calls_hourly WHERE bucket > now() - interval '3 hours' GROUP BY 1,2,3 ORDER BY 4 DESC;` and `release_quality_daily` by `prompt_version`.
**Mitigations**: roll back the prompt version; reorder the tier; fix the primary provider.
**Escalate** if cost alerts also fire.

## pipelinedegraded

**Means**: over 10% of completed runs had `degraded_structure` or `degraded_job` fail over 30m, i.e. resume or job parsing produced a degraded result.
**Likely causes**: a bad structuring or job analysis prompt, a low-tier model failing at structured output, unusual input formats.
**First checks**: "Page limit and degraded checks". Logs for `stage` `structure_resume` and `analyze_job`, by `workflow_id`. Compare `release_quality_daily` for those stages by prompt version.
**Mitigations**: pin the previous prompt version; raise the stage tier in `config/models.yaml` (for example `structure_resume: {tier: medium}`) as a temporary fix, watching cost.
**Escalate** if it lasts more than an hour.

## fabricationattemptratehigh

**Means**: the fabrication gates flagged more than 15% of planned blocks over 1h (at least 20 blocks). The gates stop these, but a high rate means the model is inventing more and more can slip through.
**Likely causes**: a model or prompt change, a weaker fallback model in use, resumes with little source content.
**First checks**: overview "Flagged and reverted blocks by rule" (which rule: `facts.numbers`, `facts.terms`, `facts.keywords`, `facts.claims`); quality dashboard "Fabrication attempt rate by day" and "Release quality by prompt version and model". Sample a few outputs from the logs by `workflow_id`.
**Mitigations**: roll back the prompt version or pin the previous one; move the model with the high rate down in the tier order; raise the stage tier.
**Escalate** if a human review of sampled outputs finds fabrications that escaped. The metric cannot see those.

## fabricationattemptrateregression

**Means**: the 6h fabrication attempt ratio is more than 2x the 7d ratio and above 5%. A change in behavior, even if under the absolute threshold.
**Likely causes**: a recent prompt or model change, a provider silently updating a model.
**First checks**: when did it start (overview panel, compare with deploy times). `release_quality_daily` grouped by `prompt_version` and `model`.
**Mitigations**: roll back the latest prompt version via `prompt_pins`; if a provider changed a model, pin the revision in `config/models.yaml`. Run the eval set before re-releasing.
**Escalate** if it keeps climbing after rollback.

## validationrevertratehigh

**Means**: one validation rule reverted more than 10% of planned blocks to the original text over 1h. The output is safe but the tailoring is weak.
**Likely causes**: the rewrite prompt makes changes this rule rejects (for example `layout.length` or `facts.terms`), or the rule itself changed.
**First checks**: the `rule` label in the alert; overview "Flagged and reverted blocks by rule"; `roletailor_ops.validation_daily` for that `rule_key` and `rule_version`.
**Mitigations**: roll back the prompt version; if the rule version changed recently, review that change.
**Escalate** if users complain about untailored resumes.

## pagelimitfailures

**Means**: more than 10% of page limit checks failed over 1h: resumes come out longer than allowed.
**Likely causes**: a rewrite prompt that adds text, a layout or template change, an unusual batch of long resumes.
**First checks**: "Page limit and degraded checks"; `roletailor_ops.validation_daily` rows for `layout.length`; logs by `workflow_id` for failed runs.
**Mitigations**: roll back the rewrite prompt version; tighten length instructions in the prompt.
**Escalate** if it persists after rollback.

## workermetricsdown

**Means**: Prometheus cannot scrape a worker (`roletailor-worker`, port 9101) for 5m. Generations probably are not running, or only the metrics endpoint is broken.
**Likely causes**: worker crashed or restarting, metrics server not started, network or DNS between Prometheus and worker, wrong port.
**First checks**: `docker compose ps` or your host's process view; worker logs; Prometheus targets page (`/targets`). Check `PROMETHEUS_MULTIPROC_DIR` exists and is writable.
**Mitigations**: restart the worker. If the queue grew, it will drain after. Other worker-based alerts are blind while this fires.
**Escalate** if a restart does not help.

## apidown

**Means**: Prometheus cannot scrape the API (`roletailor-api`, port 8000) for 2m.
**Likely causes**: API crashed, deploy in progress, database or Redis unavailable at startup, network.
**First checks**: API `/healthz`, API logs, Prometheus targets page, recent deploy.
**Mitigations**: restart or roll back the deploy; check Postgres and Redis health.
**Escalate** immediately if users cannot reach the app.

## nogenerationscompleted

**Means**: workflow requests were received in the last 30m but no run completed.
**Likely causes**: worker not consuming (Redis or Celery problem), all runs failing, workers stuck on a hung provider call.
**First checks**: workermetricsdown status, "Generation runs by outcome", the Celery queue length in Redis, worker logs. The alert counts only requests the API accepted.
**Mitigations**: restart workers; fix Redis; if every run fails, follow generationfailureratecritical.
**Escalate** immediately if the queue keeps growing.
