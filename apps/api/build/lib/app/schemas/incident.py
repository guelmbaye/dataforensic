from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.domain.enums import IncidentStatus, Severity


class IncidentCreate(BaseModel):
    title: str = Field(min_length=3, max_length=255)
    description: str = Field(default="", max_length=8000)
    asset_urn: str = Field(min_length=5, max_length=512)
    severity: Severity = Severity.MEDIUM
    observed_value: str | None = Field(default=None, max_length=255)
    expected_value: str | None = Field(default=None, max_length=255)
    detected_at: datetime | None = None
    scenario_id: str | None = Field(default=None, max_length=64)

    @field_validator("asset_urn")
    @classmethod
    def validate_urn(cls, value: str) -> str:
        if not value.startswith("urn:li:"):
            raise ValueError("asset_urn must be a DataHub URN (urn:li:...)")
        return value


class IncidentSummary(BaseModel):
    id: str
    title: str
    asset_urn: str
    asset_name: str
    severity: Severity
    status: IncidentStatus
    observed_value: str | None = None
    expected_value: str | None = None
    scenario_id: str | None = None
    created_at: datetime
    resolved_at: datetime | None = None
    investigation_id: str | None = None
    investigation_status: str | None = None
    root_cause_summary: str | None = None
    confidence: float | None = None


class IncidentDetail(IncidentSummary):
    description: str = ""
    detected_at: datetime | None = None
    blocked_reason: str | None = None
    root_cause_pattern: str | None = None
    blast_radius: dict[str, Any] = Field(default_factory=dict)
    verification_status: str | None = None
    memory: dict[str, Any] | None = None
    datahub_source_mode: str | None = None
