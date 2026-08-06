"""Domain enumerations (DOCUMENT 06 - sections 3 to 9)."""

from __future__ import annotations

from enum import StrEnum


class Severity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class IncidentStatus(StrEnum):
    CREATED = "CREATED"
    INVESTIGATING = "INVESTIGATING"
    REMEDIATING = "REMEDIATING"
    VERIFYING = "VERIFYING"
    RESOLVED = "RESOLVED"
    BLOCKED = "BLOCKED"


class InvestigationStatus(StrEnum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class InvestigationPhase(StrEnum):
    """Fine grained agent state machine (DOCUMENT 04 - section 3)."""

    CREATED = "CREATED"
    CONTEXT_LOADING = "CONTEXT_LOADING"
    INVESTIGATING = "INVESTIGATING"
    HYPOTHESIS_TESTING = "HYPOTHESIS_TESTING"
    ROOT_CAUSE_IDENTIFIED = "ROOT_CAUSE_IDENTIFIED"
    IMPACT_ANALYSIS = "IMPACT_ANALYSIS"
    REMEDIATION_PLANNED = "REMEDIATION_PLANNED"
    REMEDIATION_EXECUTED = "REMEDIATION_EXECUTED"
    VERIFYING = "VERIFYING"
    RESOLVED = "RESOLVED"
    MEMORY_WRITTEN = "MEMORY_WRITTEN"
    BLOCKED = "BLOCKED"
    NEEDS_HUMAN = "NEEDS_HUMAN"
    FAILED = "FAILED"


class EvidenceType(StrEnum):
    SCHEMA_CHANGE = "SCHEMA_CHANGE"
    QUALITY_ANOMALY = "QUALITY_ANOMALY"
    LINEAGE_DEPENDENCY = "LINEAGE_DEPENDENCY"
    METRIC_CHANGE = "METRIC_CHANGE"
    PIPELINE_CHANGE = "PIPELINE_CHANGE"
    OWNERSHIP_SIGNAL = "OWNERSHIP_SIGNAL"
    HISTORICAL_INCIDENT = "HISTORICAL_INCIDENT"
    ML_SIGNAL = "ML_SIGNAL"


class Relevance(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class HypothesisStatus(StrEnum):
    UNTESTED = "UNTESTED"
    SUPPORTED = "SUPPORTED"
    WEAKENED = "WEAKENED"
    REJECTED = "REJECTED"
    CONFIRMED = "CONFIRMED"


class ActionType(StrEnum):
    RECOMMEND = "RECOMMEND"
    EXECUTE_SIMULATED = "EXECUTE_SIMULATED"
    WRITE_BACK = "WRITE_BACK"


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ActionStatus(StrEnum):
    PLANNED = "PLANNED"
    APPROVED = "APPROVED"
    EXECUTED = "EXECUTED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


class VerificationStatus(StrEnum):
    PASS = "PASS"
    PARTIAL = "PARTIAL"
    FAIL = "FAIL"


class ImpactLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class SourceMode(StrEnum):
    """How the context was obtained. Never lie about this (DOCUMENT 07 - 20)."""

    LIVE_DATAHUB = "LIVE_DATAHUB"
    DEMO_FIXTURE = "DEMO_FIXTURE"


class SourceSystem(StrEnum):
    DATAHUB = "DATAHUB"
    SCENARIO_RUNTIME = "SCENARIO_RUNTIME"
    APPLICATION = "APPLICATION"


class ExecutionMode(StrEnum):
    SIMULATED = "SIMULATED"
    REAL = "REAL"
