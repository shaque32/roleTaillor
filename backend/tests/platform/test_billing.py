from __future__ import annotations

import time
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from roletailor import db
from tests.platform.conftest import create_job, signed_webhook, stripe_event, upload_resume
from tests.platform.test_workflows import count, start


@pytest.fixture()
def exhausted_user(make_user, classic_docx, monkeypatch):
    from roletailor.ai import gateway as gateway_module
    from roletailor.pipeline import orchestrator
    from tests.platform import stubs

    monkeypatch.setattr(orchestrator, "tailor", stubs.stub_tailor)
    monkeypatch.setattr(gateway_module, "build_gateway", stubs.stub_build_gateway)
    user = make_user()
    with db.tenant_tx(user.org_id) as conn:
        conn.execute(text("UPDATE organizations SET free_generation_limit = 0"))
        conn.execute(text("UPDATE organizations SET stripe_customer_id = :c"), {"c": f"cus_{uuid.uuid4().hex[:10]}"})
        user.customer = conn.execute(text("SELECT stripe_customer_id FROM organizations")).scalar_one()
    user.version_id = upload_resume(user, classic_docx)["version"]["id"]
    user.job_id = create_job(user)["id"]
    return user


def send(client, event: dict):
    body, headers = signed_webhook(event)
    return client.post("/v1/billing/webhook", content=body, headers=headers)


def test_free_quota_then_payment_required(make_user, classic_docx, monkeypatch, exhausted_user):
    r = start(exhausted_user, exhausted_user.version_id, exhausted_user.job_id)
    assert r.status_code == 402
    error = r.json()["error"]
    assert error["code"] == "payment_required"
    assert {o["mode"] for o in error["details"]["options"]} == {"subscription", "pay_per_use"}
    status = exhausted_user.get("/v1/billing/status").json()
    assert status == {"free_used": 0, "free_limit": 0, "subscription": None, "pay_per_use_credits": 0}


def test_pay_per_use_flow_and_refund(client, exhausted_user):
    user = exhausted_user
    completed = stripe_event("checkout.session.completed", {
        "id": "cs_test_1", "mode": "payment", "payment_status": "paid", "payment_intent": f"pi_{uuid.uuid4().hex}",
        "amount_total": 50, "currency": "usd", "customer": user.customer, "client_reference_id": user.org_id,
        "metadata": {"organization_id": user.org_id, "mode": "pay_per_use"},
    })
    assert send(client, completed).json() == {"status": "processed"}
    assert send(client, completed).json() == {"status": "duplicate"}
    assert user.get("/v1/billing/status").json()["pay_per_use_credits"] == 1

    warn = start(user, user.version_id, user.job_id)
    assert warn.status_code == 402 and warn.json()["error"]["details"]["requires_paid_usage_acceptance"]

    workflow = start(user, user.version_id, user.job_id, accept_paid_usage=True).json()
    assert workflow["status"] == "completed"
    with db.tenant_tx(user.org_id) as conn:
        usage = conn.execute(text("SELECT charge_type, payment_id FROM usage_tracking WHERE workflow_id = :w"),
                             {"w": workflow["id"]}).one()
    assert usage.charge_type == "pay_per_use" and usage.payment_id is not None
    assert user.get("/v1/billing/status").json()["pay_per_use_credits"] == 0

    refund = stripe_event("charge.refunded", {
        "id": "ch_1", "payment_intent": completed["data"]["object"]["payment_intent"], "amount_refunded": 50,
        "customer": user.customer,
    })
    assert send(client, refund).json() == {"status": "processed"}
    assert count(user.org_id, "SELECT count(*) FROM usage_tracking WHERE reversed_at IS NOT NULL") == 1
    assert count(user.org_id, "SELECT count(*) FROM payments WHERE status = 'refunded' AND refunded_minor = 50") == 1


def test_subscription_lifecycle(client, exhausted_user):
    user = exhausted_user
    sub = {"id": f"sub_{uuid.uuid4().hex[:10]}", "customer": user.customer, "status": "active",
           "cancel_at_period_end": False,
           "items": {"data": [{"price": {"id": "price_sub_test"}, "current_period_end": int(time.time()) + 86400}]}}
    assert send(client, stripe_event("customer.subscription.created", sub)).json()["status"] == "processed"
    assert user.get("/v1/billing/status").json()["subscription"]["status"] == "active"

    workflow = start(user, user.version_id, user.job_id).json()
    assert workflow["status"] == "completed"
    assert count(user.org_id, "SELECT count(*) FROM usage_tracking WHERE charge_type = 'subscription'") == 1

    invoice = {"id": "in_1", "customer": user.customer, "subscription": sub["id"],
               "hosted_invoice_url": "https://pay.example/in_1"}
    assert send(client, stripe_event("invoice.payment_failed", invoice)).json()["status"] == "processed"
    assert user.get("/v1/billing/status").json()["subscription"]["status"] == "past_due"
    notes = user.get("/v1/notifications").json()
    assert notes[0]["kind"] == "billing.payment_failed"
    assert user.post(f"/v1/notifications/{notes[0]['id']}/read").json()["read_at"]
    assert start(user, user.version_id, user.job_id).status_code == 402


def test_webhook_rejects_bad_signature(client):
    body, headers = signed_webhook(stripe_event("charge.refunded", {}))
    headers["Stripe-Signature"] = headers["Stripe-Signature"][:-4] + "0000"
    r = client.post("/v1/billing/webhook", content=body, headers=headers)
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_signature"


def test_checkout_session(make_user, monkeypatch):
    created = {}

    class FakeClient:
        def __init__(self, key):
            self.v1 = SimpleNamespace(
                customers=SimpleNamespace(create=lambda params: SimpleNamespace(id="cus_new")),
                checkout=SimpleNamespace(sessions=SimpleNamespace(create=self._session)),
            )

        @staticmethod
        def _session(params):
            created.update(params)
            return SimpleNamespace(id="cs_1", url="https://checkout.stripe.test/cs_1")

    monkeypatch.setattr("roletailor.services.billing.stripe.StripeClient", FakeClient)
    user = make_user()
    r = user.post("/v1/billing/checkout", json={"mode": "subscription"})
    assert r.json() == {"checkout_url": "https://checkout.stripe.test/cs_1"}
    assert created["customer"] == "cus_new" and created["line_items"][0]["price"] == "price_sub_test"
    r = user.post("/v1/billing/checkout", json={"mode": "pay_per_use"})
    assert created["mode"] == "payment" and created["line_items"][0]["price_data"]["unit_amount"] == 50
