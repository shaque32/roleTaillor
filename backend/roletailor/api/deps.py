"""Request dependencies: authentication, RBAC, consent gate and rate limits."""

from __future__ import annotations

import hmac
import ipaddress
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


def _valid_ip(value: str | None) -> str | None:
    """Canonical form of a client address; IPv6 clients are bucketed by their /64."""
    try:
        ip = ipaddress.ip_address((value or "").strip())
    except ValueError:
        return None
    if ip.version == 6:
        if ip.ipv4_mapped is not None:
            return str(ip.ipv4_mapped)
        return str(ipaddress.ip_network(f"{ip}/64", strict=False).network_address)
    return str(ip)


def client_ip(request: Request) -> str:
    """The address rate limits are keyed on. X-Forwarded-For is never trusted: anyone can
    send it. In order: the browser address relayed by our own web app (authenticated by
    the shared proxy secret), the header the platform edge sets, then the socket peer."""
    settings = get_settings()
    secret = settings.proxy_shared_secret
    if secret and hmac.compare_digest(request.headers.get("x-rt-proxy-secret", "").encode(), secret.encode()):
        relayed = _valid_ip(request.headers.get("x-rt-client-ip"))
        if relayed:
            return relayed
    if settings.client_ip_header:
        edge = _valid_ip(request.headers.get(settings.client_ip_header))
        if edge:
            return edge
    return (request.client.host if request.client else None) or "unknown"


def enforce_rate_limit(request: Request, scope: str, identity: str, limit: int, message: str,
                       window_s: int = 60) -> None:
    retry_after = request.app.state.limiter.hit(scope, identity, limit, window_s)
    if retry_after is not None:
        raise AppError(429, "rate_limited", message, {"retry_after": retry_after})


def rate_limited_by_ip(scope: str) -> Callable[[Request], None]:
    def dependency(request: Request) -> None:
        enforce_rate_limit(request, scope, client_ip(request), get_settings().rate_limit_auth_per_minute,
                           "Too many attempts. Try again shortly.")

    return dependency


def rate_limited_by_user(scope: str, setting: str) -> Callable[[Request, Principal], None]:
    """Per-user fixed-window limit; `setting` names the Settings field holding the limit."""

    def dependency(request: Request, principal: CurrentPrincipal) -> None:
        enforce_rate_limit(request, scope, str(principal.user_id), getattr(get_settings(), setting),
                           "You are doing that too often. Try again shortly.")

    return dependency


def generation_rate_limit(request: Request, principal: CurrentPrincipal) -> None:
    """Every model run goes through here: first generations, iterations and retries."""
    settings = get_settings()
    enforce_rate_limit(request, "generate", str(principal.user_id), settings.rate_limit_generation_per_minute,
                       "Too many generations at once. Try again shortly.")
    enforce_rate_limit(request, "generate-day", str(principal.org_id), settings.generation_runs_per_org_per_day,
                       "You have reached today's generation limit. Try again tomorrow.", window_s=86_400)
