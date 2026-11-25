from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from starlette.concurrency import run_in_threadpool

from roletailor.api.deps import CurrentPrincipal, rate_limited_by_user, require_role
from roletailor.api.schemas import CheckoutIn
from roletailor.services import billing, stripe_webhooks
from roletailor.services.auth import Principal
from roletailor.services.errors import AppError

router = APIRouter(prefix="/billing", tags=["billing"])
_BILLING_LIMIT = [Depends(rate_limited_by_user("billing", "rate_limit_billing_per_minute"))]


@router.get("/status")
def billing_status(principal: CurrentPrincipal) -> dict:
    return billing.status(principal)


@router.post("/checkout", dependencies=_BILLING_LIMIT)
def checkout(body: CheckoutIn, principal: Annotated[Principal, Depends(require_role("owner", "admin"))]) -> dict:
    return {"checkout_url": billing.create_checkout(principal, body.mode)}


@router.post("/portal", dependencies=_BILLING_LIMIT)
def portal(principal: Annotated[Principal, Depends(require_role("owner", "admin"))]) -> dict:
    return {"portal_url": billing.create_portal_session(principal)}


MAX_WEBHOOK_BYTES = 1_000_000


@router.post("/webhook")
async def webhook(request: Request, stripe_signature: Annotated[str | None, Header()] = None) -> dict:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_WEBHOOK_BYTES:
        raise AppError(413, "payload_too_large", "Webhook body is too large.")
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_WEBHOOK_BYTES:
            raise AppError(413, "payload_too_large", "Webhook body is too large.")
    event = stripe_webhooks.verify(bytes(body), stripe_signature)
    return {"status": await run_in_threadpool(stripe_webhooks.process, event)}
