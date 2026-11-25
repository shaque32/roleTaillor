from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
ENVIRONMENTS = frozenset({"dev", "test", "staging", "prod"})
PLANS = frozenset({"free", "subscription"})
PLAN_LIMIT_KEYS = frozenset({"runs_per_day", "iterations"})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RT_", env_file=".env", extra="ignore")

    environment: str = "dev"  # dev | staging | prod; selects prompt_versions.environment

    # The app connects as a non-BYPASSRLS role. Migrations run as the schema owner.
    database_url: str = "postgresql+psycopg://rt_app:rt_app@localhost:5432/roletailor"
    redis_url: str = "redis://localhost:6379/0"

    # AI
    models_config_path: Path = REPO_ROOT / "config" / "models.yaml"
    llm_cache_ttl_seconds: int = 7 * 24 * 3600
    # "live" calls real providers. "fake" uses the deterministic offline provider
    # (tests, local dev without keys, CI).
    llm_mode: str = "live"

    # Storage: "local" for dev/tests, "s3" for deployed environments.
    storage_backend: str = "local"
    storage_local_dir: Path = REPO_ROOT / ".data" / "files"
    s3_bucket: str = "roletailor-files"
    s3_region: str = "us-east-1"
    signed_url_ttl_seconds: int = 900

    # Auth
    session_ttl_hours: int = 24 * 14
    cors_origins: list[str] = ["http://localhost:3000"]

    # Billing
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_subscription_price_id: str = ""
    stripe_pay_per_use_price_id: str = ""
    pay_per_use_amount_minor: int = 50  # USD 0.50

    # Generation limits
    max_upload_bytes: int = 10 * 1024 * 1024
    default_page_limit: int = 2

    # Platform (API, worker, migrations)
    # Schema owner connection used only by db/migrate.py.
    migration_database_url: str = "postgresql://rt_owner:rt_owner@localhost:5432/roletailor"
    # Public URLs: the API (share links, local signed URLs) and the web app (Stripe redirects).
    api_base_url: str = "http://localhost:8000"
    app_base_url: str = "http://localhost:3000"
    # HMAC key for LocalStorage signed URLs. Must be set outside dev.
    secret_key: str = "dev-insecure-secret-change-me"
    s3_endpoint_url: str | None = None  # e.g. MinIO in dev; None uses AWS
    log_level: str = "INFO"
    # Fixed-window rate limits, requests per minute per client.
    rate_limit_auth_per_minute: int = 10
    rate_limit_generation_per_minute: int = 20
    # Failed and successful logins per account per hour, and sign-ups per client per day.
    rate_limit_login_per_hour: int = 30
    rate_limit_register_per_day: int = 20
    # Per-user limits on the other expensive endpoints, requests per minute.
    rate_limit_upload_per_minute: int = 10
    rate_limit_job_per_minute: int = 15
    rate_limit_export_per_minute: int = 20
    rate_limit_billing_per_minute: int = 6
    rate_limit_account_per_minute: int = 5
    # Spend ceilings: every run (first generation, iteration or retry) calls the models,
    # and only a workflow's first run is ever charged.
    generation_runs_per_org_per_day: int = 60
    max_iterations_per_workflow: int = 15
    # Per-plan overrides of the two ceilings above, as JSON. Plans are "free" and
    # "subscription"; keys are "runs_per_day" and "iterations". Anything left out uses
    # the defaults, e.g. RT_PLAN_LIMITS={"subscription": {"runs_per_day": 200}}
    plan_limits: dict[str, dict[str, int]] = {}
    # A deleted resume is erased for good this many days later, by the nightly purge
    # (worker beat schedule, hour in UTC).
    resume_retention_days: int = 30
    retention_purge_hour_utc: int = 8
    retention_purge_batch_size: int = 500
    # Request bodies. Uploads get max_upload_bytes plus multipart overhead.
    max_json_body_bytes: int = 512 * 1024
    # Client address for rate limiting. `client_ip_header` is a header the platform edge
    # sets itself and overwrites (Fly: "Fly-Client-IP"); empty uses the socket peer.
    # Requests the web app proxies carry the browser's address in X-RT-Client-IP, which
    # is believed only together with this shared secret in X-RT-Proxy-Secret.
    client_ip_header: str = ""
    proxy_shared_secret: str = ""
    # When set, GET /metrics needs "Authorization: Bearer <token>". Outside dev/test,
    # /metrics is also hidden from requests that arrived through the public edge.
    metrics_token: str = ""
    # Document parsing runs in a child process with these limits.
    parse_timeout_seconds: float = 75.0
    parse_memory_limit_mb: int = 768
    parse_cpu_seconds: int = 60
    max_resume_pdf_pages: int = 20
    max_resume_blocks: int = 3000
    # Job URL fetching
    job_fetch_timeout_seconds: float = 10.0
    job_fetch_total_seconds: float = 25.0  # wall-clock budget for one URL, redirects included
    job_fetch_max_bytes: int = 2 * 1024 * 1024
    # Ashby's public API only serves a whole job board at once, which can pass 2 MB.
    job_fetch_board_max_bytes: int = 8 * 1024 * 1024
    share_link_max_hours: int = 24 * 30
    celery_task_always_eager: bool = False
    worker_metrics_port: int = 9101  # 0 disables the worker's Prometheus endpoint

    @model_validator(mode="after")
    def _check_production_config(self) -> Settings:
        if self.environment not in ENVIRONMENTS:
            raise ValueError(f"RT_ENVIRONMENT must be one of {sorted(ENVIRONMENTS)}")
        if self.environment in {"dev", "test"}:
            return self
        problems: list[str] = []
        if self.secret_key == "dev-insecure-secret-change-me" or len(self.secret_key) < 32:
            problems.append("RT_SECRET_KEY must be set to 32+ characters")
        if self.storage_backend == "local":
            problems.append("RT_STORAGE_BACKEND must not be 'local'")
        if ":rt_app@" in self.database_url or ":rt_owner@" in self.database_url:
            problems.append("RT_DATABASE_URL still uses a development password")
        if len(self.proxy_shared_secret) < 32:
            problems.append("RT_PROXY_SHARED_SECRET must be set to 32+ characters (the web app sends"
                            " the same value as API_PROXY_SECRET)")
        for name, url in (("RT_API_BASE_URL", self.api_base_url), ("RT_APP_BASE_URL", self.app_base_url),
                          *(("RT_CORS_ORIGINS", origin) for origin in self.cors_origins)):
            if not url.startswith("https://") or "localhost" in url or "127.0.0.1" in url:
                problems.append(f"{name} must be a public https URL, got {url!r}")
        if "*" in self.cors_origins:
            problems.append("RT_CORS_ORIGINS must not contain '*'")
        if self.environment == "prod" and self.llm_mode != "live":
            problems.append("RT_LLM_MODE must be 'live' in prod")
        if problems:
            raise ValueError("unsafe configuration outside dev/test: " + "; ".join(problems))
        return self

    @field_validator("plan_limits")
    @classmethod
    def _check_plan_limits(cls, v: dict[str, dict[str, int]]) -> dict[str, dict[str, int]]:
        for plan, limits in v.items():
            if plan not in PLANS:
                raise ValueError(f"RT_PLAN_LIMITS: unknown plan {plan!r}, expected one of {sorted(PLANS)}")
            for key, value in limits.items():
                if key not in PLAN_LIMIT_KEYS:
                    raise ValueError(f"RT_PLAN_LIMITS: unknown limit {key!r} for plan {plan!r},"
                                     f" expected one of {sorted(PLAN_LIMIT_KEYS)}")
                if value < 1:
                    raise ValueError(f"RT_PLAN_LIMITS: {plan}.{key} must be at least 1")
        return v

    @field_validator("resume_retention_days")
    @classmethod
    def _check_retention(cls, v: int) -> int:
        if v < 1:
            raise ValueError("RT_RESUME_RETENTION_DAYS must be at least 1")
        return v

    @field_validator("retention_purge_hour_utc")
    @classmethod
    def _check_purge_hour(cls, v: int) -> int:
        if not 0 <= v <= 23:
            raise ValueError("RT_RETENTION_PURGE_HOUR_UTC must be between 0 and 23")
        return v

    def limits_for_plan(self, plan: str) -> tuple[int, int]:
        """(runs per organization per day, iterations per workflow) for a plan."""
        override = self.plan_limits.get(plan, {})
        return (override.get("runs_per_day", self.generation_runs_per_org_per_day),
                override.get("iterations", self.max_iterations_per_workflow))

    @field_validator("models_config_path", "storage_local_dir")
    @classmethod
    def _anchor_to_repo(cls, v: Path) -> Path:
        # .env uses repo-relative paths (config/models.yaml); the API, worker, tests, and
        # evals start from different directories, so never resolve against the cwd.
        return v if v.is_absolute() else REPO_ROOT / v


@lru_cache
def get_settings() -> Settings:
    return Settings()
