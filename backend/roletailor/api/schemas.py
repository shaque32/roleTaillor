"""Request bodies. Responses are the service-layer dicts documented in docs/api-v1.md."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

ApplicationStatus = Literal["saved", "applied", "interviewing", "offered", "rejected", "withdrawn", "accepted"]


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegisterIn(_Body):
    email: str = Field(max_length=320)
    password: str = Field(max_length=256)
    full_name: str = Field(min_length=1, max_length=200)


class LoginIn(_Body):
    email: str = Field(max_length=320)
    password: str = Field(max_length=256)
    device_label: str | None = Field(default=None, max_length=200)


class ForgotPasswordIn(_Body):
    email: str = Field(max_length=320)


class ResetPasswordIn(_Body):
    token: str = Field(min_length=1, max_length=200)
    password: str = Field(max_length=256)


class VerifyEmailIn(_Body):
    token: str = Field(min_length=1, max_length=200)


class ProfilePatch(_Body):
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    address: dict[str, Any] | None = None
    contact_number: str | None = Field(default=None, max_length=50)
    linkedin_url: str | None = Field(default=None, max_length=500)
    preferred_page_limit: int | None = Field(default=None, ge=1, le=5)
    industry_focus: str | None = Field(default=None, max_length=200)
    resume_tone: str | None = Field(default=None, max_length=100)
    ats_preference: str | None = Field(default=None, max_length=100)
    technical_depth: str | None = Field(default=None, max_length=100)
    preferred_template_id: UUID | None = None

    @field_validator("address")
    @classmethod
    def _small_address(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is not None and len(json.dumps(value)) > 2000:
            raise ValueError("address is too large")
        return value


class ConsentIn(_Body):
    purpose: Literal["ai_processing"]
    policy_version: str = Field(min_length=1, max_length=50)
    granted: bool


class ResumeRename(_Body):
    name: str = Field(min_length=1, max_length=200)


class ResumeTextIn(_Body):
    # Generous transport guard; the service enforces the real 50,000-char limit with a 413.
    text: str = Field(max_length=200_000)
    name: str | None = Field(default=None, max_length=200)


class JobIn(_Body):
    source_url: str | None = Field(default=None, max_length=2000)
    # Transport guard; the service keeps the first 50,000 characters.
    description: str | None = Field(default=None, max_length=200_000)
    title: str | None = Field(default=None, max_length=300)
    company: str | None = Field(default=None, max_length=300)


class WorkflowIn(_Body):
    resume_version_id: UUID
    job_posting_id: UUID
    page_limit: int | None = Field(default=None, ge=1, le=5)
    accept_paid_usage: bool = False


class IterationIn(_Body):
    focus_block_ids: list[str] | None = Field(default=None, max_length=200)
    instructions: str | None = Field(default=None, max_length=2000)


class ChangeDecisionIn(_Body):
    decision: Literal["accepted", "rejected", "pending"]


class ExportIn(_Body):
    kind: Literal["docx", "pdf", "ats_report", "feedback_report"]


class ShareIn(_Body):
    expires_in_hours: int = Field(ge=1)


class ApplicationIn(_Body):
    company: str = Field(min_length=1, max_length=300)
    role_title: str = Field(min_length=1, max_length=300)
    status: ApplicationStatus = "saved"
    applied_at: datetime | None = None
    reminder_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=10_000)
    job_posting_id: UUID | None = None
    resume_version_id: UUID | None = None


class ApplicationPatch(_Body):
    company: str | None = Field(default=None, min_length=1, max_length=300)
    role_title: str | None = Field(default=None, min_length=1, max_length=300)
    status: ApplicationStatus | None = None
    applied_at: datetime | None = None
    reminder_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=10_000)
    job_posting_id: UUID | None = None
    resume_version_id: UUID | None = None


class CheckoutIn(_Body):
    mode: Literal["subscription", "pay_per_use"]
