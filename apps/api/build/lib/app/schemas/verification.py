from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.domain.enums import VerificationStatus


class CheckOut(BaseModel):
    name: str
    status: VerificationStatus
    critical: bool
    expected: Any = None
    actual: Any = None
    detail: str = ""
    asset_urn: str | None = None


class VerificationOut(BaseModel):
    id: str
    investigation_id: str
    status: VerificationStatus
    summary: str
    passed: int
    total: int
    checks: list[CheckOut] = Field(default_factory=list)
    expected_result: dict[str, Any] = Field(default_factory=dict)
    actual_result: dict[str, Any] = Field(default_factory=dict)
    verified_at: datetime
    incident_status: str
