"""Incident application service."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.core.utils import urn_name
from app.domain.enums import IncidentStatus
from app.models.tables import Incident, Investigation, MemoryReference, Verification
from app.schemas.incident import IncidentCreate
from app.services.scenario import get_registry


class IncidentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, payload: IncidentCreate) -> Incident:
        scenario_id = payload.scenario_id
        if scenario_id is None:
            scenario = get_registry().for_asset(payload.asset_urn)
            scenario_id = scenario.id if scenario else None
        incident = Incident(
            title=payload.title,
            description=payload.description,
            asset_urn=payload.asset_urn,
            severity=str(payload.severity),
            observed_value=payload.observed_value,
            expected_value=payload.expected_value,
            detected_at=payload.detected_at,
            scenario_id=scenario_id,
            status=str(IncidentStatus.CREATED),
        )
        self.session.add(incident)
        await self.session.flush()
        return incident

    async def get(self, incident_id: str) -> Incident:
        incident = await self.session.get(Incident, incident_id)
        if incident is None:
            raise NotFoundError(f"Incident {incident_id} not found")
        return incident

    async def list(
        self,
        status: str | None = None,
        severity: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Incident], int]:
        stmt = select(Incident)
        count_stmt = select(func.count(Incident.id))
        if status:
            stmt = stmt.where(Incident.status == status)
            count_stmt = count_stmt.where(Incident.status == status)
        if severity:
            stmt = stmt.where(Incident.severity == severity)
            count_stmt = count_stmt.where(Incident.severity == severity)
        stmt = stmt.order_by(Incident.created_at.desc()).limit(limit).offset(offset)
        rows = list((await self.session.execute(stmt)).scalars().all())
        total = int(await self.session.scalar(count_stmt) or 0)
        return rows, total

    async def summary(self, incident: Incident) -> dict[str, Any]:
        investigation = (
            (
                await self.session.execute(
                    select(Investigation)
                    .where(Investigation.incident_id == incident.id)
                    .order_by(Investigation.started_at.desc())
                )
            )
            .scalars()
            .first()
        )
        return {
            "id": incident.id,
            "title": incident.title,
            "asset_urn": incident.asset_urn,
            "asset_name": urn_name(incident.asset_urn),
            "severity": incident.severity,
            "status": incident.status,
            "observed_value": incident.observed_value,
            "expected_value": incident.expected_value,
            "scenario_id": incident.scenario_id,
            "created_at": incident.created_at,
            "resolved_at": incident.resolved_at,
            "investigation_id": investigation.id if investigation else None,
            "investigation_status": investigation.status if investigation else None,
            "root_cause_summary": investigation.root_cause_summary if investigation else None,
            "confidence": float(investigation.confidence) if investigation else None,
        }

    async def detail(self, incident: Incident) -> dict[str, Any]:
        base = await self.summary(incident)
        investigation = (
            (
                await self.session.execute(
                    select(Investigation)
                    .where(Investigation.incident_id == incident.id)
                    .order_by(Investigation.started_at.desc())
                )
            )
            .scalars()
            .first()
        )
        verification = None
        if investigation:
            verification = (
                (
                    await self.session.execute(
                        select(Verification)
                        .where(Verification.investigation_id == investigation.id)
                        .order_by(Verification.verified_at.desc())
                    )
                )
                .scalars()
                .first()
            )
        memory = (
            (
                await self.session.execute(
                    select(MemoryReference)
                    .where(MemoryReference.incident_id == incident.id)
                    .order_by(MemoryReference.created_at.desc())
                )
            )
            .scalars()
            .first()
        )
        base.update(
            {
                "description": incident.description,
                "detected_at": incident.detected_at,
                "blocked_reason": incident.blocked_reason,
                "root_cause_pattern": investigation.root_cause_pattern if investigation else None,
                "blast_radius": (investigation.blast_radius or {}) if investigation else {},
                "verification_status": verification.status if verification else None,
                "datahub_source_mode": investigation.datahub_source_mode if investigation else None,
                "memory": {
                    "datahub_reference": memory.datahub_reference,
                    "pattern": memory.pattern,
                    "write_back_status": memory.write_back_status,
                    "source_mode": memory.source_mode,
                }
                if memory
                else None,
            }
        )
        return base
