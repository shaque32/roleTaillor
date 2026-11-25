# Monitoring

Cost, latency, errors and fabrication monitoring for RoleTailor. Names of metrics, labels, recording rules and SQL views are fixed in `docs/monitoring-contract.md`. Alert responses are in `docs/runbooks/ai-alerts.md`. Nothing here is tied to one vendor.

## Architecture

Two signal paths:

1. **Prometheus metrics** from the API (`api:8000/metrics`) and the worker (`worker:9101/metrics`). Recording and alert rules run on these. This is the real-time path and drives Alertmanager.
2. **SQL ops views** (schema `roletailor_ops`, read by the `rt_metrics` role) for drill-down, finance and release comparison. Grafana reads them through its Postgres datasource.

```
worker --/metrics--> Prometheus --rules--> Alertmanager --> Slack / email / PagerDuty
api    --/metrics-->     |
                         +--> Grafana "AI overview"
Postgres roletailor_ops --> Grafana "AI quality and cost (SQL)"
```

Files:
- `ops/monitoring/prometheus/prometheus.yml`, `rules/recording.yml`, `rules/alerts.yml`, `tests/alerts_test.yml`
- `ops/monitoring/alertmanager/alertmanager.yml`
- `ops/monitoring/grafana/` (provisioning and the two dashboards)
- `docker-compose.monitoring.yml`

## Run locally

```
docker compose -f docker-compose.yml -f docker-compose.monitoring.yml up
```

- Prometheus: http://localhost:9090 (Alerts and Targets pages)
- Alertmanager: http://localhost:9093
- Grafana: http://localhost:3001, user `admin`, password from `GRAFANA_ADMIN_PASSWORD` (default `change-me-locally`). Anonymous access is off.
- The SQL dashboard needs the `rt_metrics` role. Set `RT_METRICS_DB_PASSWORD` in `.env` to its password.
- On a fresh database volume `db/init/00_roles.sql` creates the role before migration 004 grants it access. On an existing database the init script does not run and migration 004 skips the grants when the role is missing, so create it once as a superuser or the schema owner with CREATEROLE:

```sql
CREATE ROLE rt_metrics LOGIN PASSWORD '<password>' NOBYPASSRLS;
GRANT CONNECT ON DATABASE roletailor TO rt_metrics;
GRANT USAGE ON SCHEMA roletailor_ops TO rt_metrics;
GRANT SELECT ON ALL TABLES IN SCHEMA roletailor_ops TO rt_metrics;
```

  Keep the role read-only. Never grant it writes or anything in `roletailor.*`.

## Validate rules

With Docker (needs a running daemon):

```
docker run --rm -v "$PWD/ops/monitoring/prometheus:/p" --entrypoint sh prom/prometheus:v2.53.2 -c 'promtool check rules /p/rules/recording.yml /p/rules/alerts.yml && promtool test rules /p/tests/alerts_test.yml'
```

The same two checks run in GitHub Actions (`.github/workflows/monitoring.yml`) on pull requests that touch the rules.

Without Docker, `python3 ops/monitoring/check_rules.py` checks structure, runbook anchors and metric names (it does not evaluate PromQL).

## Deploy on any host

- **Self-hosted**: run the overlay as above, or run the three containers with the same mounted files. Set real passwords, put Prometheus, Alertmanager and the metrics ports on a private network, and use TLS for the Postgres connection (`sslmode: verify-full` in `datasources.yml`).
- **Grafana Cloud or other managed Prometheus**: scrape `api:8000` and `worker:9101` with an agent (Grafana Alloy, Prometheus `remote_write`, OpenTelemetry collector) using the job names `roletailor-api` and `roletailor-worker` (the alerts depend on them). Upload `rules/recording.yml` and `rules/alerts.yml` to the managed ruler (for example with `mimirtool rules load`), configure the managed Alertmanager from `alertmanager.yml`, and import the two dashboard JSON files. Create datasources with uids `prometheus` and `roletailor-pg`, or edit the uids in the JSON.
- Set `runbook_url` to a full URL if your docs are hosted; today it is the repo path `docs/runbooks/ai-alerts.md#<alertname lower case>`.

## Thresholds

| Alert | Condition | Severity | Rationale |
|---|---|---|---|
| GenerationCostHigh | mean cost per generation 30m > $0.06 for 30m | warning | 50% above the ~$0.04 target |
| GenerationCostCritical | > $0.10 for 15m | critical | 2.5x target |
| DailyAISpendOverBudget | 24h spend > `roletailor:ai_spend_budget_usd:daily` ($50) | warning | one place to edit the budget |
| AISpendSpike | 1h spend > 3x hourly 24h average and > $1 | warning | burst or retry storm; $1 filters tiny numbers |
| FailedRunSpend | failed-run spend 1h > $2 | warning | about 50 wasted generations at target cost |
| GenerationLatencyHigh | p95 run time 15m > 120s for 15m | warning | normal runs take well under a minute or two; to be set from the live eval |
| GenerationLatencyCritical | > 300s for 10m | critical | users will abandon |
| AIStageLatencyHigh | p95 call time > 30s for 15m | warning | request timeout is 45s, so this is the warning before timeouts |
| GenerationFailureRateHigh | > 5% for 15m, 5 or more runs | warning | |
| GenerationFailureRateCritical | > 20% for 10m | critical | |
| AIProviderErrorRateHigh | per provider > 20% failed or timed out for 10m, 10 or more calls | warning | failover should absorb less |
| AIFallbackRateHigh | > 25% failover or escalated for 15m | warning | cost and latency grow with fallbacks |
| PipelineDegraded | runs with a degraded structure or job parse > 10% of completed runs, 30m | warning | |
| FabricationAttemptRateHigh | 1h ratio > 15%, 20 or more blocks, for 30m | warning | set above the eval baseline; adjust after the live eval |
| FabricationAttemptRateRegression | 6h ratio > 2x 7d ratio and > 5% | warning | catches prompt or model regressions |
| ValidationRevertRateHigh | any rule reverted > 10% of planned blocks, 1h | warning | |
| PageLimitFailures | page limit fail > 10% of checks, 1h, 10 or more | warning | |
| WorkerMetricsDown | `up` == 0 for 5m | critical | |
| ApiDown | `up` == 0 for 2m | critical | |
| NoGenerationsCompleted | accepted requests in 30m, none completed | warning | |

Every ratio alert also needs a minimum volume, so a single bad run in a quiet hour does not page anyone.

## Tuning

- Change numbers in `rules/alerts.yml` (and the budget in `rules/recording.yml`), then run the validation command and reload Prometheus (`POST /-/reload` if started with `--web.enable-lifecycle`, or restart).
- Start from real traffic: after the live eval and the first weeks, compare thresholds with the dashboards (p95 cost, p95 run time, fabrication attempt rate by day) and move them to just above normal peaks.
- If an alert is noisy, lengthen `for:` or the minimum volume before raising the threshold.
- If you add a metric or label, change `docs/monitoring-contract.md` first.

## Limits

- The fabrication rate measures attempts the gates caught, not fabrications that escaped. Escaped ones need human review of sampled outputs.
- Only ranges with enough traffic are useful. Low-volume periods suppress ratio alerts by design.
- Counters live in the worker's multiprocess directory and reset when it is cleared; `rate` and `increase` handle resets but a long worker outage hides data.
- NoGenerationsCompleted counts only requests the API accepted (`outcome="accepted"`), so rejected requests do not trigger it.
- The `/metrics` endpoints have no authentication. Keep them on a private network. This is to be covered by the later security review, together with rate limits and retention.
- Metrics hold no organization, user or resume text. Organization ids appear only in the SQL views.
