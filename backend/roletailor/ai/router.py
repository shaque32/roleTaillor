"""Model routing: stage -> tier -> ordered healthy models, with escalation and a
per-model circuit breaker. All policy lives in config/models.yaml."""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import yaml

from roletailor.ai.providers.base import ModelSpec

TIERS = ("low", "medium", "high")


@dataclass(frozen=True)
class StagePolicy:
    tier: str
    max_tier: str
    max_tokens: int


@dataclass(frozen=True)
class Route:
    spec: ModelSpec
    tier: str
    reason: str


class CircuitBreaker:
    def __init__(self, failures: int, window_s: float, cooldown_s: float):
        self._limit, self._window, self._cooldown = failures, window_s, cooldown_s
        self._fails: dict[str, deque[float]] = {}
        self._open_until: dict[str, float] = {}
        self._lock = threading.Lock()

    def available(self, key: str) -> bool:
        return time.monotonic() >= self._open_until.get(key, 0.0)

    def failure(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            q = self._fails.setdefault(key, deque())
            q.append(now)
            while q and now - q[0] > self._window:
                q.popleft()
            if len(q) >= self._limit:
                self._open_until[key] = now + self._cooldown
                q.clear()

    def success(self, key: str) -> None:
        with self._lock:
            self._fails.pop(key, None)


class ModelRouter:
    def __init__(self, config: dict):
        self.config = config
        self.models = {
            k: ModelSpec(key=k, provider=v["provider"], model=v["model"], revision=str(v["revision"]),
                         tier=v["tier"], effort=v.get("effort"), price=v.get("price", {}))
            for k, v in config["models"].items()
        }
        self.tiers: dict[str, list[str]] = config["tiers"]
        self.stages = {
            k: StagePolicy(tier=v["tier"], max_tier=v.get("max_tier", v["tier"]),
                           max_tokens=int(v.get("max_tokens", 4000)))
            for k, v in config["stages"].items()
        }
        self.boosts: dict[str, dict[str, int]] = config.get("customer_tier_boost", {})
        r = config.get("routing", {})
        cb = r.get("circuit_breaker", {})
        self.attempts_per_model = int(r.get("attempts_per_model", 2))
        self.timeout_s = float(r.get("request_timeout_seconds", 45))
        self.rewrite_batch_size = int(r.get("rewrite_batch_size", 8))
        self.rewrite_concurrency = int(r.get("rewrite_concurrency", 4))
        self.plan_escalate_on_low_confidence = bool(r.get("plan_escalate_on_low_confidence", False))
        self.breaker = CircuitBreaker(int(cb.get("failures", 3)), float(cb.get("window_seconds", 60)),
                                      float(cb.get("cooldown_seconds", 120)))

    @classmethod
    def from_file(cls, path: Path) -> ModelRouter:
        return cls(yaml.safe_load(path.read_text()))

    def policy(self, stage: str) -> StagePolicy:
        return self.stages[stage]

    def tier_for(self, stage: str, *, escalate: int = 0, customer_tier: str = "free") -> tuple[str, str]:
        """Return (tier, reason) for a stage after customer boost and escalation."""
        pol = self.policy(stage)
        boost = self.boosts.get(customer_tier, {}).get(stage, 0)
        idx = TIERS.index(pol.tier) + boost + escalate
        cap = TIERS.index(pol.max_tier)
        tier = TIERS[min(idx, cap, len(TIERS) - 1)]
        reasons = [f"stage={stage} base={pol.tier}"]
        if boost:
            reasons.append(f"customer_tier={customer_tier}+{boost}")
        if escalate:
            reasons.append(f"escalated+{escalate}")
        if idx > cap:
            reasons.append(f"capped={pol.max_tier}")
        return tier, " ".join(reasons)

    def routes(self, stage: str, *, escalate: int = 0, customer_tier: str = "free") -> list[Route]:
        """Healthy models for the stage, in failover order. Open circuits are skipped,
        but if every model in the tier is open we still try them (best effort)."""
        tier, reason = self.tier_for(stage, escalate=escalate, customer_tier=customer_tier)
        keys = self.tiers[tier]
        healthy = [k for k in keys if self.breaker.available(k)]
        ordered = healthy or keys
        out = []
        for i, k in enumerate(ordered):
            why = reason if i == 0 else f"{reason} failover#{i}"
            if len(healthy) < len(keys):
                why += f" skipped_open={','.join(sorted(set(keys) - set(healthy)))}"
            out.append(Route(spec=self.models[k], tier=tier, reason=why))
        return out
