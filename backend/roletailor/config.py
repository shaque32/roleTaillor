from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


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
    # Job URL fetching
    job_fetch_timeout_seconds: float = 10.0
    job_fetch_max_bytes: int = 2 * 1024 * 1024
    # Ashby's public API only serves a whole job board at once, which can pass 2 MB.
    job_fetch_board_max_bytes: int = 8 * 1024 * 1024
    share_link_max_hours: int = 24 * 30
    celery_task_always_eager: bool = False
    worker_metrics_port: int = 9101  # 0 disables the worker's Prometheus endpoint

    @model_validator(mode="after")
    def _check_production_config(self) -> Settings:
        if self.environment not in {"dev", "test"}:
            if self.secret_key == "dev-insecure-secret-change-me" or len(self.secret_key) < 32:
                raise ValueError("RT_SECRET_KEY must be set to 32+ characters outside dev/test")
            if self.storage_backend == "local":
                raise ValueError("RT_STORAGE_BACKEND must not be 'local' outside dev/test")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
