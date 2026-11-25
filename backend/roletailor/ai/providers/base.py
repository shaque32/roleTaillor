from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class ModelSpec:
    key: str  # config key, e.g. "claude-haiku"
    provider: str
    model: str
    revision: str
    tier: str
    effort: str | None = None
    price: dict[str, float] = field(default_factory=dict)

    def cost(self, usage: Usage) -> float:
        p = self.price
        uncached = max(usage.input_tokens - usage.cache_read_tokens - usage.cache_write_tokens, 0)
        total = (
            uncached * p.get("input", 0)
            + usage.cache_read_tokens * p.get("cache_read", p.get("input", 0))
            + usage.cache_write_tokens * p.get("cache_write", p.get("input", 0))
            + usage.output_tokens * p.get("output", 0)
        )
        return round(total / 1_000_000, 8)


@dataclass
class Usage:
    # input_tokens is the TOTAL prompt size including cached tokens.
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass(frozen=True)
class LLMRequest:
    prompt_key: str
    # Static instructions. Identical across requests for a prompt version so the
    # provider's prefix cache can hit.
    system: str
    # Per-request payload (JSON text). Always after the static prefix.
    user: str
    json_schema: dict
    max_tokens: int
    timeout_s: float = 45.0


@dataclass
class LLMResponse:
    text: str
    usage: Usage
    latency_ms: int


class ProviderError(Exception):
    """A provider call failed. `transient` errors are worth failing over."""

    def __init__(self, message: str, *, code: str, transient: bool = True):
        super().__init__(message)
        self.code = code
        self.transient = transient


class Provider(Protocol):
    name: str

    def complete(self, spec: ModelSpec, req: LLMRequest) -> LLMResponse: ...
