"""Stripe webhook processing: signature check, idempotency, and event handlers.

Each event id is recorded in stripe_webhook_events; an event already processed is
acknowledged without side effects. Handlers are also idempotent (upserts keyed by
Stripe ids), so an event that failed half-way can be safely redelivered.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import stripe
from sqlalchemy import Connection, text

from roletailor import db
from roletailor.config import get_settings
from roletailor.services import audit, billing, notifications
from roletailor.services.errors import AppError
from roletailor.services.sql import fetch_one

log = logging.getLogger(__name__)
Obj = dict[str, Any]


def verify(payload: bytes, signature: str | None) -> Obj:
    secret = get_settings().stripe_webhook_secret
    if not secret:
        raise AppError(503, "billing_unavailable", "Billing is not configured.")
    try:
        event = stripe.Webhook.construct_event(payload, signature or "", secret)
    except (ValueError, stripe.SignatureVerificationError) as exc:
        raise AppError(400, "invalid_signature", "Webhook signature verification failed.") from exc
    return event.to_dict()


def _timestamp(value: int | None) -> datetime | None:
    return datetime.fromtimestamp(value, UTC) if value else None


def _organization_id(conn: Connection, obj: Obj) -> UUID | None:
    metadata = obj.get("metadata") or {}
    if org := metadata.get("organization_id") or obj.get("client_reference_id"):
        return UUID(org)
    customer = obj.get("customer")
    if isinstance(customer, dict):
        customer = customer.get("id")
    if not customer:
        return None
    row = fetch_one(conn, "SELECT roletailor.organization_for_stripe_customer(:c) AS id", {"c": customer})
    return row["id"] if row else None


# --------------------------------------------------------------------------
# Handlers. Each runs inside a transaction already scoped to the organization.
# --------------------------------------------------------------------------


def _checkout_completed(conn: Connection, org_id: UUID, obj: Obj) -> None:
    if obj.get("customer"):
        conn.execute(
            text("UPDATE organizations SET stripe_customer_id = coalesce(stripe_customer_id, :c) WHERE id = :id"),
            {"c": obj["customer"], "id": org_id},
        )
    if obj.get("mode") == "payment" and obj.get("payment_intent"):
        conn.execute(
            text(
                "INSERT INTO payments (organization_id, stripe_payment_intent_id, status, currency, amount_minor)"
                " VALUES (:org, :pi, :status, :cur, :amount)"
                " ON CONFLICT (stripe_payment_intent_id) DO UPDATE SET status = EXCLUDED.status"
            ),
            {
                "org": org_id, "pi": obj["payment_intent"],
                "status": "succeeded" if obj.get("payment_status") == "paid" else "pending",
                "cur": (obj.get("currency") or "usd").upper(), "amount": obj.get("amount_total") or 0,
            },
        )
    audit.record(conn, org_id=org_id, action="billing.checkout_completed", resource_type="organization",
                 resource_id=org_id, metadata={"session_id": obj.get("id"), "mode": obj.get("mode")})


def _subscription_changed(conn: Connection, org_id: UUID, obj: Obj) -> None:
    items = (obj.get("items") or {}).get("data") or [{}]
    first = items[0]
    period_end = obj.get("current_period_end") or first.get("current_period_end")
    conn.execute(
        text(
            "INSERT INTO subscriptions (organization_id, stripe_subscription_id, stripe_price_id, status,"
            " current_period_end, cancel_at_period_end)"
            " VALUES (:org, :sid, :price, :status, :end, :cancel)"
            " ON CONFLICT (stripe_subscription_id) DO UPDATE SET stripe_price_id = EXCLUDED.stripe_price_id,"
            " status = EXCLUDED.status, current_period_end = EXCLUDED.current_period_end,"
            " cancel_at_period_end = EXCLUDED.cancel_at_period_end"
        ),
        {
            "org": org_id, "sid": obj["id"], "price": (first.get("price") or {}).get("id") or "unknown",
            "status": obj.get("status") or "incomplete", "end": _timestamp(period_end),
            "cancel": bool(obj.get("cancel_at_period_end")),
        },
    )
    audit.record(conn, org_id=org_id, action="billing.subscription_updated", resource_type="subscription",
                 metadata={"stripe_subscription_id": obj["id"], "status": obj.get("status")})


def _invoice_subscription_id(obj: Obj) -> str | None:
    legacy = obj.get("subscription")
    if isinstance(legacy, str):
        return legacy
    details = ((obj.get("parent") or {}).get("subscription_details") or {})
    return details.get("subscription")


def _invoice_payment_failed(conn: Connection, org_id: UUID, obj: Obj) -> None:
    if subscription_id := _invoice_subscription_id(obj):
        conn.execute(
            text("UPDATE subscriptions SET status = 'past_due' WHERE stripe_subscription_id = :sid"),
            {"sid": subscription_id},
        )
    notifications.notify_admins(conn, "billing.payment_failed", {
        "message": "Your subscription payment failed. Update your payment method to keep generating.",
        "invoice_url": obj.get("hosted_invoice_url"),
    })
    audit.record(conn, org_id=org_id, action="billing.payment_failed", resource_type="subscription",
                 metadata={"invoice_id": obj.get("id"), "stripe_subscription_id": subscription_id})


def _charge_refunded(conn: Connection, org_id: UUID, obj: Obj) -> None:
    payment = fetch_one(
        conn,
        "UPDATE payments SET refunded_minor = least(:refunded, amount_minor),"
        " status = CASE WHEN :refunded >= amount_minor THEN 'refunded' ELSE status END"
        " WHERE stripe_payment_intent_id = :pi RETURNING id",
        {"refunded": obj.get("amount_refunded") or 0, "pi": obj.get("payment_intent")},
    )
    if payment is None:
        log.warning("refund for unknown payment", extra={"payment_intent": obj.get("payment_intent")})
        return
    reversed_rows = billing.reverse_usage(conn, payment_id=payment["id"])
    audit.record(conn, org_id=org_id, action="billing.refunded", resource_type="payment",
                 resource_id=payment["id"], metadata={"usage_reversed": reversed_rows})


HANDLERS: dict[str, Callable[[Connection, UUID, Obj], None]] = {
    "checkout.session.completed": _checkout_completed,
    "customer.subscription.created": _subscription_changed,
    "customer.subscription.updated": _subscription_changed,
    "customer.subscription.deleted": _subscription_changed,
    "invoice.payment_failed": _invoice_payment_failed,
    "charge.refunded": _charge_refunded,
}


def process(event: Obj) -> str:
    """Apply one verified event. Returns processed, duplicate or ignored."""
    event_id, event_type = event["id"], event["type"]
    with db.global_tx() as conn:
        row = fetch_one(
            conn,
            "INSERT INTO stripe_webhook_events (event_id, event_type) VALUES (:id, :type)"
            " ON CONFLICT (event_id) DO UPDATE SET event_type = EXCLUDED.event_type"
            " RETURNING processed_at",
            {"id": event_id, "type": event_type},
        )
        if row and row["processed_at"] is not None:
            return "duplicate"
        handler = HANDLERS.get(event_type)
        outcome = "ignored"
        if handler is not None:
            obj = event["data"]["object"]
            org_id = _organization_id(conn, obj)
            if org_id is None:
                log.warning("stripe event without a known organization",
                            extra={"event_id": event_id, "event_type": event_type})
            else:
                db.set_tenant(conn, org_id)
                handler(conn, org_id, obj)
                outcome = "processed"
        conn.execute(
            text("UPDATE stripe_webhook_events SET processed_at = now() WHERE event_id = :id"),
            {"id": event_id},
        )
    return outcome
