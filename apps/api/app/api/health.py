from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.api.deps import db_session
from app.config import settings
from app.schemas.common import HealthResponse
from app.services.datahub import provider_status

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health(session: AsyncSession = Depends(db_session)) -> HealthResponse:
    try:
        await session.execute(text("SELECT 1"))
        database = "ok"
    except Exception as exc:  # noqa: BLE001 - reported, never hidden
        database = f"error: {exc.__class__.__name__}"

    return HealthResponse(
        status="ok" if database == "ok" else "degraded",
        version=__version__,
        environment=settings.environment,
        database=database,
        datahub=provider_status(),
        llm={
            "provider": settings.llm_provider,
            "model": settings.llm_model if settings.llm_provider != "none" else None,
            "enabled": settings.llm_provider != "none" and bool(settings.llm_api_key),
            "note": "The deterministic engine always decides the root cause.",
        },
    )
