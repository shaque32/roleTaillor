from __future__ import annotations

import json
import logging

import pytest

from roletailor.logging_setup import JsonFormatter
from roletailor.redaction import MASK, redact

FAKE_ANTHROPIC = "sk-ant-" + "api03-" + "A1b2C3d4E5f6G7h8"
FAKE_STRIPE = "sk_" + "live_" + "A1b2C3d4E5f6G7h8"


def test_masks_values_of_secret_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "plain-looking-value-123")
    monkeypatch.setenv("RT_STRIPE_WEBHOOK_SECRET", "another-opaque-value")
    out = redact("auth failed for plain-looking-value-123 and another-opaque-value")
    assert out == f"auth failed for {MASK} and {MASK}"


def test_masks_key_shapes_that_are_not_in_the_environment() -> None:
    out = redact(f"Authorization: Bearer {FAKE_ANTHROPIC}; stripe={FAKE_STRIPE}")
    assert FAKE_ANTHROPIC not in out and FAKE_STRIPE not in out
    assert out.count(MASK) == 2


def test_masks_database_url_passwords() -> None:
    out = redact("connect postgresql+psycopg://rt_app:hunter2hunter2@db.internal:5432/roletailor failed")
    assert "hunter2hunter2" not in out
    assert "rt_app:" in out and "@db.internal" in out


def test_leaves_ordinary_text_and_short_placeholders_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOME_API_KEY", "x")
    text = "Reduced churn 12% across 3 regions; see https://example.com/a:b"
    assert redact(text) == text


def test_log_lines_are_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_ANTHROPIC)
    record = logging.makeLogRecord({"msg": "provider error: key %s rejected", "args": (FAKE_ANTHROPIC,),
                                    "levelname": "ERROR", "name": "t", "detail": FAKE_STRIPE})
    line = JsonFormatter().format(record)
    assert FAKE_ANTHROPIC not in line and FAKE_STRIPE not in line
    assert json.loads(line)["message"] == f"provider error: key {MASK} rejected"
