from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import datahub_provider, db_session
from app.schemas.memory import MemorySearchResponse
from app.services.datahub.base import DataHubProvider
from app.services.memory import MemoryService

router = APIRouter(prefix="/memory", tags=["memory"])


@router.get("/search", response_model=MemorySearchResponse)
async def search_memory(
    asset_urn: str | None = Query(default=None),
    pattern: str | None = Query(default=None),
    symptom: str | None = Query(default=None),
    exclude_incident_id: str | None = Query(default=None),
    limit: int = Query(default=5, ge=1, le=25),
    session: AsyncSession = Depends(db_session),
    provider: DataHubProvider = Depends(datahub_provider),
) -> MemorySearchResponse:
    service = MemoryService(session, provider)
    matches = await service.find_previous_incidents(
        asset_urn=asset_urn,
        pattern=pattern,
        symptom=symptom,
        exclude_incident_id=exclude_incident_id,
        limit=limit,
    )
    return MemorySearchResponse(
        query={
            "asset_urn": asset_urn,
            "pattern": pattern,
            "symptom": symptom,
            "limit": limit,
        },
        matches=matches,
    )
