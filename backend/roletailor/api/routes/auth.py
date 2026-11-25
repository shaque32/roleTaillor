from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response
from fastapi.responses import JSONResponse

from roletailor.api.deps import CurrentPrincipal, client_ip, enforce_rate_limit, rate_limited_by_ip
from roletailor.api.schemas import ForgotPasswordIn, LoginIn, RegisterIn, ResetPasswordIn, VerifyEmailIn
from roletailor.config import get_settings
from roletailor.services import auth, email_auth
from roletailor.services.errors import AppError

router = APIRouter(prefix="/auth", tags=["auth"])


def _out(result: auth.AuthResult) -> dict:
    return {"token": result.token, "expires_at": result.expires_at, "user": result.user,
            "organization": result.organization}


@router.post("/register", status_code=201, dependencies=[Depends(rate_limited_by_ip("register"))])
def register(body: RegisterIn, request: Request, background: BackgroundTasks) -> dict:
    enforce_rate_limit(request, "register-day", client_ip(request), get_settings().rate_limit_register_per_day,
                       "Too many sign-ups from this network today. Try again tomorrow.", window_s=86_400)
    result = auth.register(body.email, body.password, body.full_name, request.headers.get("user-agent"))
    # After the response: a slow or failing email provider must not fail the sign-up.
    background.add_task(email_auth.send_verification_email_quietly, result.user["id"])
    return _out(result)


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


@router.post("/verify-email", dependencies=[Depends(rate_limited_by_ip("verify-email"))])
def verify_email(body: VerifyEmailIn) -> dict:
    email_auth.verify_email(body.token)
    return {"status": "verified"}


@router.post("/verify-email/resend")
def resend_verification(request: Request, principal: CurrentPrincipal) -> JSONResponse:
    enforce_rate_limit(request, "verify-resend", str(principal.user_id),
                       get_settings().rate_limit_verification_email_per_hour,
                       "You have asked for several emails already. Check your inbox, or try again later.",
                       window_s=3600)
    status = email_auth.send_verification_email(principal.user_id)
    if status == "failed":
        raise AppError(503, "email_unavailable", "We could not send the email just now. Try again shortly.")
    return JSONResponse({"status": status}, status_code=200 if status == "already_verified" else 202)


@router.post("/forgot-password", status_code=202, dependencies=[Depends(rate_limited_by_ip("forgot-password"))])
def forgot_password(body: ForgotPasswordIn, request: Request, background: BackgroundTasks) -> dict:
    """Always the same answer. The lookup and the email happen after the response, so
    neither the body nor the timing says whether the address has an account."""
    address = body.email.strip().lower()
    # Over the per-address budget the request is dropped quietly, not refused: a 429 here
    # would let anyone block another person's reset, and the newest link already mailed
    # still works.
    over_budget = request.app.state.limiter.hit(
        "forgot-email", address, get_settings().rate_limit_password_reset_per_hour, 3600)
    if over_budget is None:
        background.add_task(email_auth.request_password_reset, address)
    return {"status": "accepted"}


@router.post("/reset-password", dependencies=[Depends(rate_limited_by_ip("reset-password"))])
def reset_password(body: ResetPasswordIn) -> dict:
    email_auth.reset_password(body.token, body.password)
    return {"status": "password_reset"}
