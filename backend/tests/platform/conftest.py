"""Platform test fixtures.

A fresh `roletailor_test_<random>` database is created from db/migrations by the
schema owner (RT_MIGRATION_DATABASE_URL, which needs CREATEDB; pgvector must be
installable or present in template1), tests connect as the RLS-bound rt_app role,
and the database is dropped afterwards.
"""

from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import os
import secrets
import time
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest

os.environ.update({
    "RT_CELERY_TASK_ALWAYS_EAGER": "true",
    "RT_LLM_MODE": "fake",
    "RT_ENVIRONMENT": "test",
    "RT_RATE_LIMIT_AUTH_PER_MINUTE": "1000",
    "RT_RATE_LIMIT_GENERATION_PER_MINUTE": "1000",
    **{f"RT_{name}": "100000" for name in (
        "RATE_LIMIT_LOGIN_PER_HOUR", "RATE_LIMIT_REGISTER_PER_DAY", "RATE_LIMIT_UPLOAD_PER_MINUTE",
        "RATE_LIMIT_JOB_PER_MINUTE", "RATE_LIMIT_EXPORT_PER_MINUTE", "RATE_LIMIT_BILLING_PER_MINUTE",
        "RATE_LIMIT_ACCOUNT_PER_MINUTE", "GENERATION_RUNS_PER_ORG_PER_DAY",
    )},
    "RT_STRIPE_WEBHOOK_SECRET": "whsec_test_secret",
    "RT_STRIPE_SECRET_KEY": "sk_test_dummy",
    "RT_STRIPE_SUBSCRIPTION_PRICE_ID": "price_sub_test",
    "RT_LOG_LEVEL": "WARNING",
    "RT_EMAIL_PROVIDER": "memory",
    # Most tests are not about verification; test_email_auth.py turns the gate back on.
    "RT_REQUIRE_VERIFIED_EMAIL": "false",
    **{f"RT_{name}": "100000" for name in (
        "RATE_LIMIT_PASSWORD_RESET_PER_HOUR", "RATE_LIMIT_VERIFICATION_EMAIL_PER_HOUR",
    )},
})

REPO_ROOT = Path(__file__).resolve().parents[3]
WEBHOOK_SECRET = os.environ["RT_STRIPE_WEBHOOK_SECRET"]


def _load_migrator():
    spec = importlib.util.spec_from_file_location("rt_migrate", REPO_ROOT / "db" / "migrate.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _with_db(url: str, name: str) -> str:
    parts = urlsplit(url.replace("postgresql+psycopg://", "postgresql://", 1))
    return urlunsplit(parts._replace(path=f"/{name}"))


@pytest.fixture(scope="session")
def database(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    from roletailor import db, storage
    from roletailor.config import get_settings

    owner_url = os.environ.get("RT_MIGRATION_DATABASE_URL", get_settings().migration_database_url)
    app_url = os.environ.get("RT_TEST_APP_DATABASE_URL", "postgresql://rt_app:rt_app@localhost:5432/postgres")
    name = f"roletailor_test_{secrets.token_hex(4)}"
    admin = _with_db(owner_url, "postgres")
    try:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(f'CREATE DATABASE "{name}"')
    except psycopg.OperationalError as exc:
        pytest.skip(f"PostgreSQL is not available for platform tests: {exc}")
    try:
        _load_migrator().apply_migrations(_with_db(owner_url, name))
        os.environ["RT_DATABASE_URL"] = _with_db(app_url, name).replace("postgresql://", "postgresql+psycopg://", 1)
        os.environ["RT_STORAGE_LOCAL_DIR"] = str(tmp_path_factory.mktemp("files"))
        get_settings.cache_clear()
        storage.get_storage.cache_clear()
        db.reset_engine()
        yield name
    finally:
        db.reset_engine()
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture(scope="session")
def app(database: str):
    from roletailor.api.ratelimit import RateLimiter
    from roletailor.config import get_settings
    from roletailor.main import create_app

    application = create_app()
    application.state.limiter = RateLimiter(get_settings().redis_url, prefix=f"rl-test-{secrets.token_hex(4)}")
    return application


@pytest.fixture()
def client(app):
    from fastapi.testclient import TestClient

    with TestClient(app) as test_client:
        yield test_client


class User:
    def __init__(self, client, body: dict):
        self.client = client
        self.token = body["token"]
        self.id = body["user"]["id"]
        self.org_id = body["organization"]["id"]
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def get(self, path, **kw):
        return self.client.get(path, headers=self.headers, **kw)

    def post(self, path, **kw):
        return self.client.post(path, headers={**self.headers, **kw.pop("headers", {})}, **kw)

    def patch(self, path, **kw):
        return self.client.patch(path, headers=self.headers, **kw)

    def delete(self, path, **kw):
        return self.client.delete(path, headers=self.headers, **kw)

    def consent(self) -> None:
        r = self.post("/v1/consents", json={"purpose": "ai_processing", "policy_version": "2026-11", "granted": True})
        assert r.status_code == 201, r.text


@pytest.fixture()
def make_user(client):
    def _make(consent: bool = True) -> User:
        email = f"user-{secrets.token_hex(6)}@example.com"
        r = client.post("/v1/auth/register",
                        json={"email": email, "password": "correct horse battery", "full_name": "Ada Lovelace"})
        assert r.status_code == 201, r.text
        user = User(client, r.json())
        user.email = email
        if consent:
            user.consent()
        return user

    return _make


@pytest.fixture(scope="session")
def classic_docx() -> bytes:
    from tests.fixtures.make_fixtures import make_classic_resume

    return make_classic_resume()


def upload_resume(user: User, data: bytes, filename: str = "resume.docx") -> dict:
    r = user.post("/v1/resumes", files={"file": (filename, data, "application/octet-stream")},
                  data={"name": "My resume"})
    assert r.status_code == 201, r.text
    return r.json()


JOB_TEXT = (
    "Senior Data Engineer at Contoso. You will build streaming pipelines with Kafka and Spark, "
    "own Airflow orchestration, model data in dbt, and partner with ML teams on feature stores. "
    "Requirements: 5+ years of Python and SQL, experience with Delta Lake, data quality tooling "
    "such as Great Expectations, and mentoring engineers. Nice to have: Kubernetes, Terraform."
)


def create_job(user: User) -> dict:
    r = user.post("/v1/jobs", json={"description": JOB_TEXT, "title": "Senior Data Engineer", "company": "Contoso"})
    assert r.status_code == 201, r.text
    return r.json()


def signed_webhook(payload: dict) -> tuple[bytes, dict]:
    body = json.dumps(payload).encode()
    ts = int(time.time())
    sig = hmac.new(WEBHOOK_SECRET.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return body, {"Stripe-Signature": f"t={ts},v1={sig}", "Content-Type": "application/json"}


def stripe_event(event_type: str, obj: dict) -> dict:
    return {"id": f"evt_{secrets.token_hex(8)}", "object": "event", "type": event_type,
            "data": {"object": obj}}
