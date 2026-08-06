"""DataHub Skill — Incident Investigation.

Turns "this asset is misbehaving" into the structured context an investigating
agent needs, using only DataHub reads. No root cause logic, no scenario logic,
no writes.

Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, runtime_checkable

__all__ = ["IncidentInvestigationSkill", "SkillError", "DataHubReader"]

SCHEMA_VERSION = "1.0"

CONSUMER_ENTITY_TYPES = {
    "DASHBOARD": "dashboards",
    "CHART": "charts",
    "MLMODEL": "ml_assets",
    "MLMODELGROUP": "ml_assets",
    "MLFEATURETABLE": "ml_assets",
    "MLFEATURE": "ml_assets",
    "NOTEBOOK": "notebooks",
}


class SkillError(RuntimeError):
    """Raised when required DataHub context cannot be retrieved.

    Failing loudly matters here: an investigation built on silently missing
    context produces a confident answer about nothing.
    """


@runtime_checkable
class DataHubReader(Protocol):
    """The read surface this skill needs. The MCP server satisfies it."""

    async def get_asset_context(self, urn: str) -> Any: ...
    async def get_schema(self, urn: str) -> Any: ...
    async def get_lineage(self, urn: str, direction: str = "BOTH", depth: int = 3) -> Any: ...
    async def get_ownership(self, urn: str) -> Any: ...
    async def get_quality_context(self, urn: str) -> Any: ...
    async def find_changes(self, urn: str, since: Any = None, until: Any = None) -> Any: ...


def _unwrap(result: Any, what: str, required: bool = False) -> dict[str, Any]:
    """Normalise a client response into a plain dict.

    Clients differ: some return a rich result object with `success`/`data`,
    others return the payload directly. Both are accepted; a failure is either
    raised (required context) or degraded to an empty dict (optional context).
    """
    if result is None:
        if required:
            raise SkillError(f"{what}: no response from the DataHub client")
        return {}
    success = getattr(result, "success", None)
    if success is False:
        error = getattr(result, "error", "unknown error")
        if required:
            raise SkillError(f"{what}: {error}")
        return {}
    data = getattr(result, "data", result)
    return data if isinstance(data, dict) else {}


def _parse_time(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


class IncidentInvestigationSkill:
    def __init__(self, client: DataHubReader) -> None:
        self.client = client

    # -- context ----------------------------------------------------------
    async def collect_incident_context(
        self,
        asset_urn: str,
        incident_time: Any = None,
        depth: int = 3,
        lookback_minutes: int = 720,
    ) -> dict[str, Any]:
        """Everything an agent needs before it can form a hypothesis."""
        asset = _unwrap(await self.client.get_asset_context(asset_urn), "asset context", True)
        lineage = _unwrap(
            await self.client.get_lineage(asset_urn, "BOTH", depth), "lineage", True
        )
        schema = _unwrap(await self.client.get_schema(asset_urn), "schema")
        ownership = _unwrap(await self.client.get_ownership(asset_urn), "ownership")
        quality = _unwrap(await self.client.get_quality_context(asset_urn), "quality context")
        changes = await self.find_recent_changes(
            asset_urn, incident_time, lookback_minutes, lineage=lineage
        )

        nodes = lineage.get("nodes", [])
        return {
            "asset_urn": asset_urn,
            "asset": asset,
            "schema": schema,
            "owners": ownership.get("owners", []),
            "quality_signals": quality.get("assertions", []),
            "upstream_paths": self._paths(nodes, "UPSTREAM"),
            "downstream_paths": self._paths(nodes, "DOWNSTREAM"),
            "lineage_edges": lineage.get("edges", []),
            "recent_changes": changes,
            "incident_time": incident_time,
            "counts": {
                "upstream": sum(1 for n in nodes if n.get("direction") == "UPSTREAM"),
                "downstream": sum(1 for n in nodes if n.get("direction") == "DOWNSTREAM"),
                "quality_signals": len(quality.get("assertions", [])),
                "changed_assets": len(changes),
            },
        }

    @staticmethod
    def _paths(nodes: list[dict[str, Any]], direction: str) -> list[dict[str, Any]]:
        selected = [n for n in nodes if n.get("direction") == direction]
        selected.sort(key=lambda n: (n.get("distance") or 0, str(n.get("name") or "")))
        return [
            {
                "urn": node.get("urn"),
                "name": node.get("name"),
                "entity_type": node.get("entity_type"),
                "platform": node.get("platform"),
                "distance": node.get("distance"),
                "owners": node.get("owners", []),
                "tags": node.get("tags", []),
            }
            for node in selected
        ]

    # -- lineage ----------------------------------------------------------
    async def trace_incident_lineage(self, asset_urn: str, depth: int = 3) -> dict[str, Any]:
        """Upstream assets that can carry a defect into this one, nearest first."""
        lineage = _unwrap(
            await self.client.get_lineage(asset_urn, "UPSTREAM", depth), "lineage", True
        )
        edges = lineage.get("edges", [])
        return {
            "asset_urn": asset_urn,
            "depth": depth,
            "upstream": self._paths(lineage.get("nodes", []), "UPSTREAM"),
            "paths_to_target": {
                node["urn"]: self._path_between(edges, node["urn"], asset_urn)
                for node in self._paths(lineage.get("nodes", []), "UPSTREAM")
                if node.get("urn")
            },
        }

    @staticmethod
    def _path_between(edges: list[dict[str, Any]], source: str, target: str) -> list[str]:
        """Shortest hop sequence from source to target, for explainability."""
        adjacency: dict[str, list[str]] = {}
        for edge in edges:
            adjacency.setdefault(edge.get("upstream"), []).append(edge.get("downstream"))
        queue: deque[tuple[str, list[str]]] = deque([(source, [source])])
        seen = {source}
        while queue:
            current, path = queue.popleft()
            if current == target:
                return path
            for neighbour in adjacency.get(current, []):
                if neighbour and neighbour not in seen:
                    seen.add(neighbour)
                    queue.append((neighbour, [*path, neighbour]))
        return []

    # -- changes ----------------------------------------------------------
    async def find_recent_changes(
        self,
        asset_urn: str,
        incident_time: Any = None,
        lookback_minutes: int = 720,
        max_upstream: int = 15,
        lineage: dict[str, Any] | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """Change history on the asset and its nearest upstream assets.

        Scoped on purpose: querying the whole graph is slow and produces noise
        that looks like evidence. Start at the asset, widen along lineage.
        """
        moment = _parse_time(incident_time)
        since = moment - timedelta(minutes=lookback_minutes) if moment else None
        until = moment + timedelta(minutes=30) if moment else None

        if lineage is None:
            lineage = _unwrap(
                await self.client.get_lineage(asset_urn, "UPSTREAM", 3), "lineage", True
            )
        upstream = self._paths(lineage.get("nodes", []), "UPSTREAM")[:max_upstream]

        found: dict[str, list[dict[str, Any]]] = {}
        for urn in [asset_urn, *(node["urn"] for node in upstream if node.get("urn"))]:
            payload = _unwrap(await self.client.find_changes(urn, since, until), "changes")
            entries = payload.get("changes", [])
            if entries:
                found[urn] = entries
        return found

    # -- impact -----------------------------------------------------------
    async def summarise_downstream_impact(
        self, asset_urn: str, depth: int = 3
    ) -> dict[str, Any]:
        """Who is affected, bucketed by entity type, with owners aggregated."""
        lineage = _unwrap(
            await self.client.get_lineage(asset_urn, "DOWNSTREAM", depth), "lineage", True
        )
        nodes = self._paths(lineage.get("nodes", []), "DOWNSTREAM")

        counts: dict[str, int] = {}
        owners: dict[str, dict[str, Any]] = {}
        for node in nodes:
            bucket = CONSUMER_ENTITY_TYPES.get(
                str(node.get("entity_type") or "").upper(), "datasets"
            )
            counts[bucket] = counts.get(bucket, 0) + 1
            for owner in node.get("owners") or []:
                key = owner.get("urn") or owner.get("name")
                if not key:
                    continue
                entry = owners.setdefault(key, {**owner, "assets": []})
                entry["assets"].append(node.get("urn"))

        impacted = {node["urn"] for node in nodes if node.get("urn")}
        producers = {
            edge.get("upstream")
            for edge in lineage.get("edges", [])
            if edge.get("downstream") in impacted
        }
        return {
            "origin_urn": asset_urn,
            "counts": counts,
            "total_affected_assets": len(nodes),
            "terminal_consumers": sum(1 for urn in impacted if urn not in producers),
            "owners": list(owners.values()),
            "owner_count": len(owners),
            "affected_assets": nodes,
        }

    # -- memory -----------------------------------------------------------
    async def find_similar_incident(
        self,
        asset_urn: str | None = None,
        pattern: str | None = None,
        symptom: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Look for a comparable past investigation, if the client supports it."""
        search = getattr(self.client, "search_incident_memory", None)
        if not callable(search):
            return []
        payload = _unwrap(
            await search(asset_urn=asset_urn, pattern=pattern, symptom=symptom), "incident memory"
        )
        return list(payload.get("matches", []))[:limit]

    # -- write-back -------------------------------------------------------
    REQUIRED_FIELDS = ("incident_id", "asset_urn", "pattern", "root_cause", "confidence")

    def prepare_incident_writeback(self, summary: dict[str, Any]) -> dict[str, Any]:
        """Validate and normalise an investigation into a write-back document.

        The caller performs the write. This function exists so that whatever an
        agent (or an LLM) produced is checked into a known shape first: an
        unvalidated write is how a context graph gets polluted.
        """
        missing = [field for field in self.REQUIRED_FIELDS if not summary.get(field)]
        if missing:
            raise SkillError(f"incident write-back is missing required fields: {missing}")

        confidence = float(summary["confidence"])
        if not 0.0 <= confidence <= 1.0:
            raise SkillError("confidence must be expressed between 0 and 1")

        evidence = [
            {
                "type": str(item.get("type", "UNKNOWN")),
                "observation": str(item.get("observation", ""))[:500],
                "asset_urn": item.get("asset_urn"),
                "relevance": str(item.get("relevance", "MEDIUM")),
            }
            for item in summary.get("evidence", [])
        ]

        return {
            "schema_version": SCHEMA_VERSION,
            "incident_id": str(summary["incident_id"]),
            "asset_urn": str(summary["asset_urn"]),
            "pattern": str(summary["pattern"]).upper().replace(" ", "_"),
            "symptom": str(summary.get("symptom", ""))[:500],
            "root_cause": str(summary["root_cause"])[:1000],
            "confidence": round(confidence, 4),
            "evidence": evidence,
            "affected_assets": [str(urn) for urn in summary.get("affected_assets", [])],
            "remediation": [str(step) for step in summary.get("remediation", [])],
            "verification": str(summary.get("verification", "UNKNOWN")),
            "resolved_at": summary.get("resolved_at"),
            "tag": f"DataForensic:{str(summary['pattern']).upper().replace(' ', '_')}",
        }
