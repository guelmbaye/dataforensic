"""Blast radius computation (DOCUMENT 04 - section 11).

Numbers are always derived from the retrieved lineage graph. Nothing here is
hardcoded for the demo scenario.
"""

from __future__ import annotations

from typing import Any

from app.domain.enums import ImpactLevel

ENTITY_BUCKETS: dict[str, str] = {
    "DATASET": "datasets",
    "DASHBOARD": "dashboards",
    "CHART": "charts",
    "MLMODEL": "ml_assets",
    "MLMODELGROUP": "ml_assets",
    "MLFEATURETABLE": "ml_assets",
    "MLPRIMARYKEY": "ml_assets",
    "MLFEATURE": "ml_assets",
    "DATAJOB": "data_jobs",
    "DATAFLOW": "data_jobs",
    "NOTEBOOK": "consumers_other",
    "CONTAINER": "consumers_other",
}

CONSUMER_BUCKETS = {"dashboards", "charts", "ml_assets", "consumers_other"}

WEIGHTS: dict[str, float] = {
    "datasets": 4.0,
    "dashboards": 8.0,
    "charts": 3.0,
    "ml_assets": 12.0,
    "data_jobs": 3.0,
    "consumers_other": 2.0,
}

CRITICAL_TAGS = {"tier1", "critical", "pii", "gdpr", "finance", "regulatory", "sox"}


def _bucket(entity_type: str | None) -> str:
    return ENTITY_BUCKETS.get(str(entity_type or "").upper(), "consumers_other")


def _risk_level(score: float) -> ImpactLevel:
    if score >= 70:
        return ImpactLevel.CRITICAL
    if score >= 45:
        return ImpactLevel.HIGH
    if score >= 20:
        return ImpactLevel.MEDIUM
    return ImpactLevel.LOW


def _count_consumers(
    lineage: dict[str, Any],
    affected: list[dict[str, Any]],
    counts: dict[str, int],
) -> int:
    """Terminal consumers of the affected data.

    A consumer is an impacted asset that nothing else in the impacted set reads
    from: the end of the chain, where a human or a model actually consumes the
    corrupted values. Intermediate datasets are impacted but are not the point
    of consumption. When the graph carries no edges we fall back to counting the
    consumption-oriented entity types.
    """
    edges = lineage.get("edges") or []
    if not edges:
        return sum(counts.get(bucket, 0) for bucket in CONSUMER_BUCKETS)
    impacted = {node["urn"] for node in affected if node.get("urn")}
    produces_for_impacted = {
        edge.get("upstream")
        for edge in edges
        if edge.get("downstream") in impacted
    }
    return sum(1 for urn in impacted if urn not in produces_for_impacted)


def calculate_blast_radius(
    lineage: dict[str, Any],
    origin_urn: str,
    origin_name: str | None = None,
    include_self: bool = False,
) -> dict[str, Any]:
    nodes = [
        node
        for node in lineage.get("nodes", [])
        if node.get("direction") == "DOWNSTREAM" or (include_self and node.get("urn") == origin_urn)
    ]

    counts: dict[str, int] = {key: 0 for key in WEIGHTS}
    affected: list[dict[str, Any]] = []
    critical_assets: list[dict[str, Any]] = []
    owners: dict[str, dict[str, Any]] = {}
    score = 0.0
    factors: list[str] = []

    for node in nodes:
        bucket = _bucket(node.get("entity_type"))
        counts[bucket] = counts.get(bucket, 0) + 1
        weight = WEIGHTS.get(bucket, 2.0)
        # Closer assets are more certainly impacted.
        distance = max(int(node.get("distance") or 1), 1)
        score += weight / (1 + 0.25 * (distance - 1))

        tags = {str(t).lower() for t in (node.get("tags") or [])}
        criticality = str(node.get("criticality") or "MEDIUM").upper()
        is_critical = bool(tags & CRITICAL_TAGS) or criticality in {"HIGH", "CRITICAL"}
        if is_critical:
            score += 6.0
            critical_assets.append(
                {"urn": node.get("urn"), "name": node.get("name"), "reason": sorted(tags & CRITICAL_TAGS) or criticality}
            )

        for owner in node.get("owners") or []:
            key = owner.get("urn") or owner.get("name")
            if not key:
                continue
            entry = owners.setdefault(
                key,
                {
                    "urn": owner.get("urn"),
                    "name": owner.get("name"),
                    "email": owner.get("email"),
                    "type": owner.get("type", "DATAOWNER"),
                    "assets": [],
                },
            )
            entry["assets"].append(node.get("urn"))

        affected.append(
            {
                "urn": node.get("urn"),
                "name": node.get("name"),
                "entity_type": node.get("entity_type"),
                "platform": node.get("platform"),
                "distance": node.get("distance"),
                "criticality": criticality,
                "tags": node.get("tags", []),
                "bucket": bucket,
                "owners": node.get("owners", []),
            }
        )

    total = len(affected)
    consumers = _count_consumers(lineage, affected, counts)

    if counts.get("ml_assets"):
        factors.append(f"{counts['ml_assets']} ML asset(s) consume the affected data")
    if counts.get("dashboards"):
        factors.append(f"{counts['dashboards']} dashboard(s) rely on the affected data")
    if critical_assets:
        factors.append(f"{len(critical_assets)} downstream asset(s) are business critical")
    if len(owners) > 1:
        factors.append(f"{len(owners)} distinct owning team(s) impacted")
    if total == 0:
        factors.append("No downstream consumer found in the lineage graph")

    score = min(score, 100.0)
    level = _risk_level(score) if total else ImpactLevel.LOW

    return {
        "origin_urn": origin_urn,
        "origin_name": origin_name,
        "counts": counts,
        "total_affected_assets": total,
        "consumers": consumers,
        "owners": sorted(owners.values(), key=lambda o: str(o.get("name") or "")),
        "owner_count": len(owners),
        "risk_level": str(level),
        "risk_score": round(score, 1),
        "risk_factors": factors,
        "critical_assets": critical_assets,
        "affected_assets": sorted(affected, key=lambda a: (a["distance"] or 0, a["name"] or "")),
        "computed_from": {
            "lineage_direction": lineage.get("direction"),
            "lineage_depth": lineage.get("depth"),
            "lineage_node_count": len(lineage.get("nodes", [])),
        },
    }
