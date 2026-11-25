from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response

from roletailor.api.deps import CurrentPrincipal, client_ip, enforce_rate_limit, rate_limited_by_ip
from roletailor.api.schemas import LoginIn, RegisterIn
from roletailor.config import get_settings
from roletailor.services import auth

router = APIRouter(prefix="/auth", tags=["auth"])


def _out(result: auth.AuthResult) -> dict:
    return {"token": result.token, "expires_at": result.expires_at, "user": result.user,
            "organization": result.organization}


@router.post("/register", status_code=201, dependencies=[Depends(rate_limited_by_ip("register"))])
def register(body: RegisterIn, request: Request) -> dict:
    enforce_rate_limit(request, "register-day", client_ip(request), get_settings().rate_limit_register_per_day,
                       "Too many sign-ups from this network today. Try again tomorrow.", window_s=86_400)
    return _out(auth.register(body.email, body.password, body.full_name, request.headers.get("user-agent")))


@router.post("/login", dependencies=[Depends(rate_limited_by_ip("login"))])
def login(body: LoginIn, request: Request) -> dict:
    # Per-account bucket too: requests proxied by the web app share one client address.
    enforce_rate_limit(request, "login-email", body.email.strip().lower(), get_settings().rate_limit_auth_per_minute,
                       "Too many attempts. Try again shortly.")
    enforce_rate_limit(request, "login-email-hour", body.email.strip().lower(),
                       get_settings().rate_limit_login_per_hour,
                       "Too many sign-in attempts for this account. Try again later.", window_s=3600)
    label = body.device_label or request.headers.get("user-agent")
    return _out(auth.login(body.email, body.password, label))


@router.post("/logout", status_code=204)
def logout(principal: CurrentPrincipal) -> Response:
    auth.logout(principal)
    return Response(status_code=204)
