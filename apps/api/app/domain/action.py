"""Action risk policy (DOCUMENT 04 - section 13)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.config import settings
from app.core.errors import ActionNotAllowedError
from app.domain.enums import ActionType, ExecutionMode, RiskLevel

RISK_ORDER: dict[RiskLevel, int] = {RiskLevel.LOW: 1, RiskLevel.MEDIUM: 2, RiskLevel.HIGH: 3}

# Verbs that always classify a step as high risk when executed for real.
DESTRUCTIVE_KEYWORDS = (
    "drop", "delete", "truncate", "rollback", "purge", "overwrite production",
    "alter schema", "supprimer", "ecraser",
)


@dataclass(slots=True)
class RemediationStep:
    id: str
    title: str
    description: str
    risk: RiskLevel = RiskLevel.LOW
    effect: str | None = None
    executed: bool = False
    result: dict[str, Any] | None = None

    def to_public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "risk": str(self.risk),
            "effect": self.effect,
            "executed": self.executed,
            "result": self.result,
        }


@dataclass(slots=True)
class RemediationPlan:
    diagnosis: str
    steps: list[RemediationStep] = field(default_factory=list)
    expected_result: str = ""
    rollback: str = ""
    execution_mode: ExecutionMode = ExecutionMode.SIMULATED
    notify_owners: list[str] = field(default_factory=list)

    @property
    def risk(self) -> RiskLevel:
        if not self.steps:
            return RiskLevel.LOW
        return max(self.steps, key=lambda s: RISK_ORDER[s.risk]).risk

    @property
    def requires_approval(self) -> bool:
        if self.execution_mode is ExecutionMode.REAL:
            return True
        return RISK_ORDER[self.risk] >= RISK_ORDER[RiskLevel.MEDIUM]

    def to_public(self) -> dict[str, Any]:
        return {
            "diagnosis": self.diagnosis,
            "steps": [s.to_public() for s in self.steps],
            "risk_level": str(self.risk),
            "requires_approval": self.requires_approval,
            "execution_mode": str(self.execution_mode),
            "expected_result": self.expected_result,
            "rollback": self.rollback,
            "notify_owners": self.notify_owners,
        }


def classify_risk(text: str, default: RiskLevel = RiskLevel.LOW) -> RiskLevel:
    lowered = text.lower()
    if any(word in lowered for word in DESTRUCTIVE_KEYWORDS):
        return RiskLevel.HIGH
    return default


def assert_executable(
    action_type: ActionType,
    risk: RiskLevel,
    execution_mode: ExecutionMode,
    approved: bool,
) -> None:
    """Server side enforcement: the agent asking nicely is never enough."""
    if execution_mode is ExecutionMode.REAL and not settings.allow_real_remediation:
        raise ActionNotAllowedError(
            "Real remediation is disabled in this deployment (ALLOW_REAL_REMEDIATION=false)",
            details={"action_type": str(action_type), "execution_mode": str(execution_mode)},
        )
    if RISK_ORDER[risk] >= RISK_ORDER[RiskLevel.MEDIUM] and not approved:
        raise ActionNotAllowedError(
            "This action requires explicit human approval before execution",
            details={"risk_level": str(risk), "requires_approval": True},
        )
