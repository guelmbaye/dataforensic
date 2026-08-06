from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.domain.enums import ActionStatus, ActionType, ExecutionMode, RiskLevel


class RemediationStepOut(BaseModel):
    id: str
    title: str
    description: str
    risk: RiskLevel
    effect: str | None = None
    executed: bool = False
    result: dict[str, Any] | None = None


class RemediationOut(BaseModel):
    action_id: str
    investigation_id: str
    type: ActionType
    status: ActionStatus
    diagnosis: str
    steps: list[RemediationStepOut]
    risk_level: RiskLevel
    requires_approval: bool
    execution_mode: ExecutionMode
    expected_result: str = ""
    rollback: str = ""
    notify_owners: list[str] = Field(default_factory=list)
    executed_at: datetime | None = None
    result: dict[str, Any] | None = None


class ActionExecuteRequest(BaseModel):
    approved: bool = False
    approved_by: str | None = None
    note: str | None = None
