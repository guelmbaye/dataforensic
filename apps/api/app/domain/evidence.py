"""Evidence value objects and relevance policy (DOCUMENT 04 - section 6)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.core.utils import ensure_aware, new_id
from app.domain.enums import EvidenceType, Relevance, SourceMode, SourceSystem

RELEVANCE_WEIGHT: dict[Relevance, float] = {
    Relevance.LOW: 3.0,
    Relevance.MEDIUM: 6.0,
    Relevance.HIGH: 10.0,
}


@dataclass(slots=True)
class EvidenceItem:
    """A single observable fact. Every conclusion must point at one of these."""

    type: EvidenceType
    observation: str
    source: str
    source_system: SourceSystem = SourceSystem.DATAHUB
    source_mode: SourceMode = SourceMode.DEMO_FIXTURE
    asset_urn: str | None = None
    field_path: str | None = None
    relevance: Relevance = Relevance.MEDIUM
    observed_at: datetime | None = None
    lineage_distance: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=new_id)

    @property
    def weight(self) -> float:
        return RELEVANCE_WEIGHT[self.relevance]

    def __post_init__(self) -> None:
        self.observed_at = ensure_aware(self.observed_at)

    def to_public(self) -> dict[str, Any]:
        from app.core.utils import to_iso

        return {
            "id": self.id,
            "type": str(self.type),
            "observation": self.observation,
            "source": self.source,
            "source_system": str(self.source_system),
            "source_mode": str(self.source_mode),
            "asset_urn": self.asset_urn,
            "field_path": self.field_path,
            "relevance": str(self.relevance),
            "observed_at": to_iso(self.observed_at),
            "lineage_distance": self.lineage_distance,
            "metadata": self.metadata,
        }


def strongest(items: list[EvidenceItem]) -> EvidenceItem | None:
    if not items:
        return None
    return max(items, key=lambda e: (e.weight, e.observed_at or datetime.min))
