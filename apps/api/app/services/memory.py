"""Institutional memory: write-back and previous incident retrieval.

Rule (DOCUMENT 05 - section 6): the LLM never writes to DataHub directly.
The agent produces a structured proposal, the application validates it against
IncidentMemoryDocument, and only then a controlled DataHub operation runs.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.utils import jaccard, tokenize, utcnow
from app.domain.enums import SourceMode
from app.models.tables import Incident, Investigation, MemoryReference
from app.schemas.memory import (
    IncidentMemoryDocument,
    KnowledgePatternSummary,
    MemoryWriteResponse,
    PreviousIncidentMatch,
)
from app.services.datahub.base import DataHubProvider

logger = get_logger(__name__)


class MemoryService:
    def __init__(self, session: AsyncSession, provider: DataHubProvider) -> None:
        self.session = session
        self.provider = provider

    # -- write-back -------------------------------------------------------
    def build_document(
        self,
        incident: Incident,
        investigation: Investigation,
        evidence: list[dict[str, Any]],
        remediation_steps: list[str],
        verification_status: str,
        verification_summary: str,
        hypotheses: list[dict[str, Any]] | None = None,
        occurrences: int = 1,
    ) -> IncidentMemoryDocument:
        blast = investigation.blast_radius or {}
        affected = [a.get("urn") for a in blast.get("affected_assets", []) if a.get("urn")]
        owners = [o.get("name") or o.get("urn") for o in blast.get("owners", [])]
        return IncidentMemoryDocument(
            incident_id=incident.id,
            investigation_id=investigation.id,
            title=incident.title,
            asset_urn=incident.asset_urn,
            symptom=(incident.description or incident.title)[:2000],
            pattern=investigation.root_cause_pattern or "UNKNOWN",
            root_cause=investigation.root_cause_summary or "",
            confidence=round(float(investigation.confidence or 0.0), 4),
            evidence_summary=[
                {
                    "type": item.get("type"),
                    "observation": item.get("observation"),
                    "asset_urn": item.get("asset_urn"),
                    "relevance": item.get("relevance"),
                    "source_system": item.get("source_system"),
                }
                for item in evidence[:20]
            ],
            causal_chain=[step.get("label", "") for step in (investigation.causal_chain or [])],
            # The rejected hypotheses travel with the document on purpose: the
            # next reader needs to know what was already ruled out, not only
            # what won.
            hypotheses_considered=[
                {
                    "pattern": item.get("pattern"),
                    "status": item.get("status"),
                    "confidence": item.get("confidence"),
                    "reasoning": (item.get("reasoning_summary") or "")[:400],
                }
                for item in (hypotheses or [])[:12]
            ],
            blast_radius={
                "total_affected_assets": blast.get("total_affected_assets", 0),
                "consumers": blast.get("consumers", 0),
                "owner_count": blast.get("owner_count", 0),
                "risk_level": blast.get("risk_level"),
                "counts": blast.get("counts", {}),
            },
            trust_score=round(float(investigation.trust_score or 0.0), 1),
            trust_decision=investigation.trust_decision or "UNKNOWN",
            affected_assets=affected[:200],
            owners=[o for o in owners if o][:50],
            remediation=remediation_steps[:20],
            verification=verification_status,
            verification_summary=verification_summary,
            resolved_at=utcnow(),
            source_mode=str(self.provider.source_mode),
            knowledge_pattern=KnowledgePatternSummary(
                pattern=investigation.root_cause_pattern or "UNKNOWN",
                symptoms=[(incident.title or "")[:200]],
                evidence_signature=sorted(
                    {
                        str(item.get("type"))
                        for item in evidence
                        if item.get("relevance") in {"HIGH", "MEDIUM"}
                    }
                ),
                resolution=remediation_steps[:20],
                confidence=round(float(investigation.confidence or 0.0), 4),
                occurrences=occurrences,
            ),
        )

    async def write_back(
        self,
        incident: Incident,
        investigation: Investigation,
        document: IncidentMemoryDocument,
    ) -> MemoryWriteResponse:
        try:
            payload = IncidentMemoryDocument.model_validate(document.model_dump()).model_dump(
                mode="json"
            )
        except PydanticValidationError as exc:
            return MemoryWriteResponse(
                status="INVALID_DOCUMENT",
                source_mode=str(self.provider.source_mode),
                error=str(exc)[:500],
            )

        affected = [urn for urn in document.affected_assets if urn != document.asset_urn]
        result = await self.provider.write_incident_memory(payload, affected)
        if not result.success:
            # The organisation still learned something, even if DataHub refused
            # the write. Keeping the record local means the next similar incident
            # is still recognised; dropping it would make the whole learning loop
            # depend on one token having tag-write permission, and would fail
            # silently — the incident resolves, and the memory quietly does not
            # exist. The status says plainly that DataHub was not enriched.
            self.session.add(
                MemoryReference(
                    incident_id=incident.id,
                    investigation_id=investigation.id,
                    datahub_reference="",
                    write_back_status="LOCAL_ONLY",
                    source_mode=str(self.provider.source_mode),
                    pattern=document.pattern,
                    root_cause=document.root_cause,
                    asset_urn=document.asset_urn,
                    symptom=document.symptom,
                    confidence=document.confidence,
                    document=payload,
                )
            )
            await self.session.flush()
            return MemoryWriteResponse(
                status="WRITE_BACK_FAILED",
                source_mode=str(self.provider.source_mode),
                error=result.error,
                document=document,
            )

        reference = result.data.get("reference")
        verified = False
        read_back = await self.provider.read_incident_memory(reference)
        verified = bool(read_back.success)

        record = MemoryReference(
            incident_id=incident.id,
            investigation_id=investigation.id,
            datahub_reference=str(reference),
            write_back_status="VERIFIED" if verified else "WRITTEN_UNVERIFIED",
            source_mode=str(self.provider.source_mode),
            pattern=document.pattern,
            root_cause=document.root_cause,
            asset_urn=document.asset_urn,
            symptom=document.symptom,
            confidence=document.confidence,
            document=payload,
        )
        self.session.add(record)
        await self.session.flush()

        return MemoryWriteResponse(
            status="WRITTEN",
            datahub_reference=str(reference),
            source_mode=str(self.provider.source_mode),
            verified=verified,
            document=document,
        )

    # -- retrieval --------------------------------------------------------
    async def find_previous_incidents(
        self,
        asset_urn: str | None = None,
        pattern: str | None = None,
        symptom: str | None = None,
        exclude_incident_id: str | None = None,
        limit: int = 5,
    ) -> list[PreviousIncidentMatch]:
        stmt = select(MemoryReference).order_by(MemoryReference.created_at.desc()).limit(200)
        rows = (await self.session.execute(stmt)).scalars().all()

        symptom_tokens = tokenize(symptom)
        matches: list[PreviousIncidentMatch] = []
        for row in rows:
            if exclude_incident_id and row.incident_id == exclude_incident_id:
                continue
            similarity = 0.0
            if pattern and row.pattern == pattern:
                similarity += 0.5
            if asset_urn:
                doc_assets = set(row.document.get("affected_assets", []) or [])
                doc_assets.add(row.asset_urn)
                if asset_urn in doc_assets:
                    similarity += 0.2
            similarity += 0.3 * jaccard(symptom_tokens, tokenize(row.symptom))
            if similarity <= 0.0:
                continue
            matches.append(
                PreviousIncidentMatch(
                    incident_id=row.incident_id,
                    reference=row.datahub_reference,
                    pattern=row.pattern,
                    root_cause=row.root_cause,
                    symptom=row.symptom,
                    confidence=row.confidence,
                    similarity=round(min(similarity, 1.0), 3),
                    remediation=list(row.document.get("remediation", []) or []),
                    asset_urn=row.asset_urn,
                    resolved_at=row.created_at,
                    source_mode=row.source_mode,
                )
            )

        # Also ask DataHub itself: knowledge may have been written by another
        # agent or another deployment of DATAFORENSIC.
        graph_result = await self.provider.search_incident_memory(
            pattern=pattern, asset_urn=asset_urn, limit=limit
        )
        if graph_result.success:
            known_references = {m.reference for m in matches}
            for item in graph_result.data.get("matches", []):
                reference = item.get("reference")
                if reference in known_references:
                    continue
                doc = item.get("document", {})
                if exclude_incident_id and doc.get("incident_id") == exclude_incident_id:
                    continue
                matches.append(
                    PreviousIncidentMatch(
                        incident_id=doc.get("incident_id"),
                        reference=reference,
                        pattern=doc.get("pattern"),
                        root_cause=doc.get("root_cause", ""),
                        symptom=doc.get("symptom", ""),
                        confidence=float(doc.get("confidence", 0.0) or 0.0),
                        similarity=0.5 if doc.get("pattern") == pattern else 0.2,
                        remediation=list(doc.get("remediation", []) or []),
                        asset_urn=doc.get("asset_urn"),
                        source_mode=str(self.provider.source_mode),
                    )
                )

        matches.sort(key=lambda m: m.similarity, reverse=True)
        return matches[:limit]
