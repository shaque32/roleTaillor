from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from starlette.concurrency import run_in_threadpool

from roletailor.api.deps import CurrentPrincipal, require_role
from roletailor.api.schemas import CheckoutIn
from roletailor.services import billing, stripe_webhooks
from roletailor.services.auth import Principal

router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("/status")
def billing_status(principal: CurrentPrincipal) -> dict:
    return billing.status(principal)


@router.post("/checkout")
def checkout(body: CheckoutIn, principal: Annotated[Principal, Depends(require_role("owner", "admin"))]) -> dict:
    return {"checkout_url": billing.create_checkout(principal, body.mode)}


@router.post("/webhook")
async def webhook(request: Request, stripe_signature: Annotated[str | None, Header()] = None) -> dict:
    event = stripe_webhooks.verify(await request.body(), stripe_signature)
    return {"status": await run_in_threadpool(stripe_webhooks.process, event)}
