from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from roletailor.api.deps import CurrentPrincipal, rate_limited_by_user
from roletailor.api.schemas import JobIn
from roletailor.services import jobs

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("", status_code=201,
             dependencies=[Depends(rate_limited_by_user("job", "rate_limit_job_per_minute"))])
def create_job(body: JobIn, principal: CurrentPrincipal) -> dict:
    return jobs.create_job(principal, source_url=body.source_url, description=body.description,
                           title=body.title, company=body.company)


@router.get("/{job_id}")
def get_job(job_id: UUID, principal: CurrentPrincipal) -> dict:
    return jobs.get_job(principal, job_id)
