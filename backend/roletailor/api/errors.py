"""Uniform error envelope: {"error": {"code", "message", "details"}}."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from psycopg import errors as pg_errors
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException

from roletailor.services.errors import AppError

log = logging.getLogger(__name__)

_HTTP_CODES = {
    400: "bad_request", 401: "unauthorized", 403: "forbidden", 404: "not_found",
    405: "method_not_allowed", 409: "conflict", 413: "payload_too_large", 415: "unsupported_media_type",
    422: "validation_error", 428: "precondition_required", 429: "rate_limited",
}


def error_response(status: int, code: str, message: str, details: dict[str, Any] | None = None,
                   headers: dict[str, str] | None = None) -> JSONResponse:
    body = {"error": {"code": code, "message": message, "details": details or {}}}
    return JSONResponse(jsonable_encoder(body), status_code=status, headers=headers)


async def _app_error(_: Request, exc: AppError) -> JSONResponse:
    headers = {"Retry-After": str(exc.details["retry_after"])} if "retry_after" in exc.details else None
    return error_response(exc.status, exc.code, exc.message, exc.details, headers)


async def _http_error(_: Request, exc: HTTPException) -> JSONResponse:
    code = _HTTP_CODES.get(exc.status_code, "http_error")
    return error_response(exc.status_code, code, str(exc.detail), headers=getattr(exc, "headers", None))


async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [{"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
    return error_response(422, "validation_error", "The request is invalid.", {"errors": errors})


async def _integrity_error(_: Request, exc: IntegrityError) -> JSONResponse:
    if isinstance(exc.orig, pg_errors.ForeignKeyViolation):
        return error_response(422, "invalid_reference", "A referenced record does not exist.")
    if isinstance(exc.orig, pg_errors.UniqueViolation):
        return error_response(409, "conflict", "This record already exists.")
    if isinstance(exc.orig, pg_errors.CheckViolation):
        return error_response(422, "validation_error", "A value is out of range.")
    log.exception("integrity error")
    return error_response(500, "internal_error", "Something went wrong.")


async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled error", exc_info=exc)
    return error_response(500, "internal_error", "Something went wrong.")


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error)
    app.add_exception_handler(HTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(IntegrityError, _integrity_error)
    app.add_exception_handler(Exception, _unhandled)
