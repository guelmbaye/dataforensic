from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import IdempotencyGuard, db_session, idempotency
from app.config import settings
from app.schemas.incident import IncidentCreate, IncidentDetail, IncidentSummary
from app.schemas.investigation import InvestigationStartResponse
from app.services.incidents import IncidentService
from app.services.investigation import InvestigationService

router = APIRouter(prefix="/incidents", tags=["incidents"])


@router.post("", response_model=IncidentSummary, status_code=status.HTTP_201_CREATED)
async def create_incident(
    payload: IncidentCreate,
    guard: IdempotencyGuard = Depends(idempotency),
    session: AsyncSession = Depends(db_session),
) -> IncidentSummary:
    body = payload.model_dump(mode="json")
    cached = await guard.replay(body)
    if cached:
        return IncidentSummary.model_validate(cached)

    service = IncidentService(session)
    incident = await service.create(payload)
    summary = await service.summary(incident)
    await guard.store(body, IncidentSummary.model_validate(summary).model_dump(mode="json"), 201)
    return IncidentSummary.model_validate(summary)


@router.get("", response_model=dict)
async def list_incidents(
    status_filter: str | None = Query(default=None, alias="status"),
    severity: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(db_session),
) -> dict:
    service = IncidentService(session)
    rows, total = await service.list(status_filter, severity, limit, offset)
    items = [IncidentSummary.model_validate(await service.summary(row)) for row in rows]
    return {
        "items": [item.model_dump(mode="json") for item in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/{incident_id}", response_model=IncidentDetail)
async def get_incident(
    incident_id: str, session: AsyncSession = Depends(db_session)
) -> IncidentDetail:
    service = IncidentService(session)
    incident = await service.get(incident_id)
    return IncidentDetail.model_validate(await service.detail(incident))


@router.post(
    "/{incident_id}/investigate",
    response_model=InvestigationStartResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def investigate(
    incident_id: str,
    request: Request,
    response: Response,
    guard: IdempotencyGuard = Depends(idempotency),
    session: AsyncSession = Depends(db_session),
) -> InvestigationStartResponse:
    body = {"incident_id": incident_id}
    cached = await guard.replay(body)
    if cached:
        return InvestigationStartResponse.model_validate(cached)

    service = InvestigationService(session)
    investigation = await service.start(incident_id)
    payload = InvestigationStartResponse(
        investigation_id=investigation.id,
        incident_id=incident_id,
        status=investigation.status,  # type: ignore[arg-type]
        stream_url=f"{settings.api_prefix}/investigations/{investigation.id}/events",
    )
    await guard.store(body, payload.model_dump(mode="json"), 202)
    response.headers["Location"] = f"{settings.api_prefix}/investigations/{investigation.id}"
    return payload
