"""Explicit state machines (DOCUMENT 06 - section 25, DOCUMENT 04 - section 3).

A verification PASS is the only way into RESOLVED. The transition table makes
CREATED -> RESOLVED, INVESTIGATING -> RESOLVED and REMEDIATING -> RESOLVED
structurally impossible.
"""

from __future__ import annotations

from app.core.errors import InvalidStateTransitionError
from app.domain.enums import IncidentStatus, InvestigationPhase, InvestigationStatus

INCIDENT_TRANSITIONS: dict[IncidentStatus, set[IncidentStatus]] = {
    IncidentStatus.CREATED: {IncidentStatus.INVESTIGATING, IncidentStatus.BLOCKED},
    IncidentStatus.INVESTIGATING: {
        IncidentStatus.REMEDIATING,
        IncidentStatus.VERIFYING,
        IncidentStatus.BLOCKED,
    },
    IncidentStatus.REMEDIATING: {IncidentStatus.VERIFYING, IncidentStatus.BLOCKED},
    IncidentStatus.VERIFYING: {
        IncidentStatus.RESOLVED,
        IncidentStatus.INVESTIGATING,
        IncidentStatus.BLOCKED,
    },
    IncidentStatus.BLOCKED: {IncidentStatus.CREATED, IncidentStatus.INVESTIGATING},
    # Re-opening a resolved incident is legitimate: a regression, or a judge
    # re-running the demo. The invariant this table protects is that RESOLVED is
    # only ever *entered* from VERIFYING — reopening does not weaken it.
    IncidentStatus.RESOLVED: {IncidentStatus.INVESTIGATING},
}

INVESTIGATION_TRANSITIONS: dict[InvestigationStatus, set[InvestigationStatus]] = {
    InvestigationStatus.RUNNING: {
        InvestigationStatus.COMPLETED,
        InvestigationStatus.FAILED,
        InvestigationStatus.BLOCKED,
    },
    InvestigationStatus.BLOCKED: {InvestigationStatus.RUNNING, InvestigationStatus.FAILED},
    InvestigationStatus.COMPLETED: set(),
    InvestigationStatus.FAILED: {InvestigationStatus.RUNNING},
}

PHASE_ORDER: list[InvestigationPhase] = [
    InvestigationPhase.CREATED,
    InvestigationPhase.CONTEXT_LOADING,
    InvestigationPhase.INVESTIGATING,
    InvestigationPhase.HYPOTHESIS_TESTING,
    InvestigationPhase.ROOT_CAUSE_IDENTIFIED,
    InvestigationPhase.IMPACT_ANALYSIS,
    InvestigationPhase.REMEDIATION_PLANNED,
    InvestigationPhase.REMEDIATION_EXECUTED,
    InvestigationPhase.VERIFYING,
    InvestigationPhase.RESOLVED,
    InvestigationPhase.MEMORY_WRITTEN,
]

TERMINAL_PHASES = {
    InvestigationPhase.BLOCKED,
    InvestigationPhase.NEEDS_HUMAN,
    InvestigationPhase.FAILED,
    InvestigationPhase.MEMORY_WRITTEN,
}


def can_transition_incident(current: IncidentStatus, target: IncidentStatus) -> bool:
    if current == target:
        return True
    return target in INCIDENT_TRANSITIONS.get(current, set())


def assert_incident_transition(current: IncidentStatus, target: IncidentStatus) -> None:
    if not can_transition_incident(current, target):
        raise InvalidStateTransitionError(
            f"Incident cannot move from {current} to {target}",
            details={"current": str(current), "target": str(target)},
        )


def can_transition_investigation(
    current: InvestigationStatus, target: InvestigationStatus
) -> bool:
    if current == target:
        return True
    return target in INVESTIGATION_TRANSITIONS.get(current, set())


def assert_investigation_transition(
    current: InvestigationStatus, target: InvestigationStatus
) -> None:
    if not can_transition_investigation(current, target):
        raise InvalidStateTransitionError(
            f"Investigation cannot move from {current} to {target}",
            details={"current": str(current), "target": str(target)},
        )


def can_transition_phase(current: InvestigationPhase, target: InvestigationPhase) -> bool:
    """Phases advance forward, except failure phases which are reachable anywhere."""
    if target in TERMINAL_PHASES and target != InvestigationPhase.MEMORY_WRITTEN:
        return True
    if current in TERMINAL_PHASES and current != InvestigationPhase.BLOCKED:
        return current == target
    try:
        return PHASE_ORDER.index(target) >= PHASE_ORDER.index(current)
    except ValueError:
        return True
