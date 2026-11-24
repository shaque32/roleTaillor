"""Claude via the official Anthropic SDK, with structured outputs and prompt caching."""

from __future__ import annotations

import time

import anthropic

from roletailor.ai.providers.base import LLMRequest, LLMResponse, ModelSpec, ProviderError, Usage


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str | None = None, client: anthropic.Anthropic | None = None):
        # max_retries=0: failover and retries are owned by the gateway so every
        # attempt is visible in ai_metrics.
        self._client = client or anthropic.Anthropic(api_key=api_key, max_retries=0)

    def complete(self, spec: ModelSpec, req: LLMRequest) -> LLMResponse:
        output_config: dict = {
            "format": {"type": "json_schema", "schema": anthropic.transform_schema(req.json_schema)}
        }
        if spec.effort:
            output_config["effort"] = spec.effort
        started = time.monotonic()
        try:
            msg = self._client.with_options(timeout=req.timeout_s).messages.create(
                model=spec.model,
                max_tokens=req.max_tokens,
                # The static system prompt is the cache prefix; the payload follows it.
                system=[{"type": "text", "text": req.system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": req.user}],
                output_config=output_config,
            )
        except anthropic.APITimeoutError as e:
            raise ProviderError(str(e), code="timeout") from e
        except anthropic.RateLimitError as e:
            raise ProviderError(str(e), code="rate_limited") from e
        except anthropic.APIConnectionError as e:
            raise ProviderError(str(e), code="connection") from e
        except anthropic.APIStatusError as e:
            transient = e.status_code >= 500 or e.status_code in (408, 409, 529)
            raise ProviderError(str(e), code=f"http_{e.status_code}", transient=transient) from e

        latency = int((time.monotonic() - started) * 1000)
        if msg.stop_reason == "refusal":
            raise ProviderError("model refused", code="refusal", transient=True)
        if msg.stop_reason == "max_tokens":
            raise ProviderError("output truncated at max_tokens", code="max_tokens")
        text = next((b.text for b in msg.content if b.type == "text"), "")
        u = msg.usage
        cache_read = u.cache_read_input_tokens or 0
        cache_write = u.cache_creation_input_tokens or 0
        usage = Usage(
            input_tokens=u.input_tokens + cache_read + cache_write,
            output_tokens=u.output_tokens,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
        )
        return LLMResponse(text=text, usage=usage, latency_ms=latency)
