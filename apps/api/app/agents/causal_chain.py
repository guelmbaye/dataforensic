"""Human readable causal chain (DOCUMENT 04 - section 10).

Each step points back at the evidence that justifies it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.agents.context import InvestigationContext
from app.domain.enums import EvidenceType
from app.domain.evidence import EvidenceItem
from app.domain.hypothesis import HypothesisCandidate

TYPE_ORDER: dict[EvidenceType, int] = {
    EvidenceType.SCHEMA_CHANGE: 1,
    EvidenceType.PIPELINE_CHANGE: 2,
    EvidenceType.QUALITY_ANOMALY: 3,
    EvidenceType.LINEAGE_DEPENDENCY: 4,
    EvidenceType.ML_SIGNAL: 5,
    EvidenceType.METRIC_CHANGE: 6,
    EvidenceType.HISTORICAL_INCIDENT: 7,
    EvidenceType.OWNERSHIP_SIGNAL: 8,
}

LABELS: dict[EvidenceType, str] = {
    EvidenceType.SCHEMA_CHANGE: "Upstream schema change",
    EvidenceType.PIPELINE_CHANGE: "Transformation / pipeline impact",
    EvidenceType.QUALITY_ANOMALY: "Data quality degradation",
    EvidenceType.LINEAGE_DEPENDENCY: "Propagation through lineage",
    EvidenceType.ML_SIGNAL: "ML consumers affected",
    EvidenceType.METRIC_CHANGE: "Business metric impact",
}


def build_causal_chain(
    hypothesis: HypothesisCandidate, context: InvestigationContext
) -> list[dict[str, Any]]:
    grouped: dict[EvidenceType, list[EvidenceItem]] = {}
    for item in hypothesis.supporting:
        if item.type is EvidenceType.OWNERSHIP_SIGNAL:
            continue
        grouped.setdefault(item.type, []).append(item)

    chain: list[dict[str, Any]] = []
    ordered_types = sorted(grouped, key=lambda t: TYPE_ORDER.get(t, 99))
    for index, evidence_type in enumerate(ordered_types, start=1):
        items = sorted(
            grouped[evidence_type],
            key=lambda e: e.observed_at or datetime.min.replace(tzinfo=UTC),
        )
        head = items[0]
        chain.append(
            {
                "step": index,
                "label": LABELS.get(evidence_type, str(evidence_type)),
                "detail": head.observation,
                "asset_urn": head.asset_urn,
                "asset_name": context.asset_name(head.asset_urn),
                "evidence_ids": [e.id for e in items],
                "evidence_type": str(evidence_type),
            }
        )
    return chain


def summarize_root_cause(
    hypothesis: HypothesisCandidate, context: InvestigationContext
) -> str:
    """One strong sentence, not a 500 word LLM paragraph (DOCUMENT 07 - section 8)."""
    schema = next(
        (e for e in hypothesis.supporting if e.type is EvidenceType.SCHEMA_CHANGE), None
    )
    mapping = next(
        (
            e
            for e in hypothesis.supporting
            if e.type is EvidenceType.PIPELINE_CHANGE and e.metadata.get("mapping_unresolved")
        ),
        None,
    )
    quality = next(
        (e for e in hypothesis.supporting if e.type is EvidenceType.QUALITY_ANOMALY), None
    )
    target = context.asset_name(context.asset_urn)

    if hypothesis.pattern == "SCHEMA_DRIFT" and schema:
        field = schema.field_path or (mapping.field_path if mapping else None) or "a mapped field"
        origin = context.asset_name(schema.asset_urn)
        tail = f" and drove {quality.field_path or 'quality'} out of range" if quality else ""
        return (
            f"A schema change on {origin} ({field}) broke the field mapping feeding {target}{tail}."
        )
    if hypothesis.pattern in {"PIPELINE_FAILURE", "FRESHNESS_STALENESS"}:
        run = next(
            (
                e
                for e in hypothesis.supporting
                if e.type is EvidenceType.PIPELINE_CHANGE and (e.metadata.get("failed") or e.metadata.get("late"))
            ),
            None,
        )
        stage = context.asset_name(run.asset_urn) if run else "an upstream pipeline stage"
        verb = "failed" if (run and run.metadata.get("failed")) else "stopped refreshing on time"
        return f"{stage} {verb}, so {target} no longer reflects current source data."
    if hypothesis.pattern == "SOURCE_DATA_ANOMALY" and quality:
        source = context.asset_name(quality.asset_urn)
        if source == target:
            # The anomaly was only measured on the incident asset itself, which
            # happens when lineage is thin. "X delivered data that propagated to
            # X" reads like a bug, so say what is actually known instead.
            return (
                f"Anomalous values were found directly on {target}; no upstream asset "
                "could be identified as the source."
            )
        return (
            f"The source asset {source} delivered anomalous data that propagated to {target}."
        )
    if hypothesis.pattern == "TRANSFORMATION_LOGIC_CHANGE":
        return f"A transformation definition feeding {target} changed and altered its output."
    if hypothesis.pattern == "BUSINESS_SEASONALITY":
        return f"No data defect was found: the movement on {target} looks like a business variation."
    return hypothesis.description
