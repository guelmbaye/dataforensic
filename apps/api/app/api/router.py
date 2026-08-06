from __future__ import annotations

from fastapi import APIRouter

from app.api import (
    actions,
    datahub,
    health,
    incidents,
    investigations,
    memory,
    patterns,
    scenarios,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(incidents.router)
api_router.include_router(investigations.router)
api_router.include_router(actions.router)
api_router.include_router(memory.router)
api_router.include_router(patterns.router)
api_router.include_router(datahub.router)
api_router.include_router(scenarios.router)
