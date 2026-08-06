from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.domain.enums import (
    EvidenceType,
    HypothesisStatus,
    InvestigationPhase,
    InvestigationStatus,
    Relevance,
)


class InvestigationStartResponse(BaseModel):
    investigation_id: str
    incident_id: str
    status: InvestigationStatus
    stream_url: str


class EvidenceOut(BaseModel):
    id: str
    type: EvidenceType
    source: str
    source_system: str
    source_mode: str
    asset_urn: str | None = None
    asset_name: str | None = None
    field_path: str | None = None
    observation: str
    relevance: Relevance
    observed_at: datetime | None = None
    lineage_distance: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class HypothesisOut(BaseModel):
    id: str
    pattern: str
    description: str
    confidence: float
    status: HypothesisStatus
    reasoning_summary: str = ""
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)
    proposed_by: str = "deterministic-engine"
    is_primary: bool = False


class RootCauseOut(BaseModel):
    summary: str | None = None
    pattern: str | None = None
    confidence: float = 0.0
    reasoning: str = ""
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)


class CausalStep(BaseModel):
    step: int
    label: str
    detail: str = ""
    asset_urn: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class InvestigationOut(BaseModel):
    id: str
    incident_id: str
    status: InvestigationStatus
    phase: InvestigationPhase
    started_at: datetime
    completed_at: datetime | None = None
    datahub_source_mode: str
    reasoning_engine: str
    blocked_reason: str | None = None
    error: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    root_cause: RootCauseOut = Field(default_factory=RootCauseOut)
    causal_chain: list[CausalStep] = Field(default_factory=list)
    evidence: list[EvidenceOut] = Field(default_factory=list)
    hypotheses: list[HypothesisOut] = Field(default_factory=list)
    blast_radius: dict[str, Any] = Field(default_factory=dict)
    remediation: dict[str, Any] | None = None
    verification: dict[str, Any] | None = None
    memory: dict[str, Any] | None = None


class InvestigationEventOut(BaseModel):
    seq: int
    event: str
    level: str
    message: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
