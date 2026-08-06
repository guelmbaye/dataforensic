"""Deterministic DataHub provider backed by a local context graph.

Used for CI, offline development and as the demo fallback. Every result it
returns is tagged SourceMode.DEMO_FIXTURE and the API surfaces that tag, so the
product can never claim that live DataHub was queried when it was not
(DOCUMENT 03 - section 14, DOCUMENT 07 - section 20).
"""

from __future__ import annotations

import json
import threading
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import settings
from app.core.logging import get_logger
from app.core.utils import parse_dt, to_iso, urn_entity_type, urn_name, utcnow
from app.domain.enums import SourceMode, SourceSystem
from app.services.datahub.base import DataHubProvider, ToolResult

logger = get_logger(__name__)
_LOCK = threading.Lock()


def _load_graph(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"DataHub fixture graph not found: {path}")
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class FixtureDataHubProvider(DataHubProvider):
    name = "fixture"
    source_mode = SourceMode.DEMO_FIXTURE

    def __init__(self, path: Path | None = None, memory_store: Path | None = None) -> None:
        self.path = path or settings.fixture_file
        self.memory_store_path = memory_store or settings.memory_store_file
        self.graph = _load_graph(self.path)
        self.entities: dict[str, dict[str, Any]] = {
            e["urn"]: e for e in self.graph.get("entities", [])
        }
        self.edges: list[dict[str, Any]] = self.graph.get("lineage", [])
        self._downstream: dict[str, list[dict[str, Any]]] = {}
        self._upstream: dict[str, list[dict[str, Any]]] = {}
        for edge in self.edges:
            self._downstream.setdefault(edge["upstream"], []).append(edge)
            self._upstream.setdefault(edge["downstream"], []).append(edge)
        self.changes: list[dict[str, Any]] = self.graph.get("changes", [])
        self.assertions: list[dict[str, Any]] = self.graph.get("assertions", [])
        self._memory: dict[str, dict[str, Any]] = self._load_memory()

    # -- memory store -----------------------------------------------------
    def _load_memory(self) -> dict[str, dict[str, Any]]:
        try:
            if self.memory_store_path.exists():
                with self.memory_store_path.open(encoding="utf-8") as handle:
                    return json.load(handle)
        except (OSError, json.JSONDecodeError):  # pragma: no cover - defensive
            logger.warning("fixture_memory_store_unreadable", extra={"path": str(self.memory_store_path)})
        return {}

    def _persist_memory(self) -> None:
        with _LOCK:
            self.memory_store_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.memory_store_path.with_suffix(".tmp")
            with tmp.open("w", encoding="utf-8") as handle:
                json.dump(self._memory, handle, indent=2, default=str)
            tmp.replace(self.memory_store_path)

    def reset_memory(self) -> None:
        self._memory = {}
        if self.memory_store_path.exists():
            self.memory_store_path.unlink()

    # -- normalisation ----------------------------------------------------
    def _node(self, urn: str, distance: int = 0, direction: str = "SELF") -> dict[str, Any]:
        entity = self.entities.get(urn, {})
        return {
            "urn": urn,
            "name": entity.get("name") or urn_name(urn),
            "entity_type": entity.get("type") or urn_entity_type(urn),
            "platform": entity.get("platform"),
            "distance": distance,
            "direction": direction,
            "tags": entity.get("tags", []),
            "domain": entity.get("domain"),
            "criticality": entity.get("criticality", "MEDIUM"),
            "owners": entity.get("owners", []),
            "known": urn in self.entities,
        }

    def _asset(self, urn: str) -> dict[str, Any]:
        entity = self.entities[urn]
        return {
            "urn": urn,
            "name": entity.get("name", urn_name(urn)),
            "entity_type": entity.get("type", urn_entity_type(urn)),
            "platform": entity.get("platform"),
            "env": entity.get("env", "PROD"),
            "description": entity.get("description", ""),
            "domain": entity.get("domain"),
            "tags": entity.get("tags", []),
            "glossary_terms": entity.get("glossary_terms", []),
            "owners": entity.get("owners", []),
            "criticality": entity.get("criticality", "MEDIUM"),
            "properties": entity.get("properties", {}),
            "schema_fields": (entity.get("schema") or {}).get("fields", []),
            "ml_context": entity.get("ml_context"),
            "institutional_memory": entity.get("institutional_memory", []),
        }

    def _missing(self, tool: str, urn: str) -> ToolResult:
        return ToolResult.fail(
            tool,
            f"Asset not found in DataHub context graph: {urn}",
            source=f"fixture:{self.path.name}",
            source_mode=self.source_mode,
        )

    def _ok(self, tool: str, data: Any) -> ToolResult:
        return ToolResult.ok(
            tool,
            data,
            source=f"fixture:{self.path.name}",
            source_mode=self.source_mode,
            source_system=SourceSystem.DATAHUB,
        )

    # -- provider API -----------------------------------------------------
    async def health(self) -> ToolResult:
        return self._ok(
            "health",
            {
                "connected": True,
                "graph": self.graph.get("name", self.path.stem),
                "entities": len(self.entities),
                "lineage_edges": len(self.edges),
                "changes": len(self.changes),
                "assertions": len(self.assertions),
            },
        )

    async def get_asset_context(self, urn: str) -> ToolResult:
        if urn not in self.entities:
            return self._missing("get_asset_context", urn)
        return self._ok("get_asset_context", self._asset(urn))

    async def get_schema(self, urn: str) -> ToolResult:
        if urn not in self.entities:
            return self._missing("get_schema", urn)
        schema = self.entities[urn].get("schema") or {}
        return self._ok(
            "get_schema",
            {
                "urn": urn,
                "fields": schema.get("fields", []),
                "version": schema.get("version"),
                "last_modified": schema.get("last_modified"),
            },
        )

    async def get_lineage(self, urn: str, direction: str = "BOTH", depth: int = 3) -> ToolResult:
        if urn not in self.entities:
            return self._missing("get_lineage", urn)
        directions = ["UPSTREAM", "DOWNSTREAM"] if direction.upper() == "BOTH" else [direction.upper()]
        nodes: dict[str, dict[str, Any]] = {urn: self._node(urn, 0, "SELF")}
        edges: list[dict[str, Any]] = []
        for way in directions:
            adjacency = self._upstream if way == "UPSTREAM" else self._downstream
            key = "upstream" if way == "UPSTREAM" else "downstream"
            queue: deque[tuple[str, int]] = deque([(urn, 0)])
            seen = {urn}
            while queue:
                current, dist = queue.popleft()
                if dist >= depth:
                    continue
                for edge in adjacency.get(current, []):
                    neighbour = edge[key]
                    edges.append(
                        {
                            "upstream": edge["upstream"],
                            "downstream": edge["downstream"],
                            "via": edge.get("via"),
                            "type": edge.get("type", "TRANSFORMED"),
                        }
                    )
                    if neighbour in seen:
                        continue
                    seen.add(neighbour)
                    node = self._node(neighbour, dist + 1, way)
                    existing = nodes.get(neighbour)
                    if existing is None or existing["distance"] > node["distance"]:
                        nodes[neighbour] = node
                    queue.append((neighbour, dist + 1))
        deduped = {(e["upstream"], e["downstream"], e.get("via")): e for e in edges}
        return self._ok(
            "get_lineage",
            {
                "urn": urn,
                "direction": direction.upper(),
                "depth": depth,
                "nodes": sorted(nodes.values(), key=lambda n: (n["distance"], n["urn"])),
                "edges": list(deduped.values()),
            },
        )

    async def get_ownership(self, urn: str) -> ToolResult:
        if urn not in self.entities:
            return self._missing("get_ownership", urn)
        return self._ok(
            "get_ownership",
            {"urn": urn, "owners": self.entities[urn].get("owners", [])},
        )

    async def get_quality_context(self, urn: str) -> ToolResult:
        if urn not in self.entities:
            return self._missing("get_quality_context", urn)
        items = [a for a in self.assertions if a.get("asset_urn") == urn]
        return self._ok(
            "get_quality_context",
            {
                "urn": urn,
                "assertions": items,
                "has_quality_signals": bool(items),
            },
        )

    async def find_changes(
        self, urn: str, since: datetime | str | None = None, until: datetime | str | None = None
    ) -> ToolResult:
        if urn not in self.entities:
            return self._missing("find_changes", urn)
        # Callers may pass ISO strings (tool arguments are JSON) or datetimes.
        since = parse_dt(since)
        until = parse_dt(until)
        selected: list[dict[str, Any]] = []
        for change in self.changes:
            if change.get("entity_urn") != urn:
                continue
            moment = parse_dt(change.get("timestamp"))
            if since and moment and moment < since:
                continue
            if until and moment and moment > until:
                continue
            selected.append(change)
        selected.sort(key=lambda c: c.get("timestamp") or "")
        return self._ok(
            "find_changes",
            {
                "urn": urn,
                "window": {"since": to_iso(since), "until": to_iso(until)},
                "changes": selected,
            },
        )

    async def find_related_assets(self, urn: str, limit: int = 20) -> ToolResult:
        if urn not in self.entities:
            return self._missing("find_related_assets", urn)
        base = self.entities[urn]
        base_tags = set(base.get("tags", []))
        base_terms = set(base.get("glossary_terms", []))
        base_domain = base.get("domain")
        scored: list[tuple[float, dict[str, Any]]] = []
        for other_urn, other in self.entities.items():
            if other_urn == urn:
                continue
            score = 0.0
            if base_domain and other.get("domain") == base_domain:
                score += 0.4
            score += 0.3 * len(base_tags & set(other.get("tags", [])))
            score += 0.5 * len(base_terms & set(other.get("glossary_terms", [])))
            if score > 0:
                node = self._node(other_urn)
                node["relation_score"] = round(score, 3)
                scored.append((score, node))
        scored.sort(key=lambda item: item[0], reverse=True)
        return self._ok(
            "find_related_assets",
            {"urn": urn, "related": [node for _, node in scored[:limit]]},
        )

    async def search_assets(self, query: str, limit: int = 10) -> ToolResult:
        needle = query.lower().strip()
        results = [
            self._node(urn)
            for urn, entity in self.entities.items()
            if needle in urn.lower()
            or needle in str(entity.get("name", "")).lower()
            or needle in str(entity.get("description", "")).lower()
        ]
        return self._ok("search_assets", {"query": query, "results": results[:limit]})

    async def write_incident_memory(
        self, document: dict[str, Any], affected_urns: list[str]
    ) -> ToolResult:
        target = document.get("asset_urn")
        if target not in self.entities:
            return self._missing("write_incident_memory", str(target))
        reference = f"{target}#dataforensic-incident-{document.get('incident_id')}"
        record = {
            "reference": reference,
            "document": document,
            "affected_urns": affected_urns,
            "written_at": to_iso(utcnow()),
            "tags_applied": [f"DataForensic:{document.get('pattern')}"],
        }
        self._memory[reference] = record
        self._persist_memory()
        # Attach to the graph exactly like DataHub institutional memory would.
        for urn in {target, *affected_urns}:
            entity = self.entities.get(urn)
            if not entity:
                continue
            entity.setdefault("institutional_memory", []).append(
                {
                    "url": f"{settings.public_app_url}/investigations/"
                    f"{document.get('investigation_id')}",
                    "label": f"DATAFORENSIC incident {document.get('incident_id')}",
                    "description": document.get("root_cause", ""),
                }
            )
            tags = entity.setdefault("tags", [])
            tag = f"DataForensic:{document.get('pattern')}"
            if tag not in tags:
                tags.append(tag)
        return self._ok(
            "write_incident_memory",
            {"reference": reference, "operations": ["institutional_memory", "tag"], **record},
        )

    async def read_incident_memory(self, reference: str) -> ToolResult:
        record = self._memory.get(reference)
        if not record:
            return ToolResult.fail(
                "read_incident_memory",
                f"No incident memory found for reference {reference}",
                source=f"fixture:{self.path.name}",
                source_mode=self.source_mode,
            )
        return self._ok("read_incident_memory", record)

    async def search_incident_memory(
        self, pattern: str | None = None, asset_urn: str | None = None, limit: int = 10
    ) -> ToolResult:
        matches: list[dict[str, Any]] = []
        for record in self._memory.values():
            doc = record.get("document", {})
            if pattern and doc.get("pattern") != pattern:
                continue
            if asset_urn and asset_urn not in {doc.get("asset_urn"), *record.get("affected_urns", [])}:
                continue
            matches.append(record)
        matches.sort(key=lambda r: r.get("written_at") or "", reverse=True)
        return self._ok(
            "search_incident_memory",
            {"pattern": pattern, "asset_urn": asset_urn, "matches": matches[:limit]},
        )
