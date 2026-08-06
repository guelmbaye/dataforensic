"""Hypothesis engine (DOCUMENT 04 - section 7).

Candidates are generated from generic signal shapes, then scored. The engine
never maps an incident title to an answer: remove the schema-change evidence and
SCHEMA_DRIFT collapses on its own.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from app.agents.context import InvestigationContext
from app.agents.scoring import build_reasoning_summary, classify, score_hypothesis
from app.domain.enums import EvidenceType, Relevance
from app.domain.evidence import EvidenceItem
from app.domain.hypothesis import HypothesisCandidate

Predicate = Callable[[EvidenceItem], bool]

FRESHNESS_HINTS = ("fresh", "lag", "stale", "delay", "latency", "sla")
VOLUME_HINTS = ("volume", "row_count", "rowcount", "count")


def _is_schema_change(e: EvidenceItem) -> bool:
    return e.type is EvidenceType.SCHEMA_CHANGE


def _is_relevant_schema_change(e: EvidenceItem) -> bool:
    return _is_schema_change(e) and bool(e.metadata.get("on_path_to_target", True))


def _is_mapping_break(e: EvidenceItem) -> bool:
    return e.type is EvidenceType.PIPELINE_CHANGE and bool(e.metadata.get("mapping_unresolved"))


def _is_definition_change(e: EvidenceItem) -> bool:
    return e.type is EvidenceType.PIPELINE_CHANGE and bool(e.metadata.get("definition_changed"))


def _is_failed_run(e: EvidenceItem) -> bool:
    return e.type is EvidenceType.PIPELINE_CHANGE and bool(e.metadata.get("failed"))


def _is_late_run(e: EvidenceItem) -> bool:
    return e.type is EvidenceType.PIPELINE_CHANGE and bool(e.metadata.get("late"))


def _is_healthy_run(e: EvidenceItem) -> bool:
    return (
        e.type is EvidenceType.PIPELINE_CHANGE
        and str(e.metadata.get("status", "")).upper() in {"SUCCESS", "SUCCEEDED", "COMPLETED", "OK"}
        and not e.metadata.get("failed")
        and not e.metadata.get("late")
        and not e.metadata.get("mapping_unresolved")
    )


def _quality_kind(e: EvidenceItem) -> str:
    blob = " ".join(
        str(e.metadata.get(key, "")) for key in ("check", "kind", "name", "type")
    ).lower()
    return blob


def _is_freshness_quality(e: EvidenceItem) -> bool:
    return e.type is EvidenceType.QUALITY_ANOMALY and any(
        hint in _quality_kind(e) for hint in FRESHNESS_HINTS
    )


def _is_volume_quality(e: EvidenceItem) -> bool:
    return e.type is EvidenceType.QUALITY_ANOMALY and any(
        hint in _quality_kind(e) for hint in VOLUME_HINTS
    )


def _is_content_quality(e: EvidenceItem) -> bool:
    return (
        e.type is EvidenceType.QUALITY_ANOMALY
        and not _is_freshness_quality(e)
        and not _is_volume_quality(e)
    )


@dataclass(slots=True)
class HypothesisRule:
    pattern: str
    description: str
    supports: Predicate
    contradicts: Predicate = lambda e: False
    requires_any: Predicate | None = None
    always_consider: bool = False


RULES: list[HypothesisRule] = [
    HypothesisRule(
        pattern="SCHEMA_DRIFT",
        description=(
            "An upstream schema change broke a field mapping in the transformation chain, "
            "corrupting the downstream values."
        ),
        supports=lambda e: _is_relevant_schema_change(e) or _is_mapping_break(e),
        contradicts=lambda e: False,
        always_consider=True,
    ),
    HypothesisRule(
        pattern="PIPELINE_FAILURE",
        description="A pipeline execution failed or degraded, leaving the target asset incorrect.",
        supports=lambda e: _is_failed_run(e) or _is_late_run(e) or _is_volume_quality(e),
        contradicts=_is_healthy_run,
        always_consider=True,
    ),
    HypothesisRule(
        pattern="SOURCE_DATA_ANOMALY",
        description="The source system delivered anomalous data that propagated downstream.",
        supports=lambda e: False,  # replaced dynamically (needs graph context)
        contradicts=lambda e: _is_relevant_schema_change(e) and e.relevance is Relevance.HIGH,
        always_consider=True,
    ),
    HypothesisRule(
        pattern="BUSINESS_SEASONALITY",
        description="The variation is a genuine business movement rather than a data defect.",
        supports=lambda e: False,
        contradicts=lambda e: e.relevance is Relevance.HIGH
        and e.type
        in {EvidenceType.SCHEMA_CHANGE, EvidenceType.QUALITY_ANOMALY, EvidenceType.PIPELINE_CHANGE},
        always_consider=True,
    ),
    HypothesisRule(
        pattern="FRESHNESS_STALENESS",
        description="An upstream stage stopped refreshing, so the target asset serves stale data.",
        supports=lambda e: _is_freshness_quality(e) or _is_late_run(e),
        requires_any=lambda e: _is_freshness_quality(e) or _is_late_run(e),
    ),
    HypothesisRule(
        pattern="TRANSFORMATION_LOGIC_CHANGE",
        description="A transformation definition changed and altered the downstream result.",
        supports=_is_definition_change,
        requires_any=_is_definition_change,
    ),
]


class HypothesisEngine:
    def __init__(
        self,
        context: InvestigationContext,
        lookback_minutes: int = 720,
    ) -> None:
        self.context = context
        self.lookback_minutes = lookback_minutes

    def _source_assets(self) -> set[str]:
        """Assets in the retrieved graph that have no upstream (true sources)."""
        edges = self.context.lineage.get("edges", [])
        has_upstream = {e["downstream"] for e in edges}
        return {
            n["urn"]
            for n in self.context.nodes
            if n.get("urn") and n["urn"] not in has_upstream
        }

    def generate(self, evidence: list[EvidenceItem]) -> list[HypothesisCandidate]:
        symptom_evidence = [e for e in evidence if e.type is EvidenceType.METRIC_CHANGE]
        sources = self._source_assets()

        def supports_source_anomaly(item: EvidenceItem) -> bool:
            return item.type is EvidenceType.QUALITY_ANOMALY and item.asset_urn in sources

        # A content quality anomaly corroborates SCHEMA_DRIFT only when a
        # structural change was actually found. Without that guard, "values look
        # wrong" would support schema drift in every incident, including the
        # ones where nothing structural changed at all.
        structural_change_found = any(
            _is_relevant_schema_change(e) or _is_mapping_break(e) for e in evidence
        )

        def supports_schema_drift(item: EvidenceItem) -> bool:
            if _is_relevant_schema_change(item) or _is_mapping_break(item):
                return True
            return structural_change_found and _is_content_quality(item)

        candidates: list[HypothesisCandidate] = []
        for rule in RULES:
            dynamic: dict[str, Predicate] = {
                "SOURCE_DATA_ANOMALY": supports_source_anomaly,
                "SCHEMA_DRIFT": supports_schema_drift,
            }
            supports = dynamic.get(rule.pattern, rule.supports)
            if rule.requires_any and not any(rule.requires_any(e) for e in evidence):
                continue
            supporting = [e for e in evidence if supports(e)]
            if not supporting and not rule.always_consider:
                continue

            # Lineage evidence corroborates a hypothesis only for the assets that
            # already produced one of its supporting signals.
            implicated = {e.asset_urn for e in supporting if e.asset_urn}
            lineage_support = [
                e
                for e in evidence
                if e.type is EvidenceType.LINEAGE_DEPENDENCY and e.asset_urn in implicated
            ]

            candidate = HypothesisCandidate(
                pattern=rule.pattern,
                description=rule.description,
                supporting=[*symptom_evidence, *supporting, *lineage_support],
                contradicting=[e for e in evidence if rule.contradicts(e)],
            )
            candidates.append(candidate)
        return candidates

    def score(self, candidates: list[HypothesisCandidate]) -> list[HypothesisCandidate]:
        incident_time: datetime | None = self.context.incident_time
        for candidate in candidates:
            raw, breakdown = score_hypothesis(candidate, incident_time, self.lookback_minutes)
            candidate.confidence = raw / 100.0
            candidate.score_breakdown = breakdown
            candidate.status = classify(candidate, raw)
            candidate.reasoning_summary = build_reasoning_summary(candidate, breakdown)
        candidates.sort(key=lambda c: c.confidence, reverse=True)
        return candidates

    @staticmethod
    def primary(candidates: list[HypothesisCandidate]) -> HypothesisCandidate | None:
        from app.domain.enums import HypothesisStatus

        for candidate in candidates:
            if candidate.status in {HypothesisStatus.CONFIRMED, HypothesisStatus.SUPPORTED}:
                return candidate
        return None
