"""Computes the Investigation Trust Score from what was actually retrieved.

Every check answers a question about *grounding*, never about which hypothesis
won. That independence is the point: if this file started reading the primary
hypothesis' confidence, the second number would stop being a second opinion.
"""

from __future__ import annotations

from typing import Any

from app.agents.context import InvestigationContext
from app.domain.enums import EvidenceType, Relevance
from app.domain.evidence import EvidenceItem
from app.domain.hypothesis import HypothesisCandidate
from app.domain.trust import WEIGHTS, TrustCheck, TrustCheckStatus, TrustScore

CAUSAL_TYPES = {
    EvidenceType.SCHEMA_CHANGE,
    EvidenceType.QUALITY_ANOMALY,
    EvidenceType.PIPELINE_CHANGE,
    EvidenceType.LINEAGE_DEPENDENCY,
    EvidenceType.ML_SIGNAL,
}


def _evidence_quality(evidence: list[EvidenceItem]) -> TrustCheck:
    """Breadth and weight of the signals, ignoring which hypothesis they favour."""
    causal = [e for e in evidence if e.type in CAUSAL_TYPES]
    distinct_types = {e.type for e in causal}
    high = [e for e in causal if e.relevance is Relevance.HIGH]

    breadth = min(len(distinct_types) / 4.0, 1.0) * (WEIGHTS["evidence_quality"] * 0.6)
    weight = min(len(high) / 3.0, 1.0) * (WEIGHTS["evidence_quality"] * 0.4)
    points = breadth + weight

    if not causal:
        status = TrustCheckStatus.FAIL
        detail = "No causal signal was collected; only the reported symptom is available."
    elif len(distinct_types) >= 3 and len(high) >= 2:
        status = TrustCheckStatus.PASS
        detail = (
            f"{len(causal)} causal signals across {len(distinct_types)} independent "
            f"types, {len(high)} of them high relevance."
        )
    else:
        status = TrustCheckStatus.PARTIAL
        detail = (
            f"{len(causal)} causal signals across {len(distinct_types)} type(s); "
            "corroboration is thin."
        )
    return TrustCheck(
        "evidence_quality", status, points, WEIGHTS["evidence_quality"], detail
    )


def _schema_validation(
    context: InvestigationContext, primary: HypothesisCandidate | None
) -> TrustCheck:
    """Was the schema actually read, and does the implicated field exist in it?

    A root cause naming a field nobody verified is the most common way an
    incident write-up ends up wrong, so this check looks the field up.
    """
    max_points = WEIGHTS["schema_validation"]
    fields = (context.schema or {}).get("fields") or []
    if not fields:
        return TrustCheck(
            "schema_validation",
            TrustCheckStatus.FAIL,
            0.0,
            max_points,
            "The schema of the affected asset could not be retrieved.",
        )

    known_paths = {
        str(field_def.get("path", "")).lower()
        for payload in context.schemas.values()
        for field_def in (payload.get("fields") or [])
    }

    cited_fields = {
        e.field_path.lower()
        for e in (primary.supporting if primary else [])
        if e.field_path
    }
    if not cited_fields:
        return TrustCheck(
            "schema_validation",
            TrustCheckStatus.PARTIAL,
            max_points * 0.6,
            max_points,
            f"Schemas retrieved for {len(context.schemas)} asset(s) but the conclusion "
            "names no field to verify.",
        )

    resolved = sorted(f for f in cited_fields if f in known_paths)
    unresolved = sorted(f for f in cited_fields if f not in known_paths)

    if not unresolved:
        return TrustCheck(
            "schema_validation",
            TrustCheckStatus.PASS,
            max_points,
            max_points,
            f"Every field named by the conclusion exists in the retrieved schemas: {', '.join(resolved)}.",
        )
    if resolved:
        return TrustCheck(
            "schema_validation",
            TrustCheckStatus.PARTIAL,
            max_points * 0.5,
            max_points,
            f"Verified {', '.join(resolved)}; could not locate {', '.join(unresolved)} in any retrieved schema.",
        )
    return TrustCheck(
        "schema_validation",
        TrustCheckStatus.FAIL,
        0.0,
        max_points,
        f"The conclusion names {', '.join(unresolved)}, absent from every retrieved schema.",
    )


def _lineage_coverage(
    context: InvestigationContext, evidence: list[EvidenceItem]
) -> TrustCheck:
    """Both directions walked, and no signal cited from outside the graph."""
    max_points = WEIGHTS["lineage_coverage"]
    upstream = context.upstream
    downstream = context.downstream

    if not upstream and not downstream:
        return TrustCheck(
            "lineage_coverage",
            TrustCheckStatus.FAIL,
            0.0,
            max_points,
            "No lineage was retrieved, so nothing connects the signals to the incident.",
        )

    cited_assets = {e.asset_urn for e in evidence if e.asset_urn}
    known = {node.get("urn") for node in context.nodes}
    known.add(context.asset_urn)
    # Data jobs are legitimately outside a table-level lineage graph.
    orphans = {
        urn for urn in cited_assets if urn not in known and ":dataJob:" not in (urn or "")
    }

    if upstream and downstream and not orphans:
        return TrustCheck(
            "lineage_coverage",
            TrustCheckStatus.PASS,
            max_points,
            max_points,
            f"{len(upstream)} upstream and {len(downstream)} downstream assets walked; "
            "every cited asset sits in the graph.",
        )
    if orphans:
        return TrustCheck(
            "lineage_coverage",
            TrustCheckStatus.PARTIAL,
            max_points * 0.4,
            max_points,
            f"{len(orphans)} cited asset(s) are not connected to the incident in the retrieved lineage.",
        )
    side = "upstream" if upstream else "downstream"
    return TrustCheck(
        "lineage_coverage",
        TrustCheckStatus.PARTIAL,
        max_points * 0.5,
        max_points,
        f"Only the {side} side was retrieved; the other direction is unknown.",
    )


def _quality_signals(
    context: InvestigationContext, evidence: list[EvidenceItem]
) -> TrustCheck:
    max_points = WEIGHTS["quality_signals"]
    assertions = (context.quality or {}).get("assertions") or []
    observed = [e for e in evidence if e.type is EvidenceType.QUALITY_ANOMALY]

    if observed and assertions:
        return TrustCheck(
            "quality_signals",
            TrustCheckStatus.PASS,
            max_points,
            max_points,
            f"{len(assertions)} quality checks known to DataHub and "
            f"{len(observed)} measured anomalies corroborate the incident.",
        )
    if observed or assertions:
        return TrustCheck(
            "quality_signals",
            TrustCheckStatus.PARTIAL,
            max_points * 0.6,
            max_points,
            (
                f"{len(observed)} measured anomalies, but the asset declares no quality check."
                if observed
                else f"{len(assertions)} quality checks declared, none of them firing."
            ),
        )
    return TrustCheck(
        "quality_signals",
        TrustCheckStatus.FAIL,
        0.0,
        max_points,
        "No quality context was available for this asset.",
    )


def _historical_match(
    matches: list[Any], pattern: str | None
) -> TrustCheck:
    max_points = WEIGHTS["historical_match"]
    if not matches:
        return TrustCheck(
            "historical_match",
            TrustCheckStatus.FAIL,
            0.0,
            max_points,
            "First time this shape of incident is seen; there is no precedent to lean on.",
        )

    same_pattern = [m for m in matches if pattern and getattr(m, "pattern", None) == pattern]
    if same_pattern:
        best = max(same_pattern, key=lambda m: getattr(m, "similarity", 0.0))
        return TrustCheck(
            "historical_match",
            TrustCheckStatus.PASS,
            max_points,
            max_points,
            (
                f"A previous investigation reached the same conclusion "
                f"({best.pattern}) with {best.similarity:.0%} similarity, and its "
                "remediation was verified."
            ),
        )
    return TrustCheck(
        "historical_match",
        TrustCheckStatus.PARTIAL,
        max_points * 0.45,
        max_points,
        (
            f"{len(matches)} past investigation(s) on related assets, but none "
            "reached this conclusion — the precedent does not confirm it."
        ),
    )


def compute_trust_score(
    context: InvestigationContext,
    evidence: list[EvidenceItem],
    primary: HypothesisCandidate | None,
    previous_matches: list[Any],
) -> TrustScore:
    return TrustScore(
        checks=[
            _evidence_quality(evidence),
            _schema_validation(context, primary),
            _lineage_coverage(context, evidence),
            _quality_signals(context, evidence),
            _historical_match(previous_matches, primary.pattern if primary else None),
        ]
    )
