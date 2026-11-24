from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Response

from roletailor.api.deps import CurrentPrincipal
from roletailor.api.schemas import ApplicationIn, ApplicationPatch
from roletailor.services import applications

router = APIRouter(prefix="/applications", tags=["applications"])


@router.get("")
def list_applications(principal: CurrentPrincipal) -> list[dict]:
    return applications.list_applications(principal)


@router.post("", status_code=201)
def create_application(body: ApplicationIn, principal: CurrentPrincipal) -> dict:
    return applications.create(principal, body.model_dump())


@router.get("/{application_id}")
def get_application(application_id: UUID, principal: CurrentPrincipal) -> dict:
    return applications.get(principal, application_id)


@router.patch("/{application_id}")
def update_application(application_id: UUID, body: ApplicationPatch, principal: CurrentPrincipal) -> dict:
    return applications.update(principal, application_id, body.model_dump(exclude_unset=True))


@router.delete("/{application_id}", status_code=204)
def delete_application(application_id: UUID, principal: CurrentPrincipal) -> Response:
    applications.delete(principal, application_id)
    return Response(status_code=204)
