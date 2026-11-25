from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from roletailor.api.deps import CurrentPrincipal, rate_limited_by_user
from roletailor.api.schemas import ConsentIn, ProfilePatch
from roletailor.services import account, notifications, users

router = APIRouter(tags=["profile"])
_ACCOUNT_LIMIT = [Depends(rate_limited_by_user("account", "rate_limit_account_per_minute"))]


@router.get("/me")
def get_me(principal: CurrentPrincipal) -> dict:
    return users.get_profile(principal.user_id)


@router.patch("/me")
def patch_me(body: ProfilePatch, principal: CurrentPrincipal) -> dict:
    return users.update_profile(principal.user_id, body.model_dump(exclude_unset=True))


@router.delete("/me", status_code=202, dependencies=_ACCOUNT_LIMIT)
def delete_me(principal: CurrentPrincipal) -> dict:
    account.delete_account(principal)
    return {"status": "deleted"}


@router.get("/me/export", dependencies=_ACCOUNT_LIMIT)
def export_me(principal: CurrentPrincipal) -> dict:
    return account.export_data(principal)


@router.post("/consents", status_code=201)
def record_consent(body: ConsentIn, principal: CurrentPrincipal) -> dict:
    return users.record_consent(principal.user_id, body.purpose, body.policy_version, body.granted)


@router.get("/notifications")
def list_notifications(principal: CurrentPrincipal) -> list[dict]:
    return notifications.list_for(principal)


@router.post("/notifications/{notification_id}/read")
def read_notification(notification_id: UUID, principal: CurrentPrincipal) -> dict:
    return notifications.mark_read(principal, notification_id)
