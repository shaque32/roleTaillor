"""The single entry point for model calls.

`Gateway.run` takes a stage, a versioned prompt, a JSON payload, and a pydantic output
model, and returns a validated instance. It owns routing, failover, schema-repair
retries, escalation, caching, cost accounting, and telemetry, so pipeline stages stay
small and deterministic code never touches a provider SDK.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from roletailor.ai.cache import MemoryCache, RedisCache, ResponseCache, cache_key
from roletailor.ai.prompts.registry import PromptRegistry
from roletailor.ai.providers.base import LLMRequest, Provider, ProviderError, Usage
from roletailor.ai.router import ModelRouter, Route
from roletailor.ai.telemetry import CallRecord, MetricsSink
from roletailor.config import Settings, get_settings

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class AIUnavailable(RuntimeError):
    """Every model for a stage failed. The pipeline decides how to degrade."""

    def __init__(self, stage: str, last_error: str):
        super().__init__(f"{stage}: all models failed ({last_error})")
        self.stage = stage
        self.last_error = last_error


def _payload_text(payload: dict) -> str:
    # Sorted keys keep identical payloads byte-identical for the response cache.
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


class Gateway:
    def __init__(self, *, router: ModelRouter, registry: PromptRegistry,
                 providers: dict[str, Provider], sink: MetricsSink, cache: ResponseCache,
                 cache_ttl_s: int, trace_id: str | None = None, customer_tier: str = "free"):
        self.router = router
        self.registry = registry
        self.providers = providers
        self.sink = sink
        self.cache = cache
        self.cache_ttl_s = cache_ttl_s
        self.trace_id = trace_id or uuid.uuid4().hex
        self.customer_tier = customer_tier
        self._attempts: dict[str, int] = {}
        self._lock = threading.Lock()
        self.total_cost_usd = 0.0

    def _next_attempt(self, label: str) -> int:
        with self._lock:
            self._attempts[label] = self._attempts.get(label, 0) + 1
            return self._attempts[label]

    def run(self, *, stage: str, label: str, prompt_key: str, payload: dict,
            output: type[T], escalate: int = 0) -> T:
        """`stage` selects routing policy; `label` is the unique ai_metrics stage name
        for this call (for example "it1:rewrite:b2")."""
        prompt = self.registry.get(prompt_key)
        policy = self.router.policy(stage)
        schema = output.model_json_schema()
        user = _payload_text(payload)
        last_error = "no models configured"

        for route in self.router.routes(stage, escalate=escalate, customer_tier=self.customer_tier):
            key = cache_key(route.spec.model, prompt.sha256, user, schema)
            if (hit := self.cache.get(key)) is not None:
                try:
                    parsed = output.model_validate_json(hit)
                except ValidationError:
                    parsed = None
                if parsed is not None:
                    self._record(label, route, prompt, "cached", Usage(), 0, None, "cache_hit")
                    return parsed

            repair = ""
            for _ in range(self.router.attempts_per_model):
                req = LLMRequest(prompt_key=prompt.key, system=prompt.text, user=user + repair,
                                 json_schema=schema, max_tokens=policy.max_tokens,
                                 timeout_s=self.router.timeout_s)
                provider = self.providers[route.spec.provider]
                started = time.monotonic()
                try:
                    resp = provider.complete(route.spec, req)
                except ProviderError as e:
                    status = "timed_out" if e.code == "timeout" else "failed"
                    waited_ms = int((time.monotonic() - started) * 1000)  # time lost before failing
                    self._record(label, route, prompt, status, Usage(), waited_ms, e.code, route.reason)
                    self.router.breaker.failure(route.spec.key)
                    last_error = e.code
                    break  # fail over to the next model
                try:
                    parsed = output.model_validate_json(_strip_fences(resp.text))
                except ValidationError as e:
                    self._record(label, route, prompt, "failed", resp.usage, resp.latency_ms,
                                 "schema_invalid", route.reason)
                    last_error = "schema_invalid"
                    repair = ("\n\nYour previous reply did not match the required JSON schema: "
                              f"{_short(e)}. Reply again with valid JSON only.")
                    continue
                self.router.breaker.success(route.spec.key)
                self._record(label, route, prompt, "succeeded", resp.usage, resp.latency_ms, None,
                             route.reason)
                self.cache.set(key, parsed.model_dump_json(), self.cache_ttl_s)
                return parsed
        raise AIUnavailable(label, last_error)

    def _record(self, label: str, route: Route, prompt, status: str, usage: Usage,
                latency_ms: int, error: str | None, reason: str) -> None:
        cost = route.spec.cost(usage) if status != "cached" else 0.0
        with self._lock:
            self.total_cost_usd += cost
        self.sink.record(CallRecord(
            stage=label, attempt=self._next_attempt(label), provider=route.spec.provider,
            model_name=route.spec.model, model_revision=route.spec.revision,
            capability_tier=route.tier, prompt_key=prompt.key, prompt_version=prompt.version,
            prompt_text=prompt.text, status=status, routing_reason=reason, latency_ms=latency_ms,
            input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
            cache_read_tokens=usage.cache_read_tokens, estimated_cost_usd=cost,
            error_code=error, trace_id=self.trace_id,
        ))


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        t = t.rsplit("```", 1)[0]
    return t.strip()


def _short(e: ValidationError) -> str:
    return "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()[:5])


def _live_providers(router: ModelRouter) -> dict[str, Provider]:
    from roletailor.ai.providers.anthropic_provider import AnthropicProvider
    from roletailor.ai.providers.openai_compat import OpenAICompatProvider

    out: dict[str, Provider] = {}
    for name, cfg in router.config.get("providers", {}).items():
        key = os.environ.get(cfg.get("api_key_env", ""), None)
        if name == "anthropic":
            out[name] = AnthropicProvider(api_key=key)
        else:
            out[name] = OpenAICompatProvider(name, api_key=key or "missing",
                                             base_url=cfg.get("base_url"))
    return out


_router_singleton: ModelRouter | None = None


def _router(settings: Settings) -> ModelRouter:
    # One router per process so circuit-breaker state is shared across workflows.
    global _router_singleton
    if _router_singleton is None:
        _router_singleton = ModelRouter.from_file(settings.models_config_path)
    return _router_singleton


def build_gateway(sink: MetricsSink, *, settings: Settings | None = None,
                  cache: ResponseCache | None = None,
                  providers: dict[str, Provider] | None = None,
                  router: ModelRouter | None = None,
                  customer_tier: str = "free", trace_id: str | None = None) -> Gateway:
    settings = settings or get_settings()
    router = router or _router(settings)
    pins = router.config.get("prompt_pins", {}).get(settings.environment, {}) or {}
    if providers is None:
        if settings.llm_mode == "fake":
            from roletailor.ai.providers.fake import FakeProvider

            fake = FakeProvider()
            providers = {name: fake for name in {m.provider for m in router.models.values()}}
        else:
            providers = _live_providers(router)
    if cache is None:
        cache = RedisCache(settings.redis_url) if settings.llm_mode == "live" else MemoryCache()
    return Gateway(router=router, registry=PromptRegistry(pins=pins), providers=providers,
                   sink=sink, cache=cache, cache_ttl_s=settings.llm_cache_ttl_seconds,
                   trace_id=trace_id, customer_tier=customer_tier)
