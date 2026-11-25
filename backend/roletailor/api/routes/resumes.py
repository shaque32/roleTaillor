from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile

from roletailor.api.deps import CurrentPrincipal, rate_limited_by_user
from roletailor.api.schemas import ResumeRename, ResumeTextIn
from roletailor.config import get_settings
from roletailor.services import resumes
from roletailor.services.errors import AppError
from roletailor.services.guided import GuidedResume

router = APIRouter(prefix="/resumes", tags=["resumes"])
_UPLOAD_LIMIT = [Depends(rate_limited_by_user("upload", "rate_limit_upload_per_minute"))]


@router.get("")
def list_resumes(principal: CurrentPrincipal) -> list[dict]:
    return resumes.list_resumes(principal)


@router.post("", status_code=201, dependencies=_UPLOAD_LIMIT)
def upload_resume(
    response: Response,
    principal: CurrentPrincipal,
    file: Annotated[UploadFile, File()],
    name: Annotated[str | None, Form(max_length=200)] = None,
) -> dict:
    limit = get_settings().max_upload_bytes
    data = file.file.read(limit + 1)
    if len(data) > limit:
        raise AppError(413, "file_too_large", f"Files must be at most {limit} bytes.")
    result = resumes.create_from_upload(principal, data, file.filename, name)
    if result["version"] is None:  # a scan: OCR continues in the worker
        response.status_code = 202
    return result


@router.post("/guided", status_code=201, dependencies=_UPLOAD_LIMIT)
def create_guided(body: GuidedResume, principal: CurrentPrincipal) -> dict:
    return resumes.create_guided(principal, body)


@router.post("/text", status_code=201, dependencies=_UPLOAD_LIMIT)
def create_from_text(body: ResumeTextIn, principal: CurrentPrincipal) -> dict:
    return resumes.create_from_text(principal, body.text, body.name)


@router.get("/{resume_id}")
def get_resume(resume_id: UUID, principal: CurrentPrincipal) -> dict:
    return resumes.get_resume(principal, resume_id)


@router.post("/{resume_id}/processing/retry", status_code=202, dependencies=_UPLOAD_LIMIT)
def retry_processing(resume_id: UUID, principal: CurrentPrincipal) -> dict:
    return resumes.retry_processing(principal, resume_id)


@router.patch("/{resume_id}")
def rename_resume(resume_id: UUID, body: ResumeRename, principal: CurrentPrincipal) -> dict:
    return resumes.rename(principal, resume_id, body.name)


@router.delete("/{resume_id}", status_code=204)
def archive_resume(resume_id: UUID, principal: CurrentPrincipal) -> Response:
    resumes.archive(principal, resume_id)
    return Response(status_code=204)


@router.get("/{resume_id}/versions/{version_id}")
def get_version(resume_id: UUID, version_id: UUID, principal: CurrentPrincipal) -> dict:
    return resumes.get_resume_version(principal, resume_id, version_id)


@router.post("/{resume_id}/versions/{version_id}/restore", status_code=201)
def restore_version(resume_id: UUID, version_id: UUID, principal: CurrentPrincipal) -> dict:
    return resumes.restore_version(principal, resume_id, version_id)
