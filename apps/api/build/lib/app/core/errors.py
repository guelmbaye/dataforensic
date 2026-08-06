"""Unified error contract (DOCUMENT 06 - section 23)."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    code: str = "INTERNAL_ERROR"
    status_code: int = 500
    retryable: bool = False

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_payload(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "retryable": self.retryable,
                "details": self.details,
            }
        }


class ValidationError(AppError):
    code = "VALIDATION_ERROR"
    status_code = 422


class NotFoundError(AppError):
    code = "NOT_FOUND"
    status_code = 404


class DataHubUnavailableError(AppError):
    code = "DATAHUB_UNAVAILABLE"
    status_code = 503
    retryable = True


class InvestigationFailedError(AppError):
    code = "INVESTIGATION_FAILED"
    status_code = 500
    retryable = True


class ActionNotAllowedError(AppError):
    code = "ACTION_NOT_ALLOWED"
    status_code = 403


class VerificationFailedError(AppError):
    code = "VERIFICATION_FAILED"
    status_code = 409


class WriteBackFailedError(AppError):
    code = "WRITE_BACK_FAILED"
    status_code = 502
    retryable = True


class InvalidStateTransitionError(AppError):
    code = "INVALID_STATE_TRANSITION"
    status_code = 409


async def app_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    return JSONResponse(status_code=exc.status_code, content=exc.to_payload())


async def unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": f"Unexpected error: {exc.__class__.__name__}",
                "retryable": False,
                "details": {},
            }
        },
    )
