"""Investigation lifecycle: creation, background execution, projection."""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.core.utils import to_iso
from app.core.utils import utcnow
from app.domain.enums import IncidentStatus, InvestigationPhase, InvestigationStatus
from app.models.database import session_scope
from app.models.tables import (
    Action,
    Evidence,
    Hypothesis,
    Incident,
    Investigation,
    InvestigationEvent,
    MemoryReference,
    Verification,
)
from app.services.datahub import get_provider
from app.services.scenario import ScenarioRuntime

logger = get_logger(__name__)

_tasks: dict[str, asyncio.Task] = {}


def get_task(investigation_id: str) -> asyncio.Task | None:
    return _tasks.get(investigation_id)


async def wait_for(investigation_id: str, timeout: float = 60.0) -> None:
    """Used by tests and the E2E harness."""
    task = _tasks.get(investigation_id)
    if task:
        await asyncio.wait_for(asyncio.shield(task), timeout=timeout)


async def run_investigation(investigation_id: str) -> None:
    """Background entrypoint. Owns its own DB session."""
    from app.agents.investigator import InvestigationAgent

    async with session_scope() as session:
        investigation = await session.get(Investigation, investigation_id)
        if investigation is None:  # pragma: no cover - defensive
            logger.error("investigation_missing", extra={"investigation_id": investigation_id})
            return
        incident = await session.get(Incident, investigation.incident_id)
        if incident is None:  # pragma: no cover - defensive
            logger.error("incident_missing", extra={"investigation_id": investigation_id})
            return
        provider = await get_provider()
        agent = InvestigationAgent(session, provider, incident, investigation)
        await agent.run()


class InvestigationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def start(
        self, incident_id: str, background: bool = True, force: bool = False
    ) -> Investigation:
        incident = await self.session.get(Incident, incident_id)
        if incident is None:
            raise NotFoundError(f"Incident {incident_id} not found")
        if incident.status == str(IncidentStatus.RESOLVED) and not force:
            raise ValidationError(
                "This incident is already resolved. Re-run it with force=true to "
                "investigate again."
            )

        running = (
            (
                await self.session.execute(
                    select(Investigation).where(
                        Investigation.incident_id == incident_id,
                        Investigation.status == str(InvestigationStatus.RUNNING),
                    )
                )
            )
            .scalars()
            .first()
        )
        if running is not None:
            alive = get_task(running.id) is not None and not get_task(running.id).done()
            if alive and not force:
                return running
            # Either the caller asked for a re-run, or the investigation is
            # marked RUNNING with nothing running it — which is what an API
            # restart mid-investigation leaves behind. Without this, the incident
            # is stuck forever behind a task that no longer exists.
            running.status = str(InvestigationStatus.FAILED)
            running.phase = str(InvestigationPhase.FAILED)
            running.completed_at = utcnow()
            running.error = (
                "Superseded by a new investigation."
                if alive
                else "Abandoned: no process was running this investigation "
                "(the API most likely restarted). Superseded by a new run."
            )
            await self.session.flush()

        if force:
            # A re-run has to face the same world as the first one. After a
            # simulated remediation the scenario is REMEDIATED, so an unreset
            # re-run would find healthy signals and correctly conclude nothing.
            scenario_id = incident.scenario_id
            if scenario_id:
                await ScenarioRuntime(self.session).reset(scenario_id)
            if incident.status != str(IncidentStatus.CREATED):
                incident.status = str(IncidentStatus.CREATED)
                incident.resolved_at = None
                incident.blocked_reason = None
                await self.session.flush()

        investigation = Investigation(
            incident_id=incident_id,
            status=str(InvestigationStatus.RUNNING),
            phase=str(InvestigationPhase.CREATED),
        )
        self.session.add(investigation)
        await self.session.flush()
        await self.session.commit()

        if background:
            task = asyncio.create_task(run_investigation(investigation.id))
            _tasks[investigation.id] = task
            task.add_done_callback(lambda t: _log_task_result(investigation.id, t))
        return investigation

    async def get(self, investigation_id: str) -> Investigation:
        investigation = await self.session.get(Investigation, investigation_id)
        if investigation is None:
            raise NotFoundError(f"Investigation {investigation_id} not found")
        return investigation

    async def latest_for_incident(self, incident_id: str) -> Investigation | None:
        return (
            (
                await self.session.execute(
                    select(Investigation)
                    .where(Investigation.incident_id == incident_id)
                    .order_by(Investigation.started_at.desc())
                )
            )
            .scalars()
            .first()
        )

    async def evidence(self, investigation_id: str) -> list[Evidence]:
        return list(
            (
                await self.session.execute(
                    select(Evidence)
                    .where(Evidence.investigation_id == investigation_id)
                    .order_by(Evidence.created_at.asc())
                )
            )
            .scalars()
            .all()
        )

    async def hypotheses(self, investigation_id: str) -> list[Hypothesis]:
        return list(
            (
                await self.session.execute(
                    select(Hypothesis)
                    .where(Hypothesis.investigation_id == investigation_id)
                    .order_by(Hypothesis.confidence.desc())
                )
            )
            .scalars()
            .all()
        )

    async def latest_action(self, investigation_id: str) -> Action | None:
        return (
            (
                await self.session.execute(
                    select(Action)
                    .where(Action.investigation_id == investigation_id)
                    .order_by(Action.created_at.desc())
                )
            )
            .scalars()
            .first()
        )

    async def latest_verification(self, investigation_id: str) -> Verification | None:
        return (
            (
                await self.session.execute(
                    select(Verification)
                    .where(Verification.investigation_id == investigation_id)
                    .order_by(Verification.verified_at.desc())
                )
            )
            .scalars()
            .first()
        )

    async def memory_reference(self, investigation_id: str) -> MemoryReference | None:
        return (
            (
                await self.session.execute(
                    select(MemoryReference)
                    .where(MemoryReference.investigation_id == investigation_id)
                    .order_by(MemoryReference.created_at.desc())
                )
            )
            .scalars()
            .first()
        )

    async def events_since(self, investigation_id: str, last_seq: int = 0) -> list[InvestigationEvent]:
        return list(
            (
                await self.session.execute(
                    select(InvestigationEvent)
                    .where(
                        InvestigationEvent.investigation_id == investigation_id,
                        InvestigationEvent.seq > last_seq,
                    )
                    .order_by(InvestigationEvent.seq.asc())
                )
            )
            .scalars()
            .all()
        )

    # -- projection -------------------------------------------------------
    async def build_output(self, investigation: Investigation) -> dict[str, Any]:
        evidence = await self.evidence(investigation.id)
        hypotheses = await self.hypotheses(investigation.id)
        action = await self.latest_action(investigation.id)
        verification = await self.latest_verification(investigation.id)
        memory = await self.memory_reference(investigation.id)
        primary = next((h for h in hypotheses if h.is_primary), None)

        return {
            "id": investigation.id,
            "incident_id": investigation.incident_id,
            "status": investigation.status,
            "phase": investigation.phase,
            "started_at": investigation.started_at,
            "completed_at": investigation.completed_at,
            "datahub_source_mode": investigation.datahub_source_mode,
            "reasoning_engine": investigation.reasoning_engine,
            "blocked_reason": investigation.blocked_reason,
            "error": investigation.error,
            "trust": investigation.trust_breakdown or {},
            "learning": {
                "memory_assisted": bool(investigation.memory_assisted),
                "matched_pattern": investigation.matched_pattern,
                "reused_from_investigation_id": investigation.reused_from_investigation_id,
                "remediation_source": investigation.remediation_source,
                "duration_ms": investigation.duration_ms,
                "tool_call_count": investigation.tool_call_count,
            },
            "context": investigation.context_summary or {},
            "root_cause": {
                "summary": investigation.root_cause_summary,
                "pattern": investigation.root_cause_pattern,
                "confidence": float(investigation.confidence or 0.0),
                "reasoning": primary.reasoning_summary if primary else "",
                "score_breakdown": primary.score_breakdown if primary else {},
                "evidence_ids": primary.supporting_evidence_ids if primary else [],
            },
            "causal_chain": investigation.causal_chain or [],
            "evidence": [serialize_evidence(e) for e in evidence],
            "hypotheses": [serialize_hypothesis(h) for h in hypotheses],
            "blast_radius": investigation.blast_radius or {},
            "remediation": serialize_action(action) if action else None,
            "verification": serialize_verification(verification) if verification else None,
            "memory": serialize_memory(memory) if memory else None,
        }


def _log_task_result(investigation_id: str, task: asyncio.Task) -> None:
    _tasks.pop(investigation_id, None)
    if task.cancelled():  # pragma: no cover
        logger.warning("investigation_task_cancelled", extra={"investigation_id": investigation_id})
        return
    exc = task.exception()
    if exc:  # pragma: no cover - the agent already handles its own errors
        logger.error(
            "investigation_task_error",
            extra={"investigation_id": investigation_id, "error": str(exc)},
        )


def serialize_evidence(row: Evidence) -> dict[str, Any]:
    return {
        "id": row.id,
        "type": row.type,
        "source": row.source,
        "source_system": row.source_system,
        "source_mode": row.source_mode,
        "asset_urn": row.asset_urn,
        "field_path": row.field_path,
        "observation": row.observation,
        "relevance": row.relevance,
        "observed_at": row.observed_at,
        "lineage_distance": row.lineage_distance,
        "metadata": row.extra or {},
    }


def serialize_hypothesis(row: Hypothesis) -> dict[str, Any]:
    return {
        "id": row.id,
        "pattern": row.pattern,
        "description": row.description,
        "confidence": float(row.confidence or 0.0),
        "status": row.status,
        "reasoning_summary": row.reasoning_summary,
        "score_breakdown": row.score_breakdown or {},
        "supporting_evidence_ids": row.supporting_evidence_ids or [],
        "contradicting_evidence_ids": row.contradicting_evidence_ids or [],
        "proposed_by": row.proposed_by,
        "is_primary": bool(row.is_primary),
    }


def serialize_action(row: Action) -> dict[str, Any]:
    plan = row.plan or {}
    return {
        "action_id": row.id,
        "investigation_id": row.investigation_id,
        "type": row.type,
        "status": row.status,
        "diagnosis": plan.get("diagnosis", row.description),
        "steps": plan.get("steps", []),
        "risk_level": row.risk_level,
        "requires_approval": bool(row.requires_approval),
        "execution_mode": row.execution_mode,
        "expected_result": plan.get("expected_result", ""),
        "rollback": plan.get("rollback", ""),
        "notify_owners": plan.get("notify_owners", []),
        "executed_at": row.executed_at,
        "result": row.result,
    }


def serialize_verification(row: Verification) -> dict[str, Any]:
    checks = row.checks or []
    passed = sum(1 for c in checks if c.get("status") == "PASS")
    return {
        "id": row.id,
        "investigation_id": row.investigation_id,
        "status": row.status,
        "summary": f"{passed} / {len(checks)} checks PASS",
        "passed": passed,
        "total": len(checks),
        "checks": checks,
        "expected_result": row.expected_result or {},
        "actual_result": row.actual_result or {},
        "verified_at": row.verified_at,
    }


def serialize_memory(row: MemoryReference) -> dict[str, Any]:
    return {
        "id": row.id,
        "incident_id": row.incident_id,
        "investigation_id": row.investigation_id,
        "datahub_reference": row.datahub_reference,
        "write_back_status": row.write_back_status,
        "source_mode": row.source_mode,
        "pattern": row.pattern,
        "root_cause": row.root_cause,
        "confidence": float(row.confidence or 0.0),
        "created_at": to_iso(row.created_at),
        "document": row.document or {},
    }
