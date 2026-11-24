"""Request dependencies: authentication, RBAC, consent gate and rate limits."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from roletailor.config import get_settings
from roletailor.services import auth, users
from roletailor.services.auth import Principal
from roletailor.services.errors import AppError

_bearer = HTTPBearer(auto_error=False)


def get_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    x_organization_id: Annotated[UUID | None, Header()] = None,
) -> Principal:
    if credentials is None:
        raise AppError(401, "unauthorized", "Sign in to continue.")
    principal = auth.authenticate(credentials.credentials, x_organization_id)
    if principal is None:
        raise AppError(401, "unauthorized", "Your session has expired. Sign in again.")
    return principal


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


def require_role(*roles: str) -> Callable[[Principal], Principal]:
    def dependency(principal: CurrentPrincipal) -> Principal:
        if principal.role not in roles:
            raise AppError(403, "forbidden", "Your role does not allow this action.")
        return principal

    return dependency


def require_ai_consent(principal: CurrentPrincipal) -> Principal:
    if not users.has_ai_consent(principal.user_id):
        raise AppError(428, "consent_required", "Allow AI processing of your resume to continue.",
                       {"purpose": users.AI_PROCESSING})
    return principal


AIPrincipal = Annotated[Principal, Depends(require_ai_consent)]


def _client_ip(request: Request) -> str:
    # Behind a proxy, run uvicorn with --proxy-headers and --forwarded-allow-ips so this
    # is the original client address.
    return request.client.host if request.client else "unknown"


def enforce_rate_limit(request: Request, scope: str, identity: str, limit: int, message: str) -> None:
    retry_after = request.app.state.limiter.hit(scope, identity, limit)
    if retry_after is not None:
        raise AppError(429, "rate_limited", message, {"retry_after": retry_after})


def rate_limited_by_ip(scope: str) -> Callable[[Request], None]:
    def dependency(request: Request) -> None:
        enforce_rate_limit(request, scope, _client_ip(request), get_settings().rate_limit_auth_per_minute,
                           "Too many attempts. Try again shortly.")

    return dependency


def generation_rate_limit(request: Request, principal: CurrentPrincipal) -> None:
    enforce_rate_limit(request, "generate", str(principal.user_id),
                       get_settings().rate_limit_generation_per_minute,
                       "Too many generations at once. Try again shortly.")
