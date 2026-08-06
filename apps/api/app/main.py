"""DATAFORENSIC AI - FastAPI application entrypoint."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.api.router import api_router
from app.config import settings
from app.core.errors import AppError, app_error_handler, unhandled_error_handler
from app.core.logging import configure_logging, get_logger
from app.models.database import dispose_db, init_db
from app.services.datahub import build_provider, reset_provider

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging(settings.log_level)
    await init_db()
    try:
        provider = await build_provider()
        logger.info(
            "startup_complete",
            extra={
                "provider": provider.name,
                "source_mode": str(provider.source_mode),
                "environment": settings.environment,
            },
        )
    except Exception as exc:  # noqa: BLE001 - the API must start to report the failure
        logger.error("datahub_provider_startup_failed", extra={"error": str(exc)})
    yield
    await reset_provider()
    await dispose_db()


app = FastAPI(
    title="DATAFORENSIC AI",
    version=__version__,
    description=(
        "Autonomous data incident investigator built on the DataHub context graph. "
        "Investigate -> Resolve -> Remember."
    ),
    lifespan=lifespan,
    docs_url="/docs",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Location", "Last-Event-ID"],
)

app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(Exception, unhandled_error_handler)


@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    # `exc.errors()` carries the original exception object under `ctx`, which is
    # not JSON serializable. Project each error onto plain primitives.
    errors = [
        {
            "location": [str(part) for part in error.get("loc", [])],
            "message": str(error.get("msg", "")),
            "type": str(error.get("type", "")),
        }
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Request payload is invalid",
                "retryable": False,
                "details": {"errors": errors},
            }
        },
    )


app.include_router(api_router, prefix=settings.api_prefix)


@app.get("/", tags=["meta"])
async def root() -> dict:
    return {
        "name": "DATAFORENSIC AI",
        "version": __version__,
        "tagline": "Investigate. Resolve. Remember.",
        "api": settings.api_prefix,
        "docs": "/docs",
    }
