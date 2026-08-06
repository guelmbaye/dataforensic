from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class PatternMatch(BaseModel):
    """A known pattern that might explain an incident the agent has not solved yet."""

    pattern: str
    label: str
    similarity: float = Field(ge=0.0, le=1.0)
    occurrences: int = 0
    average_confidence: float = 0.0
    average_trust_score: float = 0.0
    verified_resolutions: int = 0
    symptoms: list[str] = Field(default_factory=list)
    evidence_signature: list[str] = Field(default_factory=list)
    recommended_remediation: list[str] = Field(default_factory=list)
    last_seen: datetime | None = None
    match_reasons: list[str] = Field(default_factory=list)


class KnowledgePatternOut(BaseModel):
    pattern: str
    label: str
    description: str = ""
    occurrences: int = 0
    verified_resolutions: int = 0
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    symptoms: list[str] = Field(default_factory=list)
    evidence_signature: list[str] = Field(default_factory=list)
    resolution_steps: list[str] = Field(default_factory=list)
    affected_asset_urns: list[str] = Field(default_factory=list)
    average_confidence: float = 0.0
    average_trust_score: float = 0.0
    first_investigation_ms: int | None = None
    latest_investigation_ms: int | None = None
    first_investigation_tool_calls: int | None = None
    latest_investigation_tool_calls: int | None = None
    history: list[dict[str, Any]] = Field(default_factory=list)


class PatternListResponse(BaseModel):
    items: list[KnowledgePatternOut]
    total: int


class TrustCheckOut(BaseModel):
    key: str
    label: str
    status: str
    points: float
    max_points: float
    detail: str


class TrustScoreOut(BaseModel):
    score: float
    max_score: float = 100.0
    decision: str
    rationale: str
    checks: list[TrustCheckOut] = Field(default_factory=list)
