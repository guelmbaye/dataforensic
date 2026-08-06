"""Hypothesis value objects (DOCUMENT 04 - section 7)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.utils import new_id
from app.domain.enums import EvidenceType, HypothesisStatus
from app.domain.evidence import EvidenceItem


@dataclass(slots=True)
class HypothesisCandidate:
    pattern: str
    description: str
    supporting: list[EvidenceItem] = field(default_factory=list)
    contradicting: list[EvidenceItem] = field(default_factory=list)
    confidence: float = 0.0
    status: HypothesisStatus = HypothesisStatus.UNTESTED
    reasoning_summary: str = ""
    score_breakdown: dict[str, float] = field(default_factory=dict)
    proposed_by: str = "deterministic-engine"
    id: str = field(default_factory=new_id)

    @property
    def supporting_types(self) -> set[EvidenceType]:
        return {e.type for e in self.supporting}

    def to_public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "pattern": self.pattern,
            "description": self.description,
            "confidence": round(self.confidence, 4),
            "status": str(self.status),
            "reasoning_summary": self.reasoning_summary,
            "score_breakdown": {k: round(v, 2) for k, v in self.score_breakdown.items()},
            "supporting_evidence_ids": [e.id for e in self.supporting],
            "contradicting_evidence_ids": [e.id for e in self.contradicting],
            "proposed_by": self.proposed_by,
        }
