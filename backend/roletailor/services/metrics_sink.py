"""MetricsSink that persists AI call telemetry (ai_metrics, ai_model_versions, prompt_versions).

`record()` is called from the pipeline's rewrite thread pool, so it is serialized by a
lock and every call uses its own short transaction (no connection is shared across
threads). Attempts restart at 1 when Celery retries a run; a clash on
(workflow, stage, attempt) is resolved by appending after the highest stored attempt.
"""

from __future__ import annotations

import threading
from uuid import UUID

from roletailor import db
from roletailor.ai.telemetry import CallRecord
from roletailor.config import get_settings
from roletailor.services.sql import fetch_one

_METRIC_INSERT = (
    "INSERT INTO ai_metrics (organization_id, workflow_id, model_version_id, prompt_version_id,"
    " stage, attempt, status, routing_reason, trace_id, latency_ms, input_tokens, output_tokens,"
    " estimated_cost_usd, error_code, created_at)"
    " VALUES (:org, :wf, :model, :prompt, :stage, {attempt}, :status, :reason, :trace, :latency,"
    " :input, :output, :cost, :error, :created)"
)


class DbMetricsSink:
    def __init__(self, org_id: UUID | str, workflow_id: UUID | str):
        self.org_id = str(org_id)
        self.workflow_id = str(workflow_id)
        self.metric_ids: dict[str, UUID] = {}  # stage label -> latest ai_metrics.id
        self._models: dict[tuple[str, str, str], UUID] = {}
        self._prompts: dict[tuple[str, int], UUID] = {}
        self._lock = threading.Lock()

    def record(self, rec: CallRecord) -> None:
        with self._lock, db.tenant_tx(self.org_id) as conn:
            params = {
                "org": self.org_id, "wf": self.workflow_id,
                "model": self._model_id(conn, rec), "prompt": self._prompt_id(conn, rec),
                "stage": rec.stage, "attempt": rec.attempt, "status": rec.status,
                "reason": rec.routing_reason, "trace": rec.trace_id, "latency": rec.latency_ms,
                "input": rec.input_tokens, "output": rec.output_tokens,
                "cost": rec.estimated_cost_usd, "error": rec.error_code,
                "created": rec.completed_at,
            }
            row = fetch_one(
                conn,
                _METRIC_INSERT.format(attempt=":attempt")
                + " ON CONFLICT (organization_id, workflow_id, stage, attempt) DO NOTHING RETURNING id",
                params,
            )
            if row is None:
                row = fetch_one(
                    conn,
                    _METRIC_INSERT.format(
                        attempt="(SELECT coalesce(max(attempt), 0) + 1 FROM ai_metrics"
                        " WHERE workflow_id = :wf AND stage = :stage)"
                    ) + " RETURNING id",
                    params,
                )
            assert row is not None
            self.metric_ids[rec.stage] = row["id"]

    def _model_id(self, conn, rec: CallRecord) -> UUID:
        key = (rec.provider, rec.model_name, rec.model_revision)
        if key not in self._models:
            row = fetch_one(
                conn,
                "INSERT INTO ai_model_versions (provider, model_name, revision, capability_tier)"
                " VALUES (:p, :m, :r, :t) ON CONFLICT (provider, model_name, revision)"
                " DO UPDATE SET capability_tier = EXCLUDED.capability_tier RETURNING id",
                {"p": rec.provider, "m": rec.model_name, "r": rec.model_revision,
                 "t": rec.capability_tier},
            )
            assert row is not None
            self._models[key] = row["id"]
        return self._models[key]

    def _prompt_id(self, conn, rec: CallRecord) -> UUID:
        key = (rec.prompt_key, rec.prompt_version)
        if key not in self._prompts:
            params = {"k": rec.prompt_key, "e": get_settings().environment,
                      "v": rec.prompt_version, "t": rec.prompt_text}
            row = fetch_one(
                conn,
                "INSERT INTO prompt_versions (prompt_key, environment, version_number, template_text)"
                " VALUES (:k, :e, :v, :t) ON CONFLICT (prompt_key, environment, version_number)"
                " DO NOTHING RETURNING id",
                params,
            ) or fetch_one(
                conn,
                "SELECT id FROM prompt_versions WHERE prompt_key = :k AND environment = :e"
                " AND version_number = :v",
                params,
            )
            assert row is not None
            self._prompts[key] = row["id"]
        return self._prompts[key]
