"""The DATAFORENSIC investigation agent.

Golden rule (DOCUMENT 04 - section 21):
    Evidence before inference.
    Inference before action.
    Action before verification.
    Verification before resolution.
    Resolution before memory.
"""

from __future__ import annotations

from time import perf_counter
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.causal_chain import build_causal_chain, summarize_root_cause
from app.agents.context import ContextBuilder, InvestigationContext
from app.agents.evidence_collector import EvidenceCollector
from app.agents.hypothesis_engine import HypothesisEngine
from app.agents.llm import LLMReasoner
from app.agents.scoring import build_reasoning_summary, classify, score_hypothesis
from app.agents.tools import AgentToolbox
from app.agents.trust import compute_trust_score
from app.config import settings
from app.core.errors import AppError, DataHubUnavailableError
from app.core.logging import get_logger
from app.core.utils import to_iso, utcnow
from app.domain.enums import (
    EvidenceType,
    HypothesisStatus,
    IncidentStatus,
    InvestigationPhase,
    InvestigationStatus,
    Relevance,
    SourceSystem,
    VerificationStatus,
)
from app.domain.evidence import EvidenceItem
from app.domain.hypothesis import HypothesisCandidate
from app.domain.state_machine import assert_incident_transition
from app.models.tables import Evidence, Hypothesis, Incident, Investigation, ToolCallLog
from app.services.blast_radius import calculate_blast_radius
from app.services.datahub.base import DataHubProvider
from app.services.events import InvestigationEventWriter
from app.services.memory import MemoryService
from app.services.patterns import PatternLibrary
from app.services.resolution import ResolutionService, resolve_scenario
from app.services.scenario import ScenarioRuntime

logger = get_logger(__name__)


class InvestigationAgent:
    def __init__(
        self,
        session: AsyncSession,
        provider: DataHubProvider,
        incident: Incident,
        investigation: Investigation,
    ) -> None:
        self.session = session
        self.provider = provider
        self.incident = incident
        self.investigation = investigation
        self.events = InvestigationEventWriter(session, investigation.id)
        self.toolbox = AgentToolbox(session, provider, investigation.id, self._emit)
        self.runtime = ScenarioRuntime(session)
        self.scenario = resolve_scenario(incident)
        self.memory = MemoryService(session, provider)
        self.resolution = ResolutionService(session, provider)
        self.llm = LLMReasoner()
        self.patterns = PatternLibrary(session)
        self.context: InvestigationContext | None = None
        self.evidence: list[EvidenceItem] = []
        self.candidates: list[HypothesisCandidate] = []
        self.previous_matches: list[Any] = []
        self.pattern_matches: list[Any] = []
        self.started_monotonic: float = 0.0

    # -- infrastructure ---------------------------------------------------
    async def _emit(
        self,
        event: str,
        message: str,
        payload: dict[str, Any] | None = None,
        level: str = "info",
    ) -> None:
        await self.events.emit(event, message, payload or {}, level=level)

    async def _phase(self, phase: InvestigationPhase) -> None:
        self.investigation.phase = str(phase)
        await self.session.flush()

    async def _block(self, reason: str, details: dict[str, Any] | None = None) -> None:
        self.investigation.status = str(InvestigationStatus.BLOCKED)
        self.investigation.phase = str(InvestigationPhase.BLOCKED)
        self.investigation.blocked_reason = reason
        self.investigation.completed_at = utcnow()
        if self.incident.status != str(IncidentStatus.RESOLVED):
            self.incident.status = str(IncidentStatus.BLOCKED)
            self.incident.blocked_reason = reason
        await self.session.flush()
        await self._emit(
            "investigation_blocked",
            reason,
            {"reason": reason, **(details or {})},
        )

    # -- main loop --------------------------------------------------------
    async def run(self) -> None:
        self.started_monotonic = perf_counter()
        try:
            await self._emit(
                "investigation_started",
                f"Investigation started for '{self.incident.title}'",
                {
                    "incident_id": self.incident.id,
                    "asset_urn": self.incident.asset_urn,
                    "severity": self.incident.severity,
                    "scenario_id": self.scenario.id if self.scenario else None,
                    "datahub_source_mode": str(self.provider.source_mode),
                    "reasoning_engine": self.llm.engine_name,
                },
            )
            self.investigation.datahub_source_mode = str(self.provider.source_mode)
            self.investigation.reasoning_engine = self.llm.engine_name
            assert_incident_transition(
                IncidentStatus(self.incident.status), IncidentStatus.INVESTIGATING
            )
            self.incident.status = str(IncidentStatus.INVESTIGATING)

            previous = await self._recall_previous_incidents()
            await self._load_context()
            await self._collect_evidence(previous)
            await self._build_hypotheses()

            primary = await self._select_root_cause()
            if primary is None:
                return

            await self._impact_analysis(primary)
            action = await self._plan_remediation()
            executed = await self._execute_remediation(action)
            if not executed:
                await self._complete(
                    "Remediation plan requires human approval before execution."
                )
                return

            resolved = await self._verify()
            if resolved:
                await self._write_memory()
            await self._complete()

        except DataHubUnavailableError as exc:
            logger.warning("investigation_blocked_datahub", extra={"error": exc.message})
            await self._block(
                f"Required DataHub context unavailable: {exc.message}", exc.details
            )
        except AppError as exc:
            logger.error("investigation_failed_app_error", extra={"error": exc.message})
            await self._fail(exc.message)
        except Exception as exc:  # noqa: BLE001
            logger.exception("investigation_failed")
            await self._fail(f"{exc.__class__.__name__}: {exc}")

    async def _record_metrics(self) -> None:
        """Measured, not asserted.

        The claim that memory makes the next investigation cheaper is only worth
        making if the cost is counted, so wall-clock time and the number of tool
        calls are recorded on every run, including the ones with no precedent.
        """
        self.investigation.duration_ms = int((perf_counter() - self.started_monotonic) * 1000)
        self.investigation.tool_call_count = int(
            await self.session.scalar(
                select(func.count(ToolCallLog.id)).where(
                    ToolCallLog.investigation_id == self.investigation.id
                )
            )
            or 0
        )

    async def _fail(self, message: str) -> None:
        self.investigation.status = str(InvestigationStatus.FAILED)
        self.investigation.phase = str(InvestigationPhase.FAILED)
        self.investigation.error = message
        self.investigation.completed_at = utcnow()
        await self._record_metrics()
        await self.session.flush()
        await self._emit("investigation_failed", message, {"error": message}, level="error")

    async def _complete(self, note: str | None = None) -> None:
        self.investigation.status = str(InvestigationStatus.COMPLETED)
        self.investigation.completed_at = utcnow()
        await self._record_metrics()
        await self.session.flush()
        await self._emit(
            "investigation_completed",
            note or "Investigation completed",
            {
                "incident_status": self.incident.status,
                "root_cause": self.investigation.root_cause_summary,
                "confidence": self.investigation.confidence,
                "phase": self.investigation.phase,
                "note": note,
            },
        )

    # -- steps ------------------------------------------------------------
    async def _recall_previous_incidents(self) -> list[Any]:
        """Consult the organisational memory before doing any work.

        This is a prior, not an answer. Whatever comes back, the agent still
        gathers its own evidence and still scores every hypothesis: a pattern
        that does not fit simply fails to be confirmed.
        """
        symptom = f"{self.incident.title} {self.incident.description}"
        matches = await self.memory.find_previous_incidents(
            asset_urn=self.incident.asset_urn,
            symptom=symptom,
            exclude_incident_id=self.incident.id,
            limit=3,
        )
        self.previous_matches = matches

        self.pattern_matches = await self.patterns.match(
            symptom=symptom, asset_urn=self.incident.asset_urn, limit=3
        )
        self.investigation.memory_assisted = bool(matches or self.pattern_matches)

        await self._emit(
            "previous_incidents_checked",
            (
                f"{len(matches)} similar past investigation(s) found in institutional memory"
                if matches
                else "No similar past investigation found; running a fresh investigation"
            ),
            {
                "matches": [m.model_dump(mode="json") for m in matches],
                "count": len(matches),
            },
        )

        if self.pattern_matches:
            best = self.pattern_matches[0]
            self.investigation.matched_pattern = best.pattern
            await self._emit(
                "known_pattern_detected",
                (
                    f"Known pattern {best.pattern} matches at {best.similarity:.0%} "
                    f"(seen {best.occurrences}x, {best.verified_resolutions} verified "
                    f"resolution(s)). Treated as a lead, not a conclusion."
                ),
                {
                    "pattern": best.pattern,
                    "similarity": round(best.similarity, 4),
                    "occurrences": best.occurrences,
                    "verified_resolutions": best.verified_resolutions,
                    "recommended_remediation": best.recommended_remediation,
                    "match_reasons": best.match_reasons,
                    "candidates": [m.model_dump(mode="json") for m in self.pattern_matches],
                },
            )
        await self.session.flush()
        return matches

    async def _load_context(self) -> None:
        await self._phase(InvestigationPhase.CONTEXT_LOADING)
        incident_time = self.incident.detected_at or (
            self.scenario.incident_time if self.scenario else None
        )
        builder = ContextBuilder(self.toolbox, self._emit)  # type: ignore[arg-type]
        self.context = await builder.build(
            self.incident.asset_urn,
            incident_time,
            depth=settings.agent_lineage_depth,
            lookback_minutes=settings.agent_lookback_minutes,
        )
        self.investigation.context_summary = self.context.summary()
        await self.session.flush()

    async def _collect_evidence(self, previous: list[Any]) -> None:
        await self._phase(InvestigationPhase.INVESTIGATING)
        assert self.context is not None
        collector = EvidenceCollector(
            self.context, self.runtime, self.scenario, self.provider.source_mode
        )
        items = await collector.collect(
            self.incident.observed_value, self.incident.expected_value
        )

        for match in previous:
            items.append(
                EvidenceItem(
                    type=EvidenceType.HISTORICAL_INCIDENT,
                    observation=(
                        f"A previous investigation on a similar symptom concluded: "
                        f"{match.root_cause} (pattern {match.pattern}, "
                        f"similarity {match.similarity:.0%})"
                    ),
                    source=f"incident-memory:{match.reference}",
                    source_system=SourceSystem.DATAHUB,
                    source_mode=self.provider.source_mode,
                    asset_urn=match.asset_urn,
                    relevance=Relevance.MEDIUM,
                    observed_at=match.resolved_at,
                    lineage_distance=self.context.distance_to_target(match.asset_urn or ""),
                    metadata={
                        "pattern": match.pattern,
                        "similarity": match.similarity,
                        "reference": match.reference,
                    },
                )
            )

        self.evidence = items
        for item in items:
            self.session.add(
                Evidence(
                    id=item.id,
                    investigation_id=self.investigation.id,
                    type=str(item.type),
                    source=item.source,
                    source_system=str(item.source_system),
                    source_mode=str(item.source_mode),
                    asset_urn=item.asset_urn,
                    field_path=item.field_path,
                    observation=item.observation,
                    relevance=str(item.relevance),
                    observed_at=item.observed_at,
                    lineage_distance=item.lineage_distance,
                    extra=item.metadata,
                )
            )
        await self.session.flush()

        for item in items:
            await self._emit(
                "evidence_found",
                item.observation,
                {
                    "evidence_id": item.id,
                    "type": str(item.type),
                    "relevance": str(item.relevance),
                    "asset_urn": item.asset_urn,
                    "source": item.source,
                    "source_system": str(item.source_system),
                    "observed_at": to_iso(item.observed_at),
                },
            )
        await self._emit(
            "evidence_collected",
            f"{len(items)} evidence signal(s) collected",
            {
                "count": len(items),
                "by_type": {
                    str(t): sum(1 for e in items if e.type is t)
                    for t in {e.type for e in items}
                },
            },
        )

    async def _build_hypotheses(self) -> None:
        await self._phase(InvestigationPhase.HYPOTHESIS_TESTING)
        assert self.context is not None
        engine = HypothesisEngine(self.context, settings.agent_lookback_minutes)
        candidates = engine.generate(self.evidence)

        candidates.extend(await self._llm_candidates(candidates))

        for candidate in candidates:
            await self._emit(
                "hypothesis_created",
                f"Hypothesis: {candidate.description}",
                {
                    "hypothesis_id": candidate.id,
                    "pattern": candidate.pattern,
                    "supporting": len(candidate.supporting),
                    "contradicting": len(candidate.contradicting),
                    "proposed_by": candidate.proposed_by,
                },
            )

        self.candidates = engine.score(candidates)

        for candidate in self.candidates:
            self.session.add(
                Hypothesis(
                    id=candidate.id,
                    investigation_id=self.investigation.id,
                    pattern=candidate.pattern,
                    description=candidate.description,
                    confidence=candidate.confidence,
                    status=str(candidate.status),
                    reasoning_summary=candidate.reasoning_summary,
                    score_breakdown=candidate.score_breakdown,
                    supporting_evidence_ids=[e.id for e in candidate.supporting],
                    contradicting_evidence_ids=[e.id for e in candidate.contradicting],
                    proposed_by=candidate.proposed_by,
                )
            )
            await self.session.flush()
            await self._emit(
                "hypothesis_scored",
                f"{candidate.pattern}: {candidate.confidence:.0%} ({candidate.status})",
                {
                    "hypothesis_id": candidate.id,
                    "pattern": candidate.pattern,
                    "confidence": round(candidate.confidence, 4),
                    "status": str(candidate.status),
                    "score_breakdown": candidate.score_breakdown,
                    "reasoning": candidate.reasoning_summary,
                },
            )

    async def _llm_candidates(
        self, existing: list[HypothesisCandidate]
    ) -> list[HypothesisCandidate]:
        if not self.llm.enabled or not self.context:
            return []
        proposals = await self.llm.propose_hypotheses(
            self.context.summary(),
            [e.to_public() for e in self.evidence],
            [c.pattern for c in existing],
        )
        by_id = {e.id: e for e in self.evidence}
        extra: list[HypothesisCandidate] = []
        for proposal in proposals:
            supporting = [
                by_id[eid]
                for eid in proposal.get("supporting_evidence_ids", [])
                if eid in by_id
            ]
            if not supporting:
                # Guardrail: no unsupported claim ever enters the investigation.
                await self._emit(
                    "hypothesis_rejected",
                    f"LLM proposal '{proposal.get('pattern')}' discarded: no valid evidence cited",
                    {"pattern": proposal.get("pattern"), "reason": "no_valid_evidence"},
                    level="warning",
                )
                continue
            extra.append(
                HypothesisCandidate(
                    pattern=str(proposal.get("pattern", "LLM_PROPOSAL")).upper(),
                    description=str(proposal.get("description", ""))[:500],
                    supporting=supporting,
                    contradicting=[
                        by_id[eid]
                        for eid in proposal.get("contradicting_evidence_ids", [])
                        if eid in by_id
                    ],
                    proposed_by="llm",
                )
            )
        return extra

    async def _select_root_cause(self) -> HypothesisCandidate | None:
        assert self.context is not None
        primary = HypothesisEngine.primary(self.candidates)

        if primary is None:
            best = self.candidates[0] if self.candidates else None
            await self._block(
                "No hypothesis reaches the evidence threshold required to assert a root cause. "
                "Human investigation is required.",
                {
                    "best_candidate": best.pattern if best else None,
                    "best_confidence": round(best.confidence, 4) if best else 0.0,
                },
            )
            return None

        cause_evidence = [
            e for e in primary.supporting if e.type is not EvidenceType.METRIC_CHANGE
        ]
        if not cause_evidence:
            await self._block(
                "The leading hypothesis is only supported by the reported symptom; "
                "no causal evidence was found.",
                {"pattern": primary.pattern},
            )
            return None

        summary = summarize_root_cause(primary, self.context)
        chain = build_causal_chain(primary, self.context)

        narrative = await self.llm.narrate(
            summary, chain, [e.to_public() for e in primary.supporting]
        )
        if narrative:
            primary.reasoning_summary = f"{primary.reasoning_summary} {narrative}"
            row = await self.session.get(Hypothesis, primary.id)
            if row:
                row.reasoning_summary = primary.reasoning_summary

        self.investigation.root_cause_summary = summary
        self.investigation.root_cause_pattern = primary.pattern
        self.investigation.confidence = primary.confidence
        self.investigation.causal_chain = chain
        row = await self.session.get(Hypothesis, primary.id)
        if row:
            row.is_primary = True
        await self._phase(InvestigationPhase.ROOT_CAUSE_IDENTIFIED)

        await self._score_trust(primary)

        await self._emit(
            "root_cause_identified",
            f"{primary.pattern}: {summary}",
            {
                "pattern": primary.pattern,
                "summary": summary,
                "confidence": round(primary.confidence, 4),
                "status": str(primary.status),
                "score_breakdown": primary.score_breakdown,
                "evidence_ids": [e.id for e in primary.supporting],
                "causal_chain": chain,
            },
        )
        return primary

    async def _score_trust(self, primary: HypothesisCandidate) -> None:
        """How grounded was this investigation, independent of what it concluded."""
        assert self.context is not None
        trust = compute_trust_score(
            self.context, self.evidence, primary, self.previous_matches
        )
        self.investigation.trust_score = trust.score
        self.investigation.trust_decision = str(trust.decision)
        self.investigation.trust_breakdown = trust.to_public()
        await self.session.flush()
        await self._emit(
            "trust_score_computed",
            f"Trust score {trust.score:.0f} / 100 - {str(trust.decision).replace('_', ' ').lower()}",
            trust.to_public(),
            level="info" if trust.score >= 65 else "warning",
        )

    async def _impact_analysis(self, primary: HypothesisCandidate) -> None:
        await self._phase(InvestigationPhase.IMPACT_ANALYSIS)
        assert self.context is not None

        origin_urn = self._corruption_entry(primary)
        lineage = self.context.lineage
        if origin_urn != self.context.asset_urn:
            downstream = await self.toolbox.get_lineage(
                origin_urn, "DOWNSTREAM", settings.agent_lineage_depth
            )
            if downstream.success:
                lineage = downstream.data

        blast = calculate_blast_radius(
            lineage, origin_urn, self.context.asset_name(origin_urn)
        )
        self.investigation.blast_radius = blast
        await self.session.flush()
        await self._emit(
            "blast_radius_calculated",
            (
                f"{blast['total_affected_assets']} affected asset(s), "
                f"{blast['consumers']} consumer(s), {blast['owner_count']} owner(s) - "
                f"risk {blast['risk_level']}"
            ),
            blast,
        )

    def _corruption_entry(self, primary: HypothesisCandidate) -> str:
        """Where the defect enters the graph: the closest implicated upstream asset."""
        assert self.context is not None
        if self.scenario and self.scenario.corruption_entry_urn:
            if self.context.node(self.scenario.corruption_entry_urn) or True:
                return self.scenario.corruption_entry_urn
        implicated = [
            e
            for e in primary.supporting
            if e.asset_urn
            and e.lineage_distance is not None
            and e.type
            in {EvidenceType.SCHEMA_CHANGE, EvidenceType.QUALITY_ANOMALY, EvidenceType.PIPELINE_CHANGE}
        ]
        if not implicated:
            return self.context.asset_urn
        closest = min(implicated, key=lambda e: e.lineage_distance or 99)
        return closest.asset_urn or self.context.asset_urn

    async def _plan_remediation(self):
        reuse_plan, reuse_source = await self._known_good_plan()
        action = await self.resolution.create_plan(
            self.investigation,
            self.incident,
            self.evidence,
            self.scenario,
            reuse_plan=reuse_plan,
            reuse_source=reuse_source,
        )
        self.investigation.remediation_source = (action.plan or {}).get("derived_from")
        if reuse_plan:
            await self._emit(
                "remediation_reused",
                (
                    f"Reusing the remediation that was verified the last time "
                    f"{self.investigation.root_cause_pattern} occurred, instead of "
                    "generating a new one."
                ),
                {
                    "pattern": self.investigation.root_cause_pattern,
                    "source": reuse_source,
                    "steps": [s.get("title") for s in reuse_plan.get("steps", [])],
                },
            )
        await self._phase(InvestigationPhase.REMEDIATION_PLANNED)
        await self._emit(
            "remediation_planned",
            f"Remediation plan ready ({len(action.plan.get('steps', []))} steps, risk {action.risk_level})",
            {"action_id": action.id, **action.plan},
        )
        return action

    async def _known_good_plan(self) -> tuple[dict[str, Any] | None, str | None]:
        """The plan a previous, verified investigation used for this same pattern.

        Only reused when the pattern the agent just concluded matches the one the
        library knows: recognising a pattern early must never let it choose the
        fix for a different conclusion.
        """
        pattern = self.investigation.root_cause_pattern
        if not pattern:
            return None, None
        row = await self.patterns.get(pattern)
        if row is None or row.verified_resolutions < 1:
            return None, None
        plan = row.resolution_plan or {}
        if not plan.get("steps"):
            return None, None
        self.investigation.reused_from_investigation_id = next(
            (
                entry.get("investigation_id")
                for entry in (row.occurrences_log or [])
                if entry.get("verified")
            ),
            None,
        )
        return plan, f"knowledge_pattern:{pattern}"

    async def _execute_remediation(self, action) -> bool:
        if action.requires_approval:
            await self._emit(
                "approval_required",
                "The remediation plan requires explicit human approval before execution",
                {
                    "action_id": action.id,
                    "risk_level": action.risk_level,
                    "execution_mode": action.execution_mode,
                },
                level="warning",
            )
            return False
        if self.scenario is None:
            await self._emit(
                "remediation_recommended",
                "No controlled environment attached: the plan stays a recommendation",
                {"action_id": action.id},
                level="warning",
            )
            return False

        result = await self.resolution.execute_action(action, approved=False)
        await self._phase(InvestigationPhase.REMEDIATION_EXECUTED)
        await self._emit(
            "remediation_executed",
            "Remediation executed in the controlled simulation environment",
            {"action_id": action.id, **result},
        )
        return True

    async def _verify(self) -> bool:
        await self._phase(InvestigationPhase.VERIFYING)
        await self._emit(
            "verification_started", "Verifying the resolution independently", {}
        )
        record, outcome = await self.resolution.verify(self.investigation, self.incident)
        await self._emit(
            "verification_completed",
            f"Verification {outcome.status}: {outcome.passed} / {outcome.total} checks PASS",
            {"verification_id": record.id, **outcome.to_public()},
            level="info" if outcome.status is VerificationStatus.PASS else "warning",
        )
        if outcome.status is VerificationStatus.PASS:
            await self._phase(InvestigationPhase.RESOLVED)
            await self._emit(
                "incident_resolved",
                "Incident RESOLVED after successful verification",
                {"incident_id": self.incident.id, "status": self.incident.status},
            )
            return True
        await self._emit(
            "resolution_failed",
            "Verification failed: the incident stays open and the investigation is reopened",
            {"status": str(outcome.status), "checks": outcome.to_public()["checks"]},
            level="warning",
        )
        return False

    async def _write_memory(self) -> None:
        # Recorded before the write-back so the knowledge pattern captures the
        # real cost of this investigation rather than zeros.
        await self._record_metrics()
        response = await self.resolution.write_memory(self.investigation, self.incident)
        if response.status != "WRITTEN":
            await self._emit(
                "memory_write_failed",
                f"Write-back failed: {response.error}",
                {"status": response.status, "error": response.error},
                level="error",
            )
            return
        await self._phase(InvestigationPhase.MEMORY_WRITTEN)
        await self._emit(
            "memory_written",
            f"Investigation knowledge written back to DataHub ({response.datahub_reference})",
            {
                "datahub_reference": response.datahub_reference,
                "verified": response.verified,
                "source_mode": response.source_mode,
                "pattern": self.investigation.root_cause_pattern,
                "document": response.document.model_dump(mode="json") if response.document else None,
            },
        )
