from __future__ import annotations

from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header

from roletailor.api.deps import AIPrincipal, CurrentPrincipal, generation_rate_limit
from roletailor.api.metrics import WORKFLOW_REQUESTS
from roletailor.api.schemas import IterationIn, WorkflowIn
from roletailor.services import workflows
from roletailor.services.errors import AppError

router = APIRouter(prefix="/workflows", tags=["workflows"])


@router.post("", status_code=202, dependencies=[Depends(generation_rate_limit)])
def create_workflow(
    body: WorkflowIn,
    principal: AIPrincipal,
    idempotency_key: Annotated[str | None, Header(max_length=200)] = None,
) -> dict:
    try:
        workflow = workflows.create(
            principal, resume_version_id=body.resume_version_id, job_posting_id=body.job_posting_id,
            page_limit=body.page_limit, accept_paid_usage=body.accept_paid_usage,
            idempotency_key=idempotency_key or f"auto-{uuid4()}",
        )
    except AppError as exc:
        WORKFLOW_REQUESTS.labels(exc.code).inc()
        raise
    WORKFLOW_REQUESTS.labels("accepted").inc()
    return workflow


@router.get("")
def list_workflows(principal: CurrentPrincipal) -> list[dict]:
    return workflows.dashboard(principal)


@router.get("/{workflow_id}")
def get_workflow(workflow_id: UUID, principal: CurrentPrincipal) -> dict:
    return workflows.detail(principal, workflow_id)


@router.post("/{workflow_id}/iterations", status_code=202, dependencies=[Depends(generation_rate_limit)])
def request_iteration(workflow_id: UUID, body: IterationIn, principal: AIPrincipal) -> dict:
    return workflows.request_iteration(principal, workflow_id, body.focus_block_ids, body.instructions)


@router.post("/{workflow_id}/pause")
def pause(workflow_id: UUID, principal: CurrentPrincipal) -> dict:
    return workflows.pause(principal, workflow_id)


@router.post("/{workflow_id}/resume")
def resume(workflow_id: UUID, principal: AIPrincipal) -> dict:
    return workflows.resume(principal, workflow_id)


@router.post("/{workflow_id}/cancel")
def cancel(workflow_id: UUID, principal: CurrentPrincipal) -> dict:
    return workflows.cancel(principal, workflow_id)
