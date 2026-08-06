"""Explainable root cause scoring (DOCUMENT 04 - section 8).

    Confidence = Evidence Strength
               + Lineage Relevance
               + Temporal Correlation
               + Cross-Signal Agreement
               - Contradicting Evidence

The breakdown is returned with the score and is displayed in the UI: a judge
must be able to see *why* the agent is confident, not just how confident it is.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.core.utils import ensure_aware
from app.domain.enums import EvidenceType, HypothesisStatus, Relevance
from app.domain.evidence import EvidenceItem
from app.domain.hypothesis import HypothesisCandidate

MAX_EVIDENCE_STRENGTH = 30.0
MAX_LINEAGE_RELEVANCE = 25.0
MAX_TEMPORAL_CORRELATION = 20.0
MAX_CROSS_SIGNAL = 25.0
CROSS_SIGNAL_PER_TYPE = 5.5

CONTRADICTION_PENALTY = {Relevance.HIGH: 8.0, Relevance.MEDIUM: 4.0, Relevance.LOW: 2.0}

# The symptom itself is what every hypothesis tries to explain: it must not
# count as independent corroboration of a specific cause.
SYMPTOM_TYPES = {EvidenceType.METRIC_CHANGE}
NON_CORROBORATING_TYPES = SYMPTOM_TYPES | {EvidenceType.OWNERSHIP_SIGNAL}

CONFIRM_THRESHOLD = 85.0
SUPPORT_THRESHOLD = 60.0
WEAKEN_THRESHOLD = 15.0


def _path_factor(distances: list[int]) -> float:
    if not distances:
        return 0.0
    shortest = min(distances)
    if shortest <= 3:
        return 1.0
    if shortest <= 5:
        return 0.9
    return 0.75


def _time_factor(
    evidence: list[EvidenceItem], incident_time: datetime | None, lookback_minutes: int
) -> float:
    incident_time = ensure_aware(incident_time)
    if incident_time is None:
        return 0.4
    timestamps = [ensure_aware(e.observed_at) for e in evidence if e.observed_at]
    if not timestamps:
        return 0.2
    window_start = incident_time - timedelta(minutes=lookback_minutes)
    preceding_in_window = [t for t in timestamps if window_start <= t <= incident_time]
    if preceding_in_window:
        return 1.0
    if any(t < incident_time for t in timestamps):
        return 0.6
    return 0.0


def score_hypothesis(
    candidate: HypothesisCandidate,
    incident_time: datetime | None = None,
    lookback_minutes: int = 720,
) -> tuple[float, dict[str, float]]:
    cause_evidence = [e for e in candidate.supporting if e.type not in SYMPTOM_TYPES]

    evidence_strength = min(
        MAX_EVIDENCE_STRENGTH, sum(e.weight for e in candidate.supporting)
    )

    max_relevance = (max((e.weight for e in cause_evidence), default=0.0)) / 10.0

    distances = [
        e.lineage_distance for e in cause_evidence if e.lineage_distance is not None
    ]
    lineage_relevance = MAX_LINEAGE_RELEVANCE * max_relevance * _path_factor(distances)

    temporal_correlation = (
        MAX_TEMPORAL_CORRELATION
        * max_relevance
        * _time_factor(cause_evidence, incident_time, lookback_minutes)
    )

    corroborating_types = {
        e.type for e in cause_evidence if e.type not in NON_CORROBORATING_TYPES
    }
    cross_signal = min(MAX_CROSS_SIGNAL, CROSS_SIGNAL_PER_TYPE * len(corroborating_types))

    contradictions = sum(
        CONTRADICTION_PENALTY[e.relevance] for e in candidate.contradicting
    )

    total = (
        evidence_strength
        + lineage_relevance
        + temporal_correlation
        + cross_signal
        - contradictions
    )
    total = max(0.0, min(100.0, total))

    breakdown = {
        "evidence_strength": round(evidence_strength, 2),
        "lineage_relevance": round(lineage_relevance, 2),
        "temporal_correlation": round(temporal_correlation, 2),
        "cross_signal_agreement": round(cross_signal, 2),
        "contradicting_evidence": -round(contradictions, 2),
        "total": round(total, 2),
    }
    return total, breakdown


def classify(candidate: HypothesisCandidate, score: float) -> HypothesisStatus:
    """CONFIRMED requires corroboration, not just a high arithmetic score."""
    cause_evidence = [e for e in candidate.supporting if e.type not in SYMPTOM_TYPES]
    corroborating_types = {
        e.type for e in cause_evidence if e.type not in NON_CORROBORATING_TYPES
    }
    has_high = any(e.relevance is Relevance.HIGH for e in cause_evidence)

    if score >= CONFIRM_THRESHOLD:
        if len(corroborating_types) >= 2 and has_high:
            return HypothesisStatus.CONFIRMED
        return HypothesisStatus.SUPPORTED
    if score >= SUPPORT_THRESHOLD:
        return HypothesisStatus.SUPPORTED
    if score >= WEAKEN_THRESHOLD:
        return HypothesisStatus.WEAKENED
    if not cause_evidence:
        return HypothesisStatus.REJECTED
    return HypothesisStatus.REJECTED


def build_reasoning_summary(candidate: HypothesisCandidate, breakdown: dict[str, float]) -> str:
    cause_evidence = [e for e in candidate.supporting if e.type not in SYMPTOM_TYPES]
    if not cause_evidence:
        return (
            "No independent evidence supports this hypothesis; it only restates the "
            "observed symptom."
        )
    types = ", ".join(sorted({str(e.type) for e in cause_evidence}))
    parts = [
        f"{len(cause_evidence)} supporting signal(s) ({types})",
        f"evidence strength {breakdown['evidence_strength']}/30",
        f"lineage relevance {breakdown['lineage_relevance']}/25",
        f"temporal correlation {breakdown['temporal_correlation']}/20",
        f"cross-signal agreement {breakdown['cross_signal_agreement']}/25",
    ]
    if candidate.contradicting:
        parts.append(
            f"{len(candidate.contradicting)} contradicting signal(s) "
            f"({breakdown['contradicting_evidence']})"
        )
    return "; ".join(parts) + "."
