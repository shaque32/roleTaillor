import pytest
from pydantic import ValidationError

from roletailor.config import Settings

LONG_KEY = "x" * 40
GOOD = {
    "environment": "prod",
    "secret_key": LONG_KEY,
    "proxy_shared_secret": "p" * 40,
    "storage_backend": "s3",
    "llm_mode": "live",
    "database_url": "postgresql+psycopg://rt_app:a-real-password@db.internal:5432/roletailor",
    "api_base_url": "https://api.roletailor.example",
    "app_base_url": "https://app.roletailor.example",
    "cors_origins": ["https://app.roletailor.example"],
    "email_provider": "resend",
    "RESEND_API_KEY": "re_live_key",
    "email_from": "RoleTailor <no-reply@mail.roletailor.test>",
}


def make(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def test_dev_defaults_pass():
    make(environment="dev")


def test_full_production_config_passes():
    make(**GOOD)
    make(**{**GOOD, "environment": "staging", "llm_mode": "fake"})
    make(**{**GOOD, "environment": "staging", "email_provider": "console"})


def test_unknown_email_provider_fails_everywhere():
    with pytest.raises(ValidationError, match="RT_EMAIL_PROVIDER must be one of"):
        make(environment="dev", email_provider="smtp")


def test_unknown_environment_fails():
    with pytest.raises(ValidationError, match="RT_ENVIRONMENT"):
        make(environment="production")


@pytest.mark.parametrize(("override", "message"), [
    ({"secret_key": "dev-insecure-secret-change-me"}, "RT_SECRET_KEY"),
    ({"secret_key": "short"}, "RT_SECRET_KEY"),
    ({"storage_backend": "local"}, "RT_STORAGE_BACKEND"),
    ({"proxy_shared_secret": ""}, "RT_PROXY_SHARED_SECRET"),
    ({"database_url": "postgresql+psycopg://rt_app:rt_app@db:5432/roletailor"}, "development password"),
    ({"llm_mode": "fake"}, "RT_LLM_MODE"),
    ({"email_provider": "console"}, "RT_EMAIL_PROVIDER must be 'resend' in prod"),
    ({"email_provider": "memory"}, "tests only"),
    ({"RESEND_API_KEY": ""}, "RESEND_API_KEY must be set"),
    ({"email_from": "RoleTailor <no-reply@roletailor.example>"}, "RT_EMAIL_FROM"),
    ({"api_base_url": "http://localhost:8000"}, "RT_API_BASE_URL"),
    ({"app_base_url": "http://app.roletailor.example"}, "RT_APP_BASE_URL"),
    ({"cors_origins": ["http://localhost:3000"]}, "RT_CORS_ORIGINS"),
    ({"cors_origins": ["*"]}, "RT_CORS_ORIGINS"),
])
def test_unsafe_production_values_fail(override, message):
    with pytest.raises(ValidationError, match=message):
        make(**{**GOOD, **override})


def test_staging_is_guarded_too():
    with pytest.raises(ValidationError, match="RT_STORAGE_BACKEND"):
        make(**{**GOOD, "environment": "staging", "storage_backend": "local"})
