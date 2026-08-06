"""Relational model (DOCUMENT 06 - sections 2 to 10).

PostgreSQL stores application state only. DataHub remains the authoritative
context system: we keep asset URNs, never copies of the graph.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.utils import new_id, utcnow
from app.models.database import Base


def _pk() -> Mapped[str]:
    return mapped_column(String(36), primary_key=True, default=new_id)


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[str] = _pk()
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    asset_urn: Mapped[str] = mapped_column(String(512), index=True)
    severity: Mapped[str] = mapped_column(String(16), default="MEDIUM", index=True)
    observed_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    expected_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="CREATED", index=True)
    scenario_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    detected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    blocked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra: Mapped[dict] = mapped_column(JSON, default=dict)

    investigations: Mapped[list[Investigation]] = relationship(
        back_populates="incident", cascade="all, delete-orphan", lazy="selectin"
    )
    memory_references: Mapped[list[MemoryReference]] = relationship(
        back_populates="incident", cascade="all, delete-orphan", lazy="selectin"
    )


class Investigation(Base):
    __tablename__ = "investigations"

    id: Mapped[str] = _pk()
    incident_id: Mapped[str] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(24), default="RUNNING", index=True)
    phase: Mapped[str] = mapped_column(String(32), default="CREATED")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    root_cause_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    root_cause_pattern: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    causal_chain: Mapped[list] = mapped_column(JSON, default=list)
    blast_radius: Mapped[dict] = mapped_column(JSON, default=dict)
    context_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    datahub_source_mode: Mapped[str] = mapped_column(String(24), default="DEMO_FIXTURE")
    reasoning_engine: Mapped[str] = mapped_column(String(48), default="deterministic-engine")
    blocked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Investigation Trust Score: how grounded the reasoning was, kept separate
    # from how confident the conclusion is.
    trust_score: Mapped[float] = mapped_column(Float, default=0.0)
    trust_decision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    trust_breakdown: Mapped[dict] = mapped_column(JSON, default=dict)

    # Organisational learning: what the agent knew before it started, and what
    # that saved. Measured, never asserted.
    memory_assisted: Mapped[bool] = mapped_column(Boolean, default=False)
    matched_pattern: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    reused_from_investigation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    remediation_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    tool_call_count: Mapped[int] = mapped_column(Integer, default=0)

    incident: Mapped[Incident] = relationship(back_populates="investigations", lazy="selectin")
    evidence: Mapped[list[Evidence]] = relationship(
        back_populates="investigation", cascade="all, delete-orphan", lazy="selectin"
    )
    hypotheses: Mapped[list[Hypothesis]] = relationship(
        back_populates="investigation", cascade="all, delete-orphan", lazy="selectin"
    )
    actions: Mapped[list[Action]] = relationship(
        back_populates="investigation", cascade="all, delete-orphan", lazy="selectin"
    )
    verifications: Mapped[list[Verification]] = relationship(
        back_populates="investigation", cascade="all, delete-orphan", lazy="selectin"
    )


class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[str] = _pk()
    investigation_id: Mapped[str] = mapped_column(
        ForeignKey("investigations.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(String(32), index=True)
    source: Mapped[str] = mapped_column(String(255))
    source_system: Mapped[str] = mapped_column(String(32), default="DATAHUB")
    source_mode: Mapped[str] = mapped_column(String(24), default="DEMO_FIXTURE")
    asset_urn: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    field_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    observation: Mapped[str] = mapped_column(Text)
    relevance: Mapped[str] = mapped_column(String(16), default="MEDIUM", index=True)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lineage_distance: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extra: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    investigation: Mapped[Investigation] = relationship(back_populates="evidence")


class Hypothesis(Base):
    __tablename__ = "hypotheses"

    id: Mapped[str] = _pk()
    investigation_id: Mapped[str] = mapped_column(
        ForeignKey("investigations.id", ondelete="CASCADE"), index=True
    )
    pattern: Mapped[str] = mapped_column(String(64), index=True)
    description: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(16), default="UNTESTED", index=True)
    reasoning_summary: Mapped[str] = mapped_column(Text, default="")
    score_breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
    supporting_evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    contradicting_evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    proposed_by: Mapped[str] = mapped_column(String(48), default="deterministic-engine")
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    investigation: Mapped[Investigation] = relationship(back_populates="hypotheses")


class Action(Base):
    __tablename__ = "actions"

    id: Mapped[str] = _pk()
    investigation_id: Mapped[str] = mapped_column(
        ForeignKey("investigations.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(String(32), index=True)
    description: Mapped[str] = mapped_column(Text)
    risk_level: Mapped[str] = mapped_column(String(16), default="LOW")
    execution_mode: Mapped[str] = mapped_column(String(16), default="SIMULATED")
    status: Mapped[str] = mapped_column(String(16), default="PLANNED", index=True)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    plan: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    investigation: Mapped[Investigation] = relationship(back_populates="actions")


class Verification(Base):
    __tablename__ = "verifications"

    id: Mapped[str] = _pk()
    investigation_id: Mapped[str] = mapped_column(
        ForeignKey("investigations.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(16), index=True)
    checks: Mapped[list] = mapped_column(JSON, default=list)
    expected_result: Mapped[dict] = mapped_column(JSON, default=dict)
    actual_result: Mapped[dict] = mapped_column(JSON, default=dict)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    investigation: Mapped[Investigation] = relationship(back_populates="verifications")


class MemoryReference(Base):
    __tablename__ = "memory_references"

    id: Mapped[str] = _pk()
    incident_id: Mapped[str] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), index=True
    )
    investigation_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    datahub_reference: Mapped[str] = mapped_column(String(512))
    write_back_status: Mapped[str] = mapped_column(String(24), default="WRITTEN")
    source_mode: Mapped[str] = mapped_column(String(24), default="DEMO_FIXTURE")
    pattern: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    root_cause: Mapped[str] = mapped_column(Text)
    asset_urn: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    symptom: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    document: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    incident: Mapped[Incident] = relationship(back_populates="memory_references")


class InvestigationEvent(Base):
    """Persisted SSE stream (also the agent action log - no hidden actions)."""

    __tablename__ = "investigation_events"
    __table_args__ = (
        UniqueConstraint("investigation_id", "seq", name="uq_investigation_event_seq"),
        Index("ix_investigation_events_lookup", "investigation_id", "seq"),
    )

    id: Mapped[str] = _pk()
    investigation_id: Mapped[str] = mapped_column(String(36), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    event: Mapped[str] = mapped_column(String(48))
    level: Mapped[str] = mapped_column(String(16), default="info")
    message: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ToolCallLog(Base):
    """Complete tool call log (DOCUMENT 03 - section 15)."""

    __tablename__ = "tool_calls"

    id: Mapped[str] = _pk()
    investigation_id: Mapped[str] = mapped_column(String(36), index=True)
    tool: Mapped[str] = mapped_column(String(64), index=True)
    arguments: Mapped[dict] = mapped_column(JSON, default=dict)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    source: Mapped[str] = mapped_column(String(128), default="")
    source_mode: Mapped[str] = mapped_column(String(24), default="DEMO_FIXTURE")
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ScenarioState(Base):
    """Controlled demo world state (never production)."""

    __tablename__ = "scenario_states"

    scenario_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    state: Mapped[str] = mapped_column(String(32), default="BROKEN")
    applied_effects: Mapped[list] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class IdempotencyRecord(Base):
    """Replay protection for sensitive POSTs (DOCUMENT 06 - section 24)."""

    __tablename__ = "idempotency_records"
    __table_args__ = (UniqueConstraint("key", "endpoint", name="uq_idempotency_key_endpoint"),)

    id: Mapped[str] = _pk()
    key: Mapped[str] = mapped_column(String(128), index=True)
    endpoint: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    status_code: Mapped[int] = mapped_column(Integer, default=200)
    response: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KnowledgePattern(Base):
    """A root-cause pattern distilled from every investigation that produced it.

    This is the organisational asset the product exists to build. One row is not
    one incident: it accumulates across incidents, so occurrence count, average
    confidence and the last verified resolution all describe what the
    organisation has learned about this failure mode.
    """

    __tablename__ = "knowledge_patterns"

    pattern: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(128), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    occurrences: Mapped[int] = mapped_column(Integer, default=0)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    symptoms: Mapped[list] = mapped_column(JSON, default=list)
    evidence_signature: Mapped[list] = mapped_column(JSON, default=list)
    resolution_steps: Mapped[list] = mapped_column(JSON, default=list)
    resolution_plan: Mapped[dict] = mapped_column(JSON, default=dict)
    affected_asset_urns: Mapped[list] = mapped_column(JSON, default=list)

    average_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    average_trust_score: Mapped[float] = mapped_column(Float, default=0.0)
    verified_resolutions: Mapped[int] = mapped_column(Integer, default=0)
    occurrences_log: Mapped[list] = mapped_column(JSON, default=list)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
