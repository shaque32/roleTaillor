"""Generation quota, charging and Stripe checkout.

Charging rules (see usage_tracking in db/migrations/001):
  * A workflow is charged once, after its first successful generation. Iterations and
    failed generations are never charged.
  * Allocation is serialized per organization by locking its organizations row.
  * Order: free quota, then an active subscription, then a pay-per-use credit (an
    unconsumed succeeded payment), which also requires the user to have accepted paid
    usage on the workflow.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

import stripe
from sqlalchemy import Connection, text

from roletailor import db
from roletailor.config import get_settings
from roletailor.services import audit
from roletailor.services.auth import Principal
from roletailor.services.errors import AppError
from roletailor.services.sql import fetch_one

SUBSCRIPTION_AMOUNT_MINOR = 999  # USD 9.99 / month, display only; Stripe price is canonical
ChargeType = Literal["free", "subscription", "pay_per_use"]

_FREE_USED_SQL = (
    "SELECT count(*) FROM usage_tracking WHERE charge_type = 'free' AND reversed_at IS NULL"
)
_ACTIVE_SUBSCRIPTION_SQL = (
    "SELECT id, stripe_subscription_id, status, current_period_end, cancel_at_period_end"
    " FROM subscriptions WHERE status IN ('active', 'trialing') AND current_period_end > now()"
    " ORDER BY current_period_end DESC LIMIT 1"
)
_UNCONSUMED_PAYMENTS_SQL = (
    " FROM payments p WHERE p.status = 'succeeded' AND p.subscription_id IS NULL"
    " AND p.refunded_minor = 0"
    " AND NOT EXISTS (SELECT 1 FROM usage_tracking u WHERE u.payment_id = p.id)"
)


@dataclass(frozen=True)
class Charge:
    charge_type: ChargeType
    payment_id: UUID | None = None


@dataclass(frozen=True)
class Quota:
    free_used: int
    free_limit: int
    subscription: dict | None
    pay_per_use_credits: int

    def plan(self, paid_usage_accepted: bool) -> Charge | None:
        """What the next initial generation would be charged as, if anything."""
        if self.free_used < self.free_limit:
            return Charge("free")
        if self.subscription is not None:
            return Charge("subscription")
        if self.pay_per_use_credits > 0 and paid_usage_accepted:
            return Charge("pay_per_use")
        return None


def quota(conn: Connection, *, lock: bool = False) -> Quota:
    org = fetch_one(
        conn,
        "SELECT free_generation_limit FROM organizations"
        " WHERE id = roletailor.current_organization_id()" + (" FOR UPDATE" if lock else ""),
    )
    assert org is not None, "tenant context is not set"
    return Quota(
        free_used=conn.execute(text(_FREE_USED_SQL)).scalar_one(),
        free_limit=org["free_generation_limit"],
        subscription=fetch_one(conn, _ACTIVE_SUBSCRIPTION_SQL),
        pay_per_use_credits=conn.execute(
            text("SELECT count(*)" + _UNCONSUMED_PAYMENTS_SQL)
        ).scalar_one(),
    )


@dataclass(frozen=True)
class PlanLimits:
    plan: str
    runs_per_day: int
    iterations: int


def plan_limits(conn: Connection | None) -> PlanLimits:
    """Spend ceilings for the current organization's plan: "subscription" while a
    subscription is active, otherwise "free" (pay-per-use buyers included).
    Pass None to get the free plan's limits without a query."""
    settings = get_settings()
    plan = "free"
    # Without overrides every plan has the same limits, so skip the lookup.
    if conn is not None and settings.plan_limits and fetch_one(conn, _ACTIVE_SUBSCRIPTION_SQL):
        plan = "subscription"
    runs, iterations = settings.limits_for_plan(plan)
    return PlanLimits(plan, runs, iterations)


def payment_required(q: Quota) -> AppError:
    settings = get_settings()
    needs_acceptance = q.pay_per_use_credits > 0
    message = (
        "Using a pay-per-use credit costs $0.50. Confirm to continue."
        if needs_acceptance
        else "You have used your free generations. Subscribe or buy a single generation."
    )
    return AppError(402, "payment_required", message, {
        "free_used": q.free_used,
        "free_limit": q.free_limit,
        "pay_per_use_credits": q.pay_per_use_credits,
        "requires_paid_usage_acceptance": needs_acceptance,
        "options": [
            {"mode": "subscription", "amount_minor": SUBSCRIPTION_AMOUNT_MINOR,
             "currency": "USD", "interval": "month"},
            {"mode": "pay_per_use", "amount_minor": settings.pay_per_use_amount_minor,
             "currency": "USD"},
        ],
    })


def ensure_can_start(conn: Connection, *, paid_usage_accepted: bool) -> Charge:
    """Pre-check at workflow creation; raises 402 before anything paid is consumed."""
    q = quota(conn)
    charge = q.plan(paid_usage_accepted)
    if charge is None:
        raise payment_required(q)
    return charge


def charge_initial_generation(conn: Connection, workflow: dict) -> Charge:
    """Record the charge for a workflow's first successful generation.

    Idempotent per workflow. Raises 402 when nothing can pay for it (the caller rolls
    the generation back so nothing is persisted or charged)."""
    q = quota(conn, lock=True)
    existing = fetch_one(
        conn,
        "SELECT charge_type, payment_id FROM usage_tracking WHERE workflow_id = :wf",
        {"wf": workflow["id"]},
    )
    if existing is not None:
        return Charge(existing["charge_type"], existing["payment_id"])
    charge = q.plan(workflow["paid_usage_accepted_at"] is not None)
    if charge is None:
        raise payment_required(q)
    if charge.charge_type == "pay_per_use":
        payment = fetch_one(
            conn, "SELECT p.id" + _UNCONSUMED_PAYMENTS_SQL + " ORDER BY p.created_at LIMIT 1"
        )
        assert payment is not None
        charge = Charge("pay_per_use", payment["id"])
    conn.execute(
        text(
            "INSERT INTO usage_tracking (organization_id, workflow_id, payment_id, charge_type)"
            " VALUES (roletailor.current_organization_id(), :wf, :pay, :type)"
        ),
        {"wf": workflow["id"], "pay": charge.payment_id, "type": charge.charge_type},
    )
    return charge


def reverse_usage(conn: Connection, *, workflow_id: UUID | None = None,
                  payment_id: UUID | None = None) -> int:
    """Mark usage as reversed (refunds, support credits). Returns rows reversed."""
    if (workflow_id is None) == (payment_id is None):
        raise ValueError("pass exactly one of workflow_id or payment_id")
    column, value = ("workflow_id", workflow_id) if workflow_id else ("payment_id", payment_id)
    return conn.execute(
        text(
            f"UPDATE usage_tracking SET reversed_at = now() WHERE {column} = :v"
            " AND reversed_at IS NULL"
        ),
        {"v": value},
    ).rowcount


def status(principal: Principal) -> dict:
    with db.tenant_tx(principal.org_id) as conn:
        q = quota(conn)
        latest = q.subscription or fetch_one(
            conn,
            "SELECT id, stripe_subscription_id, status, current_period_end, cancel_at_period_end"
            " FROM subscriptions ORDER BY created_at DESC LIMIT 1",
        )
    return {
        "free_used": q.free_used,
        "free_limit": q.free_limit,
        "subscription": latest,
        "pay_per_use_credits": q.pay_per_use_credits,
    }


# --------------------------------------------------------------------------
# Stripe checkout
# --------------------------------------------------------------------------


def stripe_client() -> stripe.StripeClient:
    key = get_settings().stripe_secret_key
    if not key:
        raise AppError(503, "billing_unavailable", "Billing is not configured.")
    return stripe.StripeClient(key)


def _customer_id(client: stripe.StripeClient, conn: Connection, principal: Principal) -> str:
    org = fetch_one(
        conn, "SELECT id, name, stripe_customer_id FROM organizations WHERE id = :id FOR UPDATE",
        {"id": principal.org_id},
    )
    assert org is not None
    if org["stripe_customer_id"]:
        return org["stripe_customer_id"]
    customer = client.v1.customers.create(params={
        "name": org["name"], "metadata": {"organization_id": str(principal.org_id)},
    }, options={"idempotency_key": f"customer-{principal.org_id}"})
    conn.execute(
        text("UPDATE organizations SET stripe_customer_id = :c WHERE id = :id"),
        {"c": customer.id, "id": principal.org_id},
    )
    return customer.id


def create_checkout(principal: Principal, mode: Literal["subscription", "pay_per_use"]) -> str:
    settings = get_settings()
    client = stripe_client()
    metadata = {"organization_id": str(principal.org_id), "mode": mode}
    if mode == "subscription":
        if not settings.stripe_subscription_price_id:
            raise AppError(503, "billing_unavailable", "Subscriptions are not configured.")
        line_item: dict = {"price": settings.stripe_subscription_price_id, "quantity": 1}
    elif settings.stripe_pay_per_use_price_id:
        line_item = {"price": settings.stripe_pay_per_use_price_id, "quantity": 1}
    else:
        line_item = {"quantity": 1, "price_data": {
            "currency": "usd", "unit_amount": settings.pay_per_use_amount_minor,
            "product_data": {"name": "RoleTailor single tailored resume"},
        }}
    with db.tenant_tx(principal.org_id) as conn:
        if mode == "subscription" and fetch_one(
            conn, "SELECT 1 AS x FROM subscriptions WHERE status IN ('active', 'trialing', 'past_due') LIMIT 1"
        ):
            raise AppError(409, "already_subscribed",
                           "You already have a subscription. Manage it in the billing portal.")
        params: dict = {
            "mode": "subscription" if mode == "subscription" else "payment",
            "customer": _customer_id(client, conn, principal),
            "client_reference_id": str(principal.org_id),
            "line_items": [line_item],
            "metadata": metadata,
            "success_url": (
                f"{settings.app_base_url}/settings?checkout=success"
                "&session_id={CHECKOUT_SESSION_ID}#billing"
            ),
            "cancel_url": f"{settings.app_base_url}/settings?checkout=cancelled#billing",
        }
        if mode == "subscription":
            params["allow_promotion_codes"] = True
            params["subscription_data"] = {"metadata": metadata}
        else:
            params["payment_intent_data"] = {"metadata": metadata}
        session = client.v1.checkout.sessions.create(params=params)
        audit.record(
            conn, org_id=principal.org_id, action="billing.checkout_started",
            resource_type="organization", resource_id=principal.org_id,
            actor_user_id=principal.user_id, metadata={"mode": mode, "session_id": session.id},
        )
    return session.url


def create_portal_session(principal: Principal) -> str:
    """Stripe customer portal URL (cancel, payment method, invoices)."""
    client = stripe_client()
    with db.tenant_tx(principal.org_id) as conn:
        org = fetch_one(conn, "SELECT stripe_customer_id FROM organizations WHERE id = :id",
                        {"id": principal.org_id})
        if org is None or not org["stripe_customer_id"]:
            raise AppError(409, "no_billing_account", "Start a subscription or purchase first.")
        session = client.v1.billing_portal.sessions.create(params={
            "customer": org["stripe_customer_id"],
            "return_url": f"{get_settings().app_base_url}/settings#billing",
        })
        audit.record(
            conn, org_id=principal.org_id, action="billing.portal_opened",
            resource_type="organization", resource_id=principal.org_id,
            actor_user_id=principal.user_id,
        )
    return session.url
