from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import IdempotencyGuard, datahub_provider, db_session, idempotency
from app.core.events import event_bus
from app.core.utils import to_iso
from app.domain.enums import InvestigationStatus
from app.models.database import session_scope
from app.schemas.investigation import EvidenceOut, HypothesisOut, InvestigationOut
from app.schemas.memory import MemoryWriteResponse
from app.schemas.remediation import RemediationOut
from app.schemas.verification import VerificationOut
from app.services.datahub.base import DataHubProvider
from app.services.events import TERMINAL_EVENTS
from app.services.incidents import IncidentService
from app.services.investigation import (
    InvestigationService,
    serialize_action,
    serialize_verification,
)
from app.services.resolution import ResolutionService

router = APIRouter(prefix="/investigations", tags=["investigations"])

HEARTBEAT_SECONDS = 15.0
STREAM_MAX_SECONDS = 900.0


@router.get("/{investigation_id}", response_model=InvestigationOut)
async def get_investigation(
    investigation_id: str, session: AsyncSession = Depends(db_session)
) -> InvestigationOut:
    service = InvestigationService(session)
    investigation = await service.get(investigation_id)
    return InvestigationOut.model_validate(await service.build_output(investigation))


@router.get("/{investigation_id}/evidence", response_model=list[EvidenceOut])
async def get_evidence(
    investigation_id: str,
    type_filter: str | None = Query(default=None, alias="type"),
    relevance: str | None = Query(default=None),
    asset_urn: str | None = Query(default=None),
    session: AsyncSession = Depends(db_session),
) -> list[EvidenceOut]:
    service = InvestigationService(session)
    await service.get(investigation_id)
    rows = await service.evidence(investigation_id)
    items = []
    for row in rows:
        if type_filter and row.type != type_filter:
            continue
        if relevance and row.relevance != relevance:
            continue
        if asset_urn and row.asset_urn != asset_urn:
            continue
        items.append(
            EvidenceOut(
                id=row.id,
                type=row.type,  # type: ignore[arg-type]
                source=row.source,
                source_system=row.source_system,
                source_mode=row.source_mode,
                asset_urn=row.asset_urn,
                field_path=row.field_path,
                observation=row.observation,
                relevance=row.relevance,  # type: ignore[arg-type]
                observed_at=row.observed_at,
                lineage_distance=row.lineage_distance,
                metadata=row.extra or {},
            )
        )
    return items


@router.get("/{investigation_id}/hypotheses", response_model=list[HypothesisOut])
async def get_hypotheses(
    investigation_id: str, session: AsyncSession = Depends(db_session)
) -> list[HypothesisOut]:
    service = InvestigationService(session)
    await service.get(investigation_id)
    rows = await service.hypotheses(investigation_id)
    return [
        HypothesisOut(
            id=row.id,
            pattern=row.pattern,
            description=row.description,
            confidence=float(row.confidence or 0.0),
            status=row.status,  # type: ignore[arg-type]
            reasoning_summary=row.reasoning_summary,
            score_breakdown=row.score_breakdown or {},
            supporting_evidence_ids=row.supporting_evidence_ids or [],
            contradicting_evidence_ids=row.contradicting_evidence_ids or [],
            proposed_by=row.proposed_by,
            is_primary=bool(row.is_primary),
        )
        for row in rows
    ]


@router.post("/{investigation_id}/remediation", response_model=RemediationOut)
async def create_remediation(
    investigation_id: str,
    guard: IdempotencyGuard = Depends(idempotency),
    session: AsyncSession = Depends(db_session),
    provider: DataHubProvider = Depends(datahub_provider),
) -> RemediationOut:
    body = {"investigation_id": investigation_id}
    cached = await guard.replay(body)
    if cached:
        return RemediationOut.model_validate(cached)

    service = InvestigationService(session)
    investigation = await service.get(investigation_id)
    incident = await IncidentService(session).get(investigation.incident_id)

    existing = await service.latest_action(investigation_id)
    if existing is not None:
        payload = RemediationOut.model_validate(serialize_action(existing))
    else:
        action = await ResolutionService(session, provider).create_plan(investigation, incident)
        payload = RemediationOut.model_validate(serialize_action(action))
    await guard.store(body, payload.model_dump(mode="json"))
    return payload


@router.post("/{investigation_id}/verify", response_model=VerificationOut)
async def verify(
    investigation_id: str,
    guard: IdempotencyGuard = Depends(idempotency),
    session: AsyncSession = Depends(db_session),
    provider: DataHubProvider = Depends(datahub_provider),
) -> VerificationOut:
    body = {"investigation_id": investigation_id}
    cached = await guard.replay(body)
    if cached:
        return VerificationOut.model_validate(cached)

    service = InvestigationService(session)
    investigation = await service.get(investigation_id)
    incident = await IncidentService(session).get(investigation.incident_id)
    record, _ = await ResolutionService(session, provider).verify(investigation, incident)
    payload = VerificationOut.model_validate(
        {**serialize_verification(record), "incident_status": incident.status}
    )
    await guard.store(body, payload.model_dump(mode="json"))
    return payload


@router.post("/{investigation_id}/memory", response_model=MemoryWriteResponse)
async def write_memory(
    investigation_id: str,
    guard: IdempotencyGuard = Depends(idempotency),
    session: AsyncSession = Depends(db_session),
    provider: DataHubProvider = Depends(datahub_provider),
) -> MemoryWriteResponse:
    body = {"investigation_id": investigation_id}
    cached = await guard.replay(body)
    if cached:
        return MemoryWriteResponse.model_validate(cached)

    service = InvestigationService(session)
    investigation = await service.get(investigation_id)
    incident = await IncidentService(session).get(investigation.incident_id)
    response = await ResolutionService(session, provider).write_memory(investigation, incident)
    await guard.store(body, response.model_dump(mode="json"))
    return response


def _sse(event: dict) -> str:
    return (
        f"id: {event['seq']}\n"
        f"event: {event['event']}\n"
        f"data: {json.dumps(event, default=str)}\n\n"
    )


@router.get("/{investigation_id}/events")
async def stream_events(
    investigation_id: str,
    request: Request,
    last_event_id: int = Query(default=0, alias="lastEventId", ge=0),
) -> StreamingResponse:
    """Server-Sent Events stream of the investigation timeline.

    The client subscribes *before* replaying persisted events, so no event can
    be lost between the replay and the live stream.
    """
    header_id = request.headers.get("last-event-id")
    resume_from = int(header_id) if header_id and header_id.isdigit() else last_event_id

    queue = await event_bus.subscribe(investigation_id)

    async def generator() -> AsyncIterator[str]:
        elapsed = 0.0
        try:
            async with session_scope() as session:
                service = InvestigationService(session)
                investigation = await service.get(investigation_id)
                rows = await service.events_since(investigation_id, resume_from)
                highest = resume_from
                for row in rows:
                    highest = row.seq
                    yield _sse(
                        {
                            "seq": row.seq,
                            "event": row.event,
                            "level": row.level,
                            "message": row.message,
                            "payload": row.payload,
                            "created_at": to_iso(row.created_at),
                            "investigation_id": investigation_id,
                        }
                    )
                terminal_seen = any(row.event in TERMINAL_EVENTS for row in rows)
                already_finished = investigation.status != str(InvestigationStatus.RUNNING)

            if terminal_seen or already_finished:
                yield "event: stream_closed\ndata: {\"reason\": \"investigation is not running\"}\n\n"
                return

            while elapsed < STREAM_MAX_SECONDS:
                if await request.is_disconnected():
                    return
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
                except TimeoutError:
                    elapsed += HEARTBEAT_SECONDS
                    yield ": keep-alive\n\n"
                    continue
                if event["seq"] <= highest:
                    continue
                highest = event["seq"]
                yield _sse(event)
                if event["event"] in TERMINAL_EVENTS:
                    yield "event: stream_closed\ndata: {\"reason\": \"investigation finished\"}\n\n"
                    return
        finally:
            await event_bus.unsubscribe(investigation_id, queue)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
