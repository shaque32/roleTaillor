from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from roletailor.api.deps import CurrentPrincipal
from roletailor.api.schemas import JobIn
from roletailor.services import jobs

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("", status_code=201)
def create_job(body: JobIn, principal: CurrentPrincipal) -> dict:
    return jobs.create_job(principal, source_url=body.source_url, description=body.description,
                           title=body.title, company=body.company)


@router.get("/{job_id}")
def get_job(job_id: UUID, principal: CurrentPrincipal) -> dict:
    return jobs.get_job(principal, job_id)
