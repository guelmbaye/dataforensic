"""Resolution service: remediation planning, controlled execution, verification,
write-back. Shared by the agent and by the REST API so the policy is enforced in
exactly one place (DOCUMENT 09 - section 12: the backend enforces the rule even
if the agent asks for execution).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ActionNotAllowedError, NotFoundError
from app.core.logging import get_logger
from app.core.utils import utcnow
from app.domain.action import RemediationPlan, RemediationStep, assert_executable
from app.domain.enums import (
    ActionStatus,
    ActionType,
    EvidenceType,
    ExecutionMode,
    IncidentStatus,
    Relevance,
    RiskLevel,
    VerificationStatus,
)
from app.domain.evidence import EvidenceItem
from app.domain.resolution import VerificationOutcome
from app.domain.state_machine import assert_incident_transition
from app.models.tables import (
    Action,
    Evidence,
    Hypothesis,
    Incident,
    Investigation,
    Verification,
)
from app.schemas.memory import MemoryWriteResponse
from app.services.datahub.base import DataHubProvider
from app.services.memory import MemoryService
from app.services.patterns import PatternLibrary
from app.services.remediation import build_remediation_plan
from app.services.scenario import ScenarioDefinition, ScenarioRuntime, get_registry
from app.services.verification import VerificationService

logger = get_logger(__name__)


def resolve_scenario(incident: Incident) -> ScenarioDefinition | None:
    registry = get_registry()
    return registry.get(incident.scenario_id) or registry.for_asset(incident.asset_urn)


def plan_from_dict(payload: dict[str, Any]) -> RemediationPlan:
    """Rebuild a plan from its stored JSON form.

    Used both to re-execute an action and to replay a plan that a previous
    investigation proved works, which is what makes a knowledge pattern
    actionable rather than merely descriptive.
    """
    return RemediationPlan(
        diagnosis=payload.get("diagnosis", ""),
        steps=[
            RemediationStep(
                id=step["id"],
                title=step["title"],
                description=step.get("description", ""),
                risk=RiskLevel(step.get("risk", "LOW")),
                effect=step.get("effect"),
                executed=bool(step.get("executed")),
                result=step.get("result"),
            )
            for step in payload.get("steps", [])
        ],
        expected_result=payload.get("expected_result", ""),
        rollback=payload.get("rollback", ""),
        execution_mode=ExecutionMode(payload.get("execution_mode", "SIMULATED")),
        notify_owners=payload.get("notify_owners", []),
    )


def plan_from_action(action: Action) -> RemediationPlan:
    return plan_from_dict(action.plan or {})


class ResolutionService:
    def __init__(self, session: AsyncSession, provider: DataHubProvider) -> None:
        self.session = session
        self.provider = provider
        self.runtime = ScenarioRuntime(session)
        self.verification = VerificationService(session, provider)
        self.memory = MemoryService(session, provider)

    # -- planning ---------------------------------------------------------
    async def create_plan(
        self,
        investigation: Investigation,
        incident: Incident,
        evidence_items: list[EvidenceItem] | None = None,
        scenario: ScenarioDefinition | None = None,
        reuse_plan: dict[str, Any] | None = None,
        reuse_source: str | None = None,
    ) -> Action:
        scenario = scenario or resolve_scenario(incident)
        items = evidence_items
        if items is None:
            items = [
                EvidenceItem(
                    id=row.id,
                    type=EvidenceType(row.type),
                    observation=row.observation,
                    source=row.source,
                    asset_urn=row.asset_urn,
                    field_path=row.field_path,
                    relevance=Relevance(row.relevance),
                    metadata=row.extra or {},
                )
                for row in (
                    await self.session.execute(
                        select(Evidence).where(Evidence.investigation_id == investigation.id)
                    )
                )
                .scalars()
                .all()
            ]

        owners = (investigation.blast_radius or {}).get("owners", [])

        if reuse_plan and reuse_plan.get("steps"):
            # A plan that was already verified against this failure mode beats a
            # freshly generated one: it is the same organisation's own answer,
            # and it carries the step effects that make the simulation runnable.
            plan = plan_from_dict(reuse_plan)
            payload = plan.to_public()
            payload["derived_from"] = reuse_source or "knowledge_pattern"
            action = Action(
                investigation_id=investigation.id,
                type=str(
                    ActionType.EXECUTE_SIMULATED
                    if plan.execution_mode is ExecutionMode.SIMULATED
                    else ActionType.RECOMMEND
                ),
                description=plan.diagnosis,
                risk_level=str(plan.risk),
                execution_mode=str(plan.execution_mode),
                status=str(ActionStatus.PLANNED),
                requires_approval=plan.requires_approval,
                plan=payload,
            )
            self.session.add(action)
            await self.session.flush()
            return action

        plan = build_remediation_plan(
            pattern=investigation.root_cause_pattern,
            evidence=items,
            asset_urn=incident.asset_urn,
            owners=owners,
            scenario=scenario,
        )
        action = Action(
            investigation_id=investigation.id,
            type=str(
                ActionType.EXECUTE_SIMULATED
                if plan.execution_mode is ExecutionMode.SIMULATED
                else ActionType.RECOMMEND
            ),
            description=plan.diagnosis,
            risk_level=str(plan.risk),
            execution_mode=str(plan.execution_mode),
            status=str(ActionStatus.PLANNED),
            requires_approval=plan.requires_approval,
            plan={**plan.to_public(), "derived_from": "generated"},
        )
        self.session.add(action)
        await self.session.flush()
        return action

    # -- execution --------------------------------------------------------
    async def execute_action(
        self,
        action: Action,
        approved: bool = False,
        approved_by: str | None = None,
    ) -> dict[str, Any]:
        if action.status == str(ActionStatus.EXECUTED):
            return action.result or {"status": "ALREADY_EXECUTED"}

        plan = plan_from_action(action)
        assert_executable(
            ActionType(action.type),
            RiskLevel(action.risk_level),
            ExecutionMode(action.execution_mode),
            approved=approved or not action.requires_approval,
        )

        investigation = await self.session.get(Investigation, action.investigation_id)
        if investigation is None:
            raise NotFoundError(f"Investigation {action.investigation_id} not found")
        incident = await self.session.get(Incident, investigation.incident_id)
        if incident is None:
            raise NotFoundError(f"Incident {investigation.incident_id} not found")

        scenario = resolve_scenario(incident)
        if scenario is None:
            raise ActionNotAllowedError(
                "No controlled scenario environment is attached to this incident; "
                "execution is refused and the plan stays a recommendation.",
                details={"incident_id": incident.id},
            )

        step_ids = [step.id for step in plan.steps]
        outcome = await self.runtime.apply_remediation(scenario, step_ids)
        for step in plan.steps:
            step.executed = True
            step.result = {"applied": True, "environment": "SIMULATION"}

        action.plan = plan.to_public()
        action.status = str(ActionStatus.EXECUTED)
        action.approved_by = approved_by
        action.approved_at = utcnow() if approved else None
        action.executed_at = utcnow()
        action.result = {
            "environment": "SIMULATION",
            "scenario_id": scenario.id,
            "scenario_state": outcome["state"],
            "applied_steps": step_ids,
            "note": "Controlled simulation only - no production system was modified.",
        }

        if incident.status in {str(IncidentStatus.CREATED), str(IncidentStatus.INVESTIGATING)}:
            assert_incident_transition(
                IncidentStatus(incident.status), IncidentStatus.REMEDIATING
            )
            incident.status = str(IncidentStatus.REMEDIATING)
        await self.session.flush()
        return action.result

    # -- verification -----------------------------------------------------
    async def verify(
        self, investigation: Investigation, incident: Incident
    ) -> tuple[Verification, VerificationOutcome]:
        scenario = resolve_scenario(incident)
        if incident.status in {
            str(IncidentStatus.INVESTIGATING),
            str(IncidentStatus.REMEDIATING),
        }:
            incident.status = str(IncidentStatus.VERIFYING)

        record, outcome = await self.verification.run(
            investigation, incident.asset_urn, scenario, incident.expected_value
        )

        if outcome.status is VerificationStatus.PASS:
            assert_incident_transition(IncidentStatus(incident.status), IncidentStatus.RESOLVED)
            incident.status = str(IncidentStatus.RESOLVED)
            incident.resolved_at = utcnow()
        else:
            incident.status = str(IncidentStatus.INVESTIGATING)
        await self.session.flush()
        return record, outcome

    # -- write-back -------------------------------------------------------
    async def write_memory(
        self, investigation: Investigation, incident: Incident
    ) -> MemoryWriteResponse:
        if incident.status != str(IncidentStatus.RESOLVED):
            raise ActionNotAllowedError(
                "Incident memory is only written after a verified resolution",
                details={"incident_status": incident.status},
            )
        evidence_rows = (
            (
                await self.session.execute(
                    select(Evidence).where(Evidence.investigation_id == investigation.id)
                )
            )
            .scalars()
            .all()
        )
        evidence = [
            {
                "type": row.type,
                "observation": row.observation,
                "asset_urn": row.asset_urn,
                "relevance": row.relevance,
                "source_system": row.source_system,
            }
            for row in evidence_rows
        ]
        action = (
            (
                await self.session.execute(
                    select(Action)
                    .where(Action.investigation_id == investigation.id)
                    .order_by(Action.created_at.desc())
                )
            )
            .scalars()
            .first()
        )
        steps = [step["title"] for step in ((action.plan or {}).get("steps", []) if action else [])]
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
        summary = ""
        if verification:
            passed = sum(1 for c in verification.checks if c.get("status") == "PASS")
            summary = f"{passed} / {len(verification.checks)} checks PASS"

        hypothesis_rows = (
            (
                await self.session.execute(
                    select(Hypothesis)
                    .where(Hypothesis.investigation_id == investigation.id)
                    .order_by(Hypothesis.confidence.desc())
                )
            )
            .scalars()
            .all()
        )
        hypotheses = [
            {
                "pattern": row.pattern,
                "status": row.status,
                "confidence": float(row.confidence or 0.0),
                "reasoning_summary": row.reasoning_summary,
            }
            for row in hypothesis_rows
        ]

        library = PatternLibrary(self.session)
        known = await library.get(investigation.root_cause_pattern or "")

        document = self.memory.build_document(
            incident=incident,
            investigation=investigation,
            evidence=evidence,
            remediation_steps=steps,
            verification_status=verification.status if verification else "UNKNOWN",
            verification_summary=summary,
            hypotheses=hypotheses,
            occurrences=(known.occurrences if known else 0) + 1,
        )
        response = await self.memory.write_back(incident, investigation, document)

        # The pattern is recorded whether or not DataHub accepted the write.
        # What the organisation learned and what got persisted to the catalog are
        # two different claims, and conflating them meant a missing tag-write
        # permission silently erased the entire learning loop.
        await library.record(
            investigation=investigation,
            symptom=incident.title,
            evidence=evidence,
            remediation_plan=(action.plan if action else None),
            affected_assets=document.affected_assets,
            verification_passed=(verification.status if verification else "") == "PASS",
            written_to_datahub=response.status == "WRITTEN",
        )
        return response
