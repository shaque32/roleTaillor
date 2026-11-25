from __future__ import annotations

import time
import uuid
from concurrent.futures import ThreadPoolExecutor
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
                customers=SimpleNamespace(create=lambda params, options=None: SimpleNamespace(id="cus_new")),
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


# --------------------------------------------------------------------------
# Checkout hardening, portal, async payments and webhook robustness
# --------------------------------------------------------------------------


class RecordingStripe:
    """Installable fake for stripe.StripeClient recording what the service sends."""

    def __init__(self, monkeypatch):
        self.sessions, self.portals, self.customers = [], [], []
        outer = self

        class FakeClient:
            def __init__(self, key):
                def customer(params, options=None):
                    outer.customers.append((params, options))
                    return SimpleNamespace(id=f"cus_{uuid.uuid4().hex[:12]}")

                def session(params):
                    outer.sessions.append(params)
                    return SimpleNamespace(id="cs_1", url="https://checkout.stripe.test/cs_1")

                def portal(params):
                    outer.portals.append(params)
                    return SimpleNamespace(url="https://portal.stripe.test/p_1")

                self.v1 = SimpleNamespace(
                    customers=SimpleNamespace(create=customer),
                    checkout=SimpleNamespace(sessions=SimpleNamespace(create=session)),
                    billing_portal=SimpleNamespace(sessions=SimpleNamespace(create=portal)),
                )

        monkeypatch.setattr("roletailor.services.billing.stripe.StripeClient", FakeClient)


def sub_payload(user, status="active", sid=None):
    return {"id": sid or f"sub_{uuid.uuid4().hex[:10]}", "customer": user.customer, "status": status,
            "cancel_at_period_end": False,
            "items": {"data": [{"price": {"id": "price_sub_test"}, "current_period_end": int(time.time()) + 86400}]}}


def test_checkout_urls_and_customer_idempotency_key(make_user, monkeypatch):
    fake = RecordingStripe(monkeypatch)
    user = make_user()
    r = user.post("/v1/billing/checkout", json={"mode": "subscription"})
    assert r.status_code == 200, r.text
    params, options = fake.customers[0]
    assert options == {"idempotency_key": f"customer-{user.org_id}"}
    session = fake.sessions[0]
    assert session["success_url"].endswith("/settings?checkout=success&session_id={CHECKOUT_SESSION_ID}#billing")
    assert session["cancel_url"].endswith("/settings?checkout=cancelled#billing")


def test_subscription_checkout_refused_when_already_subscribed(client, exhausted_user, monkeypatch):
    fake = RecordingStripe(monkeypatch)
    user = exhausted_user
    send(client, stripe_event("customer.subscription.created", sub_payload(user)))
    r = user.post("/v1/billing/checkout", json={"mode": "subscription"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "already_subscribed"
    assert fake.sessions == []
    assert user.post("/v1/billing/checkout", json={"mode": "pay_per_use"}).status_code == 200


def test_portal_session(exhausted_user, make_user, monkeypatch):
    fake = RecordingStripe(monkeypatch)
    user = exhausted_user
    r = user.post("/v1/billing/portal")
    assert r.json() == {"portal_url": "https://portal.stripe.test/p_1"}
    assert fake.portals[0]["customer"] == user.customer
    assert fake.portals[0]["return_url"].endswith("/settings#billing")
    assert count(user.org_id, "SELECT count(*) FROM audit_logs WHERE action = 'billing.portal_opened'") == 1

    other = make_user()
    r = other.post("/v1/billing/portal")
    assert r.status_code == 409 and r.json()["error"]["code"] == "no_billing_account"


def async_session(user, **extra):
    return {"id": "cs_async", "mode": "payment", "payment_status": "paid",
            "payment_intent": f"pi_{uuid.uuid4().hex}", "amount_total": 50, "currency": "usd",
            "customer": user.customer, "client_reference_id": user.org_id,
            "metadata": {"organization_id": user.org_id}, **extra}


def test_async_payment_succeeded_creates_credit_and_failed_does_not(client, exhausted_user):
    user = exhausted_user
    pending = async_session(user, payment_status="unpaid")
    send(client, stripe_event("checkout.session.completed", pending))
    assert user.get("/v1/billing/status").json()["pay_per_use_credits"] == 0
    assert send(client, stripe_event("checkout.session.async_payment_succeeded",
                                     {**pending, "payment_status": "paid"})).json()["status"] == "processed"
    assert user.get("/v1/billing/status").json()["pay_per_use_credits"] == 1

    failing = async_session(user, payment_status="unpaid")
    send(client, stripe_event("checkout.session.completed", failing))
    send(client, stripe_event("checkout.session.async_payment_failed", failing))
    assert user.get("/v1/billing/status").json()["pay_per_use_credits"] == 1
    assert count(user.org_id, "SELECT count(*) FROM payments WHERE status = 'failed'") == 1
    # A late failure never downgrades a payment that already succeeded.
    send(client, stripe_event("checkout.session.async_payment_failed", {**pending}))
    assert user.get("/v1/billing/status").json()["pay_per_use_credits"] == 1


def _stripe_reports(monkeypatch, subscription: dict) -> None:
    """Stripe's authoritative copy of a subscription, as subscriptions.retrieve returns it."""
    class FakeClient:
        def __init__(self, key):
            retrieve = lambda sid: SimpleNamespace(to_dict=lambda: {**subscription, "id": sid})  # noqa: E731
            self.v1 = SimpleNamespace(subscriptions=SimpleNamespace(retrieve=retrieve))

    monkeypatch.setattr("roletailor.services.billing.stripe.StripeClient", FakeClient)


@pytest.mark.parametrize("stripe_status", ["active", "past_due"])
def test_invoice_paid_follows_stripe_subscription_status(client, exhausted_user, monkeypatch, stripe_status):
    user = exhausted_user
    sub = sub_payload(user)
    send(client, stripe_event("customer.subscription.created", sub))
    invoice = {"id": "in_1", "customer": user.customer, "subscription": sub["id"]}
    send(client, stripe_event("invoice.payment_failed", invoice))
    assert user.get("/v1/billing/status").json()["subscription"]["status"] == "past_due"
    # Paying one invoice only restores access if Stripe says the subscription is current.
    _stripe_reports(monkeypatch, {**sub, "status": stripe_status})
    assert send(client, stripe_event("invoice.paid", invoice)).json()["status"] == "processed"
    assert user.get("/v1/billing/status").json()["subscription"]["status"] == stripe_status


def test_payment_failed_does_not_revive_canceled_subscription(client, exhausted_user):
    user = exhausted_user
    sub = sub_payload(user)
    send(client, stripe_event("customer.subscription.created", sub))
    send(client, stripe_event("customer.subscription.deleted", {**sub, "status": "canceled"}))
    invoice = {"id": "in_late", "customer": user.customer, "subscription": sub["id"]}
    assert send(client, stripe_event("invoice.payment_failed", invoice)).json()["status"] == "processed"
    assert user.get("/v1/billing/status").json()["subscription"]["status"] == "canceled"


def test_refund_before_settlement_grants_no_credit(client, exhausted_user):
    user = exhausted_user
    intent = f"pi_{uuid.uuid4().hex}"
    refund = stripe_event("charge.refunded", {
        "id": "ch_early", "payment_intent": intent, "amount": 50, "amount_refunded": 50, "currency": "usd",
        "customer": user.customer,
    })
    assert send(client, refund).json() == {"status": "processed"}
    settled = stripe_event("checkout.session.async_payment_succeeded", {
        "id": "cs_early", "mode": "payment", "payment_status": "paid", "payment_intent": intent,
        "amount_total": 50, "currency": "usd", "customer": user.customer,
        "metadata": {"organization_id": user.org_id, "mode": "pay_per_use"},
    })
    assert send(client, settled).json() == {"status": "processed"}
    assert user.get("/v1/billing/status").json()["pay_per_use_credits"] == 0
    assert count(user.org_id, "SELECT count(*) FROM payments WHERE status = 'refunded'") == 1


def test_refund_racing_settlement_is_not_lost(client, exhausted_user):
    """A settlement inserts the payment row while the refund is being handled: the
    refund must wait for it and apply, not be dropped by the unique-key conflict."""
    user = exhausted_user
    intent = f"pi_{uuid.uuid4().hex}"
    refund = stripe_event("charge.refunded", {
        "id": "ch_race", "payment_intent": intent, "amount": 50, "amount_refunded": 50, "currency": "usd",
        "customer": user.customer,
    })
    with ThreadPoolExecutor(max_workers=1) as pool:
        with db.tenant_tx(user.org_id) as conn:
            # The settlement's insert, held open (uncommitted) while the refund arrives.
            conn.execute(
                text("INSERT INTO payments (organization_id, stripe_payment_intent_id, status, currency,"
                     " amount_minor) VALUES (:org, :pi, 'succeeded', 'USD', 50)"),
                {"org": user.org_id, "pi": intent},
            )
            holder = conn.execute(text("SELECT pg_backend_pid()")).scalar_one()
            pending = pool.submit(send, client, refund)
            # Commit only once the refund's session is really waiting on this transaction.
            deadline = time.monotonic() + 10
            blocked = 0
            while not blocked and time.monotonic() < deadline:
                with db.global_tx() as probe:
                    blocked = probe.execute(
                        text("SELECT count(*) FROM pg_stat_activity WHERE :pid = ANY(pg_blocking_pids(pid))"),
                        {"pid": holder},
                    ).scalar_one()
                if not blocked:
                    time.sleep(0.05)
            assert blocked == 1 and not pending.done()
        assert pending.result(timeout=10).json() == {"status": "processed"}
    assert user.get("/v1/billing/status").json()["pay_per_use_credits"] == 0
    assert count(user.org_id, "SELECT count(*) FROM payments WHERE stripe_payment_intent_id = :pi"
                 " AND status = 'refunded' AND refunded_minor = 50", pi=intent) == 1


def test_canceled_subscription_not_reverted_by_late_event(client, exhausted_user):
    user = exhausted_user
    sub = sub_payload(user)
    send(client, stripe_event("customer.subscription.created", sub))
    send(client, stripe_event("customer.subscription.deleted", {**sub, "status": "canceled"}))
    send(client, stripe_event("customer.subscription.updated", sub))  # delivered late
    assert user.get("/v1/billing/status").json()["subscription"]["status"] == "canceled"


def test_webhook_rejects_oversized_body(client):
    r = client.post("/v1/billing/webhook", content=b"x" * 1_100_000, headers={"Stripe-Signature": "t=1,v1=00"})
    assert r.status_code == 413 and r.json()["error"]["code"] == "payload_too_large"


def test_failed_handler_rolls_back_and_redelivery_processes(client, exhausted_user, monkeypatch):
    from roletailor.services import stripe_webhooks

    user = exhausted_user
    real = stripe_webhooks.HANDLERS["checkout.session.completed"]
    calls = {"n": 0}

    def flaky(conn, org_id, obj):
        calls["n"] += 1
        if calls["n"] == 1:
            real(conn, org_id, obj)  # partial work must be rolled back too
            raise RuntimeError("boom")
        real(conn, org_id, obj)

    monkeypatch.setitem(stripe_webhooks.HANDLERS, "checkout.session.completed", flaky)
    event = stripe_event("checkout.session.completed", async_session(user))
    body, headers = signed_webhook(event)
    with pytest.raises(RuntimeError):
        client.post("/v1/billing/webhook", content=body, headers=headers)
    assert user.get("/v1/billing/status").json()["pay_per_use_credits"] == 0
    assert send(client, event).json() == {"status": "processed"}
    assert user.get("/v1/billing/status").json()["pay_per_use_credits"] == 1
    assert send(client, event).json() == {"status": "duplicate"}


def test_late_completed_event_does_not_unsettle_payment(client, exhausted_user):
    user = exhausted_user
    session = {"id": "cs_late", "mode": "payment", "payment_intent": f"pi_{uuid.uuid4().hex}",
               "amount_total": 50, "currency": "usd", "customer": user.customer,
               "metadata": {"organization_id": user.org_id, "mode": "pay_per_use"}}
    settled = stripe_event("checkout.session.async_payment_succeeded", {**session, "payment_status": "paid"})
    assert send(client, settled).json() == {"status": "processed"}
    late = stripe_event("checkout.session.completed", {**session, "payment_status": "unpaid"})
    assert send(client, late).json() == {"status": "processed"}
    assert user.get("/v1/billing/status").json()["pay_per_use_credits"] == 1


def test_past_due_subscription_blocks_second_checkout(client, exhausted_user):
    user = exhausted_user
    sub = {"id": f"sub_{uuid.uuid4().hex[:10]}", "customer": user.customer, "status": "past_due",
           "items": {"data": [{"price": {"id": "price_sub_test"}, "current_period_end": int(time.time()) + 86400}]}}
    assert send(client, stripe_event("customer.subscription.updated", sub)).json()["status"] == "processed"
    r = user.post("/v1/billing/checkout", json={"mode": "subscription"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "already_subscribed"
