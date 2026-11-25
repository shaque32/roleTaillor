"""Errors raised by services and rendered by the API as the uniform error envelope."""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    def __init__(
        self, status: int, code: str, message: str, details: dict[str, Any] | None = None
    ):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}


def not_found(resource: str) -> AppError:
    return AppError(404, "not_found", f"{resource} not found.")


def invalid_state(message: str, **details: Any) -> AppError:
    return AppError(409, "invalid_state", message, details)
