"""OpenAI-compatible chat APIs: DeepSeek today; OpenAI, Gemini's compatible endpoint,
vLLM, or Ollama with config only. Uses JSON mode and puts the schema in the static
system prompt so the provider's automatic prefix cache still applies."""

from __future__ import annotations

import json
import time

import openai

from roletailor.ai.providers.base import LLMRequest, LLMResponse, ModelSpec, ProviderError, Usage


class OpenAICompatProvider:
    def __init__(self, name: str, *, api_key: str | None, base_url: str | None = None,
                 client: openai.OpenAI | None = None):
        self.name = name
        self._client = client or openai.OpenAI(api_key=api_key, base_url=base_url, max_retries=0)

    def complete(self, spec: ModelSpec, req: LLMRequest) -> LLMResponse:
        system = (
            f"{req.system}\n\nRespond with one JSON object only, matching this JSON Schema:\n"
            f"{json.dumps(req.json_schema, sort_keys=True)}"
        )
        started = time.monotonic()
        try:
            resp = self._client.with_options(timeout=req.timeout_s).chat.completions.create(
                model=spec.model,
                max_tokens=req.max_tokens,
                response_format={"type": "json_object"},
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": req.user}],
            )
        except openai.APITimeoutError as e:
            raise ProviderError(str(e), code="timeout") from e
        except openai.RateLimitError as e:
            raise ProviderError(str(e), code="rate_limited") from e
        except openai.APIConnectionError as e:
            raise ProviderError(str(e), code="connection") from e
        except openai.APIStatusError as e:
            raise ProviderError(str(e), code=f"http_{e.status_code}",
                                transient=e.status_code >= 500) from e

        latency = int((time.monotonic() - started) * 1000)
        choice = resp.choices[0]
        if choice.finish_reason == "length":
            raise ProviderError("output truncated at max_tokens", code="max_tokens")
        u = resp.usage
        # DeepSeek reports prefix-cache hits as prompt_cache_hit_tokens.
        hit = getattr(u, "prompt_cache_hit_tokens", None) or getattr(
            getattr(u, "prompt_tokens_details", None), "cached_tokens", 0) or 0
        usage = Usage(input_tokens=u.prompt_tokens if u else 0,
                      output_tokens=u.completion_tokens if u else 0, cache_read_tokens=hit)
        return LLMResponse(text=choice.message.content or "", usage=usage, latency_ms=latency)
