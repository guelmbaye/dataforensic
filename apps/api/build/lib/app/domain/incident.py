"""Incident domain rules."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.domain.enums import ImpactLevel, IncidentStatus, Severity

SEVERITY_WEIGHT: dict[Severity, int] = {
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.HIGH: 3,
    Severity.CRITICAL: 4,
}

IMPACT_WEIGHT: dict[ImpactLevel, int] = {
    ImpactLevel.LOW: 1,
    ImpactLevel.MEDIUM: 2,
    ImpactLevel.HIGH: 3,
    ImpactLevel.CRITICAL: 4,
}


@dataclass(slots=True)
class IncidentSignal:
    """Normalised incident input handed to the agent."""

    incident_id: str
    title: str
    description: str
    asset_urn: str
    severity: Severity
    observed_value: str | None = None
    expected_value: str | None = None
    detected_at: datetime | None = None
    scenario_id: str | None = None
    tags: list[str] = field(default_factory=list)

    @property
    def symptom(self) -> str:
        parts = [self.title, self.description or ""]
        if self.observed_value and self.expected_value:
            parts.append(f"observed {self.observed_value} expected {self.expected_value}")
        return " ".join(p for p in parts if p).strip()


def escalate(severity: Severity, impact: ImpactLevel) -> Severity:
    """Impact can raise (never lower) the working severity of an incident."""
    combined = max(SEVERITY_WEIGHT[severity], IMPACT_WEIGHT[impact])
    for sev, weight in SEVERITY_WEIGHT.items():
        if weight == combined:
            return sev
    return severity


ACTIVE_STATUSES = {
    IncidentStatus.CREATED,
    IncidentStatus.INVESTIGATING,
    IncidentStatus.REMEDIATING,
    IncidentStatus.VERIFYING,
    IncidentStatus.BLOCKED,
}
