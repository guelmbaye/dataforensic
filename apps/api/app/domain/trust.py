"""Investigation Trust Score.

Confidence answers "how strongly does the evidence point at this cause?".
Trust answers a different and, for an AI system, more important question:
"how much of this investigation is actually grounded in retrieved context?"

The two must be able to disagree. An investigation can be 97% confident and
barely trustworthy — that happens exactly when the agent reasoned over a thin
context and got lucky with a correlation. Keeping the scores separate is what
makes the second number worth reading.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class TrustCheckStatus(StrEnum):
    PASS = "PASS"
    PARTIAL = "PARTIAL"
    FAIL = "FAIL"


class TrustDecision(StrEnum):
    HIGH_CONFIDENCE = "HIGH_CONFIDENCE"
    MODERATE_CONFIDENCE = "MODERATE_CONFIDENCE"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    INSUFFICIENT_GROUNDING = "INSUFFICIENT_GROUNDING"


# Weights sum to 100. Historical match is deliberately the smallest slice: a
# first-ever incident must still be able to reach HIGH_CONFIDENCE on the
# strength of its own evidence, while a recognised pattern lifts an already
# well-grounded investigation the last stretch. That is the shape of the claim
# the product makes — the system gets more trustworthy as it learns, without
# treating novelty as a defect.
WEIGHTS: dict[str, float] = {
    "evidence_quality": 30.0,
    "schema_validation": 20.0,
    "lineage_coverage": 20.0,
    "quality_signals": 15.0,
    "historical_match": 15.0,
}

LABELS: dict[str, str] = {
    "evidence_quality": "Evidence quality",
    "schema_validation": "Schema validation",
    "lineage_coverage": "Lineage coverage",
    "quality_signals": "Quality signals",
    "historical_match": "Historical match",
}

HIGH_THRESHOLD = 85.0
MODERATE_THRESHOLD = 65.0
LOW_THRESHOLD = 40.0


@dataclass(slots=True)
class TrustCheck:
    key: str
    status: TrustCheckStatus
    points: float
    max_points: float
    detail: str

    @property
    def label(self) -> str:
        return LABELS.get(self.key, self.key.replace("_", " ").capitalize())

    def to_public(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "status": str(self.status),
            "points": round(self.points, 1),
            "max_points": self.max_points,
            "detail": self.detail,
        }


@dataclass(slots=True)
class TrustScore:
    checks: list[TrustCheck] = field(default_factory=list)

    @property
    def score(self) -> float:
        return round(sum(check.points for check in self.checks), 1)

    @property
    def decision(self) -> TrustDecision:
        score = self.score
        if score >= HIGH_THRESHOLD:
            return TrustDecision.HIGH_CONFIDENCE
        if score >= MODERATE_THRESHOLD:
            return TrustDecision.MODERATE_CONFIDENCE
        if score >= LOW_THRESHOLD:
            return TrustDecision.LOW_CONFIDENCE
        return TrustDecision.INSUFFICIENT_GROUNDING

    @property
    def failed_checks(self) -> list[TrustCheck]:
        return [c for c in self.checks if c.status is TrustCheckStatus.FAIL]

    @property
    def partial_checks(self) -> list[TrustCheck]:
        return [c for c in self.checks if c.status is TrustCheckStatus.PARTIAL]

    def rationale(self) -> str:
        """One sentence a human can act on, not a restatement of the number.

        Partial checks count. Saying "every grounding check passed" next to three
        half-filled meters is the kind of contradiction that costs a reader their
        trust in the whole panel.
        """
        failed = self.failed_checks
        partial = self.partial_checks
        if not failed and not partial:
            return "Every grounding check passed: the conclusion rests on retrieved context."
        if not failed:
            names = ", ".join(check.label.lower() for check in partial)
            return (
                f"Grounding is solid but not complete ({names}). The conclusion is "
                "supported; confirm the thin parts before acting on it."
            )
        names = ", ".join(check.label.lower() for check in failed)
        weak = f" {len(partial)} more are only partial." if partial else ""
        return (
            f"Grounding is incomplete ({names}).{weak} Treat the conclusion as a lead "
            f"to confirm rather than an established fact."
        )

    def to_public(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "max_score": 100.0,
            "decision": str(self.decision),
            "rationale": self.rationale(),
            "checks": [check.to_public() for check in self.checks],
        }
