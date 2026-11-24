from __future__ import annotations

from functools import lru_cache
from pathlib import Path

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
