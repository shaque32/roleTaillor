from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
ENVIRONMENTS = frozenset({"dev", "test", "staging", "prod"})
EMAIL_PROVIDERS = frozenset({"console", "memory", "resend"})


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

    # Transactional email (verification and password reset links).
    # "console" writes the message to the log (dev), "memory" keeps it in process (tests),
    # "resend" sends through the Resend API. See docs/email-setup.md.
    email_provider: str = "console"
    resend_api_key: str = Field(default="", validation_alias=AliasChoices("RT_RESEND_API_KEY", "RESEND_API_KEY"))
    email_from: str = "RoleTailor <no-reply@roletailor.example>"
    email_reply_to: str = ""
    email_send_timeout_seconds: float = 10.0
    email_verification_ttl_hours: int = 24
    password_reset_ttl_minutes: int = 60
    # Generations (the only step that costs model spend) need a confirmed address.
    require_verified_email: bool = True

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
    # Reset emails per address and verification emails per user, per hour.
    rate_limit_password_reset_per_hour: int = 5
    rate_limit_verification_email_per_hour: int = 5
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
        if self.email_provider not in EMAIL_PROVIDERS:
            raise ValueError(f"RT_EMAIL_PROVIDER must be one of {sorted(EMAIL_PROVIDERS)}")
        if self.environment in {"dev", "test"}:
            return self
        problems: list[str] = []
        if self.email_provider == "memory":
            problems.append("RT_EMAIL_PROVIDER 'memory' is for tests only")
        if self.environment == "prod" and self.email_provider != "resend":
            problems.append("RT_EMAIL_PROVIDER must be 'resend' in prod (the console provider only logs)")
        if self.email_provider == "resend":
            if not self.resend_api_key:
                problems.append("RESEND_API_KEY must be set when RT_EMAIL_PROVIDER is 'resend'")
            if ".example" in self.email_from or "@" not in self.email_from:
                problems.append("RT_EMAIL_FROM must be an address on a domain verified in Resend,"
                                f" got {self.email_from!r}")
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

    @field_validator("models_config_path", "storage_local_dir")
    @classmethod
    def _anchor_to_repo(cls, v: Path) -> Path:
        # .env uses repo-relative paths (config/models.yaml); the API, worker, tests, and
        # evals start from different directories, so never resolve against the cwd.
        return v if v.is_absolute() else REPO_ROOT / v


@lru_cache
def get_settings() -> Settings:
    return Settings()
