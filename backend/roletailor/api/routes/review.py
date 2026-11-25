from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse, Response

from roletailor.api.deps import CurrentPrincipal, rate_limited_by_user
from roletailor.api.schemas import ChangeDecisionIn, ExportIn, ShareIn
from roletailor.services import review
from roletailor.services.errors import not_found
from roletailor.storage import LocalStorage, get_storage

router = APIRouter(tags=["review"])
_EXPORT_LIMIT = [Depends(rate_limited_by_user("export", "rate_limit_export_per_minute"))]


@router.patch("/generated/{generated_id}/changes/{change_id}")
def decide_change(generated_id: UUID, change_id: UUID, body: ChangeDecisionIn,
                  principal: CurrentPrincipal) -> dict:
    return review.decide_change(principal, generated_id, change_id, body.decision)


@router.post("/generated/{generated_id}/approve")
def approve(generated_id: UUID, principal: CurrentPrincipal) -> dict:
    return review.approve(principal, generated_id)


@router.post("/generated/{generated_id}/exports", status_code=201, dependencies=_EXPORT_LIMIT)
def create_export(generated_id: UUID, body: ExportIn, principal: CurrentPrincipal) -> dict:
    return review.create_export(principal, generated_id, body.kind)


@router.post("/exports/{export_id}/share", status_code=201, dependencies=_EXPORT_LIMIT)
def share_export(export_id: UUID, body: ShareIn, principal: CurrentPrincipal) -> dict:
    return review.share(principal, export_id, body.expires_in_hours)


@router.get("/share/{token}", include_in_schema=True)
def open_share_link(token: str) -> RedirectResponse:
    return RedirectResponse(review.resolve_share(token), status_code=302)


@router.get("/files/{token}", include_in_schema=False)
def download_local_file(token: str, request: Request) -> Response:
    """Serves LocalStorage signed URLs (dev only; S3 serves presigned URLs itself)."""
    storage = get_storage()
    target = storage.verify_token(token) if isinstance(storage, LocalStorage) else None
    if target is None:
        raise not_found("File")
    return Response(
        storage.get(target.key), media_type=target.media_type,
        headers={"Content-Disposition": f'attachment; filename="{target.filename}"',
                 "Cache-Control": "private, no-store"},
    )
