from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class IncidentMemoryDocument(BaseModel):
    """Validated structure written back to DataHub (never free-form LLM text)."""

    schema_version: str = "1.0"
    incident_id: str
    investigation_id: str
    title: str
    asset_urn: str
    symptom: str
    pattern: str
    root_cause: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_summary: list[dict[str, Any]] = Field(default_factory=list, max_length=50)
    causal_chain: list[str] = Field(default_factory=list, max_length=20)
    affected_assets: list[str] = Field(default_factory=list, max_length=200)
    owners: list[str] = Field(default_factory=list, max_length=50)
    remediation: list[str] = Field(default_factory=list, max_length=20)
    verification: str = "PASS"
    verification_summary: str = ""
    resolved_at: datetime | None = None
    created_by: str = "DATAFORENSIC AI"
    source_mode: str = "DEMO_FIXTURE"


class MemoryWriteResponse(BaseModel):
    status: str
    datahub_reference: str | None = None
    source_mode: str
    verified: bool = False
    document: IncidentMemoryDocument | None = None
    error: str | None = None


class PreviousIncidentMatch(BaseModel):
    incident_id: str | None = None
    reference: str | None = None
    pattern: str | None = None
    root_cause: str
    symptom: str = ""
    confidence: float = 0.0
    similarity: float = 0.0
    remediation: list[str] = Field(default_factory=list)
    asset_urn: str | None = None
    resolved_at: datetime | None = None
    source_mode: str = "DEMO_FIXTURE"


class MemorySearchResponse(BaseModel):
    query: dict[str, Any]
    matches: list[PreviousIncidentMatch]
