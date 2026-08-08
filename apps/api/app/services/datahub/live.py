"""Live DataHub provider.

Primary path : DataHub MCP Server (tools/call).
Fallback path: DataHub GraphQL + Timeline API (stable, normalised shapes).

Whichever transport served a call is reported in ToolResult.source, so the UI
can prove which system answered.
"""

from __future__ import annotations

import functools
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import settings
from app.core.logging import get_logger
from app.core.utils import parse_dt, to_iso, urn_entity_type, urn_name, utcnow
from app.domain.enums import SourceMode, SourceSystem
from app.services.datahub.base import DataHubProvider, ToolResult
from app.services.datahub.graphql import (
    ADD_LINK,
    ADD_TAGS,
    ASSERTIONS_QUERY,
    CREATE_TAG,
    DATASET_QUERY,
    LINEAGE_QUERY,
    SEARCH_QUERY,
    DataHubGraphQLClient,
)
from app.services.datahub.mcp_client import MCPClient

logger = get_logger(__name__)

# Tool names published by the official DataHub MCP server
# (github.com/acryldata/mcp-server-datahub). The first entry of each list is the
# real name; the rest are older or alternative spellings kept because the server
# is versioned independently of this project and a rename must degrade to the
# GraphQL fallback rather than to a crash.
#
# Two operations have no MCP equivalent at all: the change timeline and
# assertion history are only reachable through GraphQL and the Timeline API, so
# they are listed here only for the fuzzy resolver to fail fast and fall back.
MCP_TOOL_CANDIDATES: dict[str, list[str]] = {
    "get_asset_context": ["get_entities", "get_entity", "get_dataset"],
    "get_schema": ["list_schema_fields", "get_dataset_schema", "get_entities"],
    "get_lineage": ["get_lineage", "traverse_lineage", "get_dataset_lineage"],
    "get_ownership": ["get_entities", "get_ownership", "get_entity"],
    "get_quality_context": ["get_assertions", "get_dataset_assertions"],
    "find_changes": ["get_timeline", "get_schema_history"],
    "search_assets": ["search", "search_entities"],
    "find_related_assets": ["search", "search_entities"],
}

# Mutation tools exist on the MCP server from v0.5.0, but only when it is
# started with TOOLS_IS_MUTATION_ENABLED=true. Write-back therefore goes through
# GraphQL, which is available on every DataHub Core instance without an opt-in
# flag — one less thing that has to be true for the demo to work.
MCP_MUTATION_TOOLS: dict[str, list[str]] = {
    "add_tags": ["add_tags"],
    "update_description": ["update_description"],
}


def guarded(method):
    """No exception leaves the provider.

    The contract the rest of the agent is built on is that a DataHub call
    returns a failed ToolResult, never raises: an unreachable catalog must
    *block* an investigation with a readable reason, not crash it with a
    traceback. The failure-mode tests exercised that path with a stub returning
    a failed result, so the real transport errors — DNS, refused connection,
    timeout — walked straight past it and surfaced as
    `ConnectError: [Errno -3] Temporary failure in name resolution` on an
    investigation marked FAILED.
    """

    @functools.wraps(method)
    async def wrapper(self, *args: Any, **kwargs: Any) -> ToolResult:
        try:
            return await method(self, *args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - this is the boundary
            message = self._transport_error(exc)
            logger.warning(
                "datahub_call_failed",
                extra={"tool": method.__name__, "error": message[:300]},
            )
            return self._fail(method.__name__, message)

    return wrapper


class LiveDataHubProvider(DataHubProvider):
    name = "live"
    source_mode = SourceMode.LIVE_DATAHUB

    def __init__(
        self,
        datahub_url: str | None = None,
        token: str | None = None,
        mcp_url: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self.datahub_url = (datahub_url or settings.datahub_url or "").rstrip("/")
        self.mcp_url = mcp_url or settings.datahub_mcp_url
        self.token = token or settings.datahub_token
        self.timeout = timeout or settings.datahub_timeout_seconds
        self.gql = DataHubGraphQLClient(self.datahub_url, self.token, self.timeout) if self.datahub_url else None
        self.mcp = MCPClient(self.mcp_url, self.token, self.timeout) if self.mcp_url else None
        self._mcp_ready = False
        self.mcp_tools: list[str] = []
        # Kept so the failure has somewhere to be read. An empty tool list with
        # `connected: true` is the most misleading state this provider can be in:
        # GMS answers, the bridge answers, and the handshake behind it died.
        self.mcp_error: str | None = None

    def _transport_error(self, exc: Exception) -> str:
        """Say which host failed, and why that usually happens here.

        "Temporary failure in name resolution" on its own does not name the host
        it could not resolve, which is the one thing needed to fix it.
        """
        detail = (str(exc) or exc.__class__.__name__).strip()
        gms_host = urlparse(self.datahub_url).hostname if self.datahub_url else None
        mcp_host = urlparse(self.mcp_url).hostname if self.mcp_url else None

        if isinstance(exc, httpx.ConnectError):
            if "name resolution" in detail.lower() or "nodename" in detail.lower():
                return (
                    f"Cannot resolve the DataHub hostname ('{gms_host}'"
                    + (f"' / '{mcp_host}'" if mcp_host and mcp_host != gms_host else "")
                    + f"): {detail}. DataHub runs in a separate compose project, so its "
                    "containers have to be attached to this network - a network alias "
                    "does not survive recreating them."
                )
            return f"Cannot reach DataHub at '{gms_host}': {detail}."
        if isinstance(exc, httpx.TimeoutException):
            return (
                f"DataHub at '{gms_host}' did not answer within "
                f"{settings.datahub_timeout_seconds}s: {detail}."
            )
        return f"{exc.__class__.__name__}: {detail}"

    # -- transports -------------------------------------------------------
    async def _ensure_mcp(self) -> bool:
        if self.mcp is None:
            return False
        if self._mcp_ready:
            return True
        try:
            await self.mcp.initialize()
            self.mcp_tools = self.mcp.tool_names
            self._mcp_ready = True
            self.mcp_error = None
            logger.info("datahub_mcp_ready", extra={"tools": self.mcp_tools[:20]})
        except Exception as exc:  # noqa: BLE001
            self.mcp_error = f"{exc.__class__.__name__}: {exc}"[:400]
            logger.warning("datahub_mcp_unavailable", extra={"error": self.mcp_error})
            self._mcp_ready = False
        return self._mcp_ready

    def mcp_status(self) -> dict[str, Any]:
        """What the MCP transport is actually doing, including why it is not."""
        if self.mcp is None:
            return {
                "configured": False,
                "ready": False,
                "tools": [],
                "error": None,
                "detail": "No DATAHUB_MCP_URL configured; every read goes through GraphQL.",
            }
        if self._mcp_ready:
            return {
                "configured": True,
                "ready": True,
                "tools": self.mcp_tools,
                "error": None,
                "detail": f"{len(self.mcp_tools)} tool(s) advertised by the MCP server.",
            }
        return {
            "configured": True,
            "ready": False,
            "tools": [],
            "error": self.mcp_error,
            "detail": (
                "The MCP endpoint answered but the handshake did not complete. "
                "Investigations still run: every read falls back to GraphQL."
            ),
        }

    async def _try_mcp(self, operation: str, arguments: dict[str, Any]) -> tuple[bool, Any, str]:
        if not await self._ensure_mcp():
            return False, None, ""
        tool = self.mcp.resolve_tool(MCP_TOOL_CANDIDATES.get(operation, [operation]))
        if not tool:
            return False, None, ""
        try:
            payload = await self.mcp.call_tool(tool, arguments)
            return True, payload, f"datahub-mcp:{tool}"
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "datahub_mcp_tool_failed", extra={"tool": tool, "error": str(exc)}
            )
            return False, None, ""

    def _ok(self, tool: str, data: Any, source: str) -> ToolResult:
        return ToolResult.ok(
            tool,
            data,
            source=source,
            source_mode=self.source_mode,
            source_system=SourceSystem.DATAHUB,
        )

    def _fail(self, tool: str, error: str) -> ToolResult:
        return ToolResult.fail(
            tool, error, source="datahub-live", source_mode=self.source_mode
        )

    # -- normalisation ----------------------------------------------------
    @staticmethod
    def _owners_from_gql(ownership: dict[str, Any] | None) -> list[dict[str, Any]]:
        owners: list[dict[str, Any]] = []
        for entry in ((ownership or {}).get("owners") or []):
            owner = entry.get("owner") or {}
            props = owner.get("properties") or {}
            owners.append(
                {
                    "urn": owner.get("urn"),
                    "name": props.get("displayName")
                    or owner.get("username")
                    or owner.get("name")
                    or urn_name(owner.get("urn")),
                    "email": props.get("email"),
                    "type": entry.get("type") or "DATAOWNER",
                }
            )
        return owners

    @staticmethod
    def _tags_from_gql(tags: dict[str, Any] | None) -> list[str]:
        return [
            (t.get("tag") or {}).get("name")
            for t in ((tags or {}).get("tags") or [])
            if (t.get("tag") or {}).get("name")
        ]

    def _normalize_asset(self, urn: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Tolerant normaliser: works with GraphQL shapes and MCP tool payloads."""
        node = payload.get("dataset") or payload.get("entity") or payload
        props = node.get("properties") or {}
        editable = node.get("editableProperties") or {}
        platform = node.get("platform") or {}
        platform_name = (
            platform.get("name")
            if isinstance(platform, dict)
            else platform if isinstance(platform, str) else None
        )
        schema_meta = node.get("schemaMetadata") or node.get("schema") or {}
        fields = [
            {
                "path": f.get("fieldPath") or f.get("path") or f.get("name"),
                "type": f.get("nativeDataType") or f.get("type"),
                "nullable": f.get("nullable"),
                "description": f.get("description"),
            }
            for f in (schema_meta.get("fields") or [])
        ]
        domain = ((node.get("domain") or {}).get("domain") or {}).get("properties", {}).get("name")
        return {
            "urn": node.get("urn") or urn,
            "name": node.get("name") or props.get("name") or urn_name(urn),
            "entity_type": node.get("type") or urn_entity_type(urn),
            "platform": platform_name,
            "env": node.get("origin") or node.get("env"),
            "description": editable.get("description") or props.get("description") or "",
            "domain": domain,
            "tags": self._tags_from_gql(node.get("tags")) or node.get("tags") or [],
            "glossary_terms": [
                (t.get("term") or {}).get("name")
                for t in ((node.get("glossaryTerms") or {}).get("terms") or [])
            ],
            "owners": self._owners_from_gql(node.get("ownership")) or node.get("owners") or [],
            "criticality": node.get("criticality", "MEDIUM"),
            "properties": {
                p.get("key"): p.get("value") for p in (props.get("customProperties") or [])
            },
            "schema_fields": fields,
            "institutional_memory": (
                (node.get("institutionalMemory") or {}).get("elements") or []
            ),
        }

    def _normalize_lineage_node(self, result: dict[str, Any], direction: str) -> dict[str, Any]:
        entity = result.get("entity") or {}
        props = entity.get("properties") or {}
        platform = entity.get("platform") or {}
        return {
            "urn": entity.get("urn"),
            "name": entity.get("name") or props.get("name") or urn_name(entity.get("urn")),
            "entity_type": entity.get("type") or urn_entity_type(entity.get("urn")),
            "platform": platform.get("name") if isinstance(platform, dict) else platform,
            "distance": result.get("degree", 1),
            "direction": direction,
            "tags": self._tags_from_gql(entity.get("tags")),
            "owners": self._owners_from_gql(entity.get("ownership")),
            "criticality": "MEDIUM",
            "known": True,
        }

    # -- provider API -----------------------------------------------------
    @guarded
    async def health(self) -> ToolResult:
        mcp_ok = await self._ensure_mcp()
        gql_ok = False
        detail = ""
        if self.gql:
            try:
                await self.gql.health()
                gql_ok = True
            except Exception as exc:  # noqa: BLE001
                detail = str(exc)[:200]
        if not (mcp_ok or gql_ok):
            return self._fail("health", detail or "No DataHub transport is reachable")
        return self._ok(
            "health",
            {
                "connected": True,
                "mcp": mcp_ok,
                "mcp_tools": self.mcp_tools,
                "graphql": gql_ok,
                "datahub_url": self.datahub_url,
            },
            source="datahub-mcp" if mcp_ok else "datahub-graphql",
        )

    @guarded
    async def get_asset_context(self, urn: str) -> ToolResult:
        used, payload, source = await self._try_mcp("get_asset_context", {"urn": urn})
        if used and isinstance(payload, dict):
            return self._ok("get_asset_context", self._normalize_asset(urn, payload), source)
        if not self.gql:
            return self._fail("get_asset_context", "No DataHub GraphQL endpoint configured")
        data = await self.gql.execute(DATASET_QUERY, {"urn": urn})
        if not data.get("dataset"):
            return self._fail("get_asset_context", f"Asset not found in DataHub: {urn}")
        return self._ok(
            "get_asset_context",
            self._normalize_asset(urn, data),
            "datahub-graphql:dataset",
        )

    @guarded
    async def get_schema(self, urn: str) -> ToolResult:
        context = await self.get_asset_context(urn)
        if not context.success:
            return ToolResult.fail("get_schema", context.error or "unknown", source=context.source)
        return self._ok(
            "get_schema",
            {"urn": urn, "fields": context.data.get("schema_fields", [])},
            context.source,
        )

    @guarded
    async def get_lineage(self, urn: str, direction: str = "BOTH", depth: int = 3) -> ToolResult:
        used, payload, source = await self._try_mcp(
            "get_lineage", {"urn": urn, "direction": direction, "depth": depth}
        )
        if used and isinstance(payload, dict) and payload.get("nodes"):
            payload.setdefault("urn", urn)
            payload.setdefault("direction", direction)
            payload.setdefault("edges", [])
            return self._ok("get_lineage", payload, source)
        if not self.gql:
            return self._fail("get_lineage", "No DataHub GraphQL endpoint configured")
        directions = ["UPSTREAM", "DOWNSTREAM"] if direction.upper() == "BOTH" else [direction.upper()]
        nodes: dict[str, dict[str, Any]] = {}
        edges: list[dict[str, Any]] = []
        for way in directions:
            data = await self.gql.execute(
                LINEAGE_QUERY, {"urn": urn, "direction": way, "count": 100}
            )
            for result in (data.get("searchAcrossLineage") or {}).get("searchResults", []):
                node = self._normalize_lineage_node(result, way)
                if not node["urn"] or node["distance"] > depth:
                    continue
                existing = nodes.get(node["urn"])
                if existing is None or existing["distance"] > node["distance"]:
                    nodes[node["urn"]] = node
                if node["distance"] == 1:
                    edges.append(
                        {
                            "upstream": node["urn"] if way == "UPSTREAM" else urn,
                            "downstream": urn if way == "UPSTREAM" else node["urn"],
                            "via": None,
                            "type": "TRANSFORMED",
                        }
                    )
        nodes[urn] = {
            "urn": urn,
            "name": urn_name(urn),
            "entity_type": urn_entity_type(urn),
            "distance": 0,
            "direction": "SELF",
            "tags": [],
            "owners": [],
            "criticality": "MEDIUM",
            "known": True,
        }
        return self._ok(
            "get_lineage",
            {
                "urn": urn,
                "direction": direction.upper(),
                "depth": depth,
                "nodes": sorted(nodes.values(), key=lambda n: (n["distance"], n["urn"])),
                "edges": edges,
            },
            "datahub-graphql:searchAcrossLineage",
        )

    @guarded
    async def get_ownership(self, urn: str) -> ToolResult:
        context = await self.get_asset_context(urn)
        if not context.success:
            return ToolResult.fail(
                "get_ownership", context.error or "unknown", source=context.source
            )
        return self._ok(
            "get_ownership", {"urn": urn, "owners": context.data.get("owners", [])}, context.source
        )

    @guarded
    async def get_quality_context(self, urn: str) -> ToolResult:
        used, payload, source = await self._try_mcp("get_quality_context", {"urn": urn})
        if used and isinstance(payload, dict):
            assertions = payload.get("assertions") or payload.get("results") or []
            return self._ok(
                "get_quality_context",
                {"urn": urn, "assertions": assertions, "has_quality_signals": bool(assertions)},
                source,
            )
        if not self.gql:
            return self._fail("get_quality_context", "No DataHub GraphQL endpoint configured")
        data = await self.gql.execute(ASSERTIONS_QUERY, {"urn": urn})
        raw = (((data.get("dataset") or {}).get("assertions") or {}).get("assertions")) or []
        assertions = []
        for item in raw:
            info = item.get("info") or {}
            events = ((item.get("runEvents") or {}).get("runEvents") or [])
            latest = events[0] if events else {}
            result = latest.get("result") or {}
            native = {n.get("key"): n.get("value") for n in (result.get("nativeResults") or [])}
            assertions.append(
                {
                    "urn": item.get("urn"),
                    "name": info.get("description") or info.get("type"),
                    "type": info.get("type"),
                    "status": result.get("type") or latest.get("status"),
                    "asset_urn": urn,
                    "observed_at": to_iso(
                        datetime.fromtimestamp(latest["timestampMillis"] / 1000)
                        if latest.get("timestampMillis")
                        else None
                    ),
                    "native_results": native,
                }
            )
        return self._ok(
            "get_quality_context",
            {"urn": urn, "assertions": assertions, "has_quality_signals": bool(assertions)},
            "datahub-graphql:assertions",
        )

    @guarded
    async def find_changes(
        self, urn: str, since: datetime | str | None = None, until: datetime | str | None = None
    ) -> ToolResult:
        since = parse_dt(since)
        until = parse_dt(until)
        used, payload, source = await self._try_mcp(
            "find_changes",
            {"urn": urn, "startTime": to_iso(since), "endTime": to_iso(until)},
        )
        if used and isinstance(payload, dict) and payload.get("changes") is not None:
            payload.setdefault("urn", urn)
            return self._ok("find_changes", payload, source)
        if not self.gql:
            return self._fail("find_changes", "No DataHub GraphQL endpoint configured")
        transactions = await self.gql.timeline(
            urn, since, until, ["TECHNICAL_SCHEMA", "DOCUMENTATION", "OWNERSHIP", "TAG"]
        )
        # Field names follow the Timeline API guide: a ChangeEvent carries
        # changeType, category, elementId, target, description, changeDetails and
        # modificationCategory. Older names are accepted as fallbacks because the
        # payload is read from a server versioned independently of this code, and
        # a rename must degrade to a thinner record rather than to an exception.
        changes: list[dict[str, Any]] = []
        for transaction in transactions:
            timestamp = transaction.get("timestamp") or transaction.get("timestampMillis")
            moment = (
                to_iso(datetime.fromtimestamp(timestamp / 1000, tz=UTC))
                if isinstance(timestamp, (int, float))
                else timestamp
            )
            events = transaction.get("changeEvents") or transaction.get("events") or []
            for change in events:
                category = str(change.get("category") or "")
                operation = change.get("changeType") or change.get("operation")
                element = change.get("elementId") or change.get("modifier")
                details = change.get("changeDetails") or change.get("parameters") or {}
                modification = change.get("modificationCategory")
                changes.append(
                    {
                        "timestamp": moment,
                        "entity_urn": change.get("target") or urn,
                        "type": "SCHEMA_CHANGE" if category == "TECHNICAL_SCHEMA" else category,
                        "operation": operation,
                        "summary": change.get("description")
                        or f"{operation} {element}".strip(),
                        "details": {
                            # A RENAME is precisely the shape the golden scenario
                            # turns on, so it is surfaced rather than buried in
                            # the raw payload.
                            "field": element,
                            "modification_category": modification,
                            "semantic_version": transaction.get("semVer")
                            or transaction.get("semanticVersion"),
                            "sem_ver_change": change.get("semVerChange"),
                            "parameters": details,
                        },
                    }
                )
        changes.sort(key=lambda c: c.get("timestamp") or "")
        return self._ok(
            "find_changes",
            {
                "urn": urn,
                "window": {"since": to_iso(since), "until": to_iso(until)},
                "changes": changes,
            },
            "datahub-openapi:timeline",
        )

    @guarded
    async def find_related_assets(self, urn: str, limit: int = 20) -> ToolResult:
        context = await self.get_asset_context(urn)
        if not context.success:
            return ToolResult.fail(
                "find_related_assets", context.error or "unknown", source=context.source
            )
        terms = [*context.data.get("glossary_terms", []), *context.data.get("tags", [])]
        related: list[dict[str, Any]] = []
        for term in terms[:3]:
            search = await self.search_assets(str(term), limit=limit)
            if search.success:
                related.extend(
                    node for node in search.data.get("results", []) if node["urn"] != urn
                )
        unique = {node["urn"]: node for node in related}
        return self._ok(
            "find_related_assets",
            {"urn": urn, "related": list(unique.values())[:limit]},
            "datahub-graphql:search",
        )

    @guarded
    async def search_assets(self, query: str, limit: int = 10) -> ToolResult:
        used, payload, source = await self._try_mcp("search_assets", {"query": query, "limit": limit})
        if used and isinstance(payload, dict):
            results = payload.get("results") or payload.get("entities") or []
            return self._ok("search_assets", {"query": query, "results": results}, source)
        if not self.gql:
            return self._fail("search_assets", "No DataHub GraphQL endpoint configured")
        data = await self.gql.execute(SEARCH_QUERY, {"query": query, "count": limit})
        results = [
            self._normalize_lineage_node(item, "SEARCH")
            for item in (data.get("searchAcrossEntities") or {}).get("searchResults", [])
        ]
        return self._ok(
            "search_assets", {"query": query, "results": results}, "datahub-graphql:search"
        )

    # -- write-back -------------------------------------------------------
    @guarded
    async def write_incident_memory(
        self, document: dict[str, Any], affected_urns: list[str]
    ) -> ToolResult:
        if not settings.datahub_writeback_enabled:
            return self._fail("write_incident_memory", "Write-back is disabled by configuration")
        if not self.gql:
            return self._fail("write_incident_memory", "No DataHub GraphQL endpoint configured")
        target = document.get("asset_urn")
        pattern = str(document.get("pattern") or "UNKNOWN")
        tag_id = f"dataforensic-{pattern.lower().replace('_', '-')}"
        tag_urn = f"urn:li:tag:{tag_id}"
        operations: list[str] = []
        try:
            await self.gql.execute(
                CREATE_TAG,
                {
                    "id": tag_id,
                    "name": f"DataForensic: {pattern}",
                    "description": f"Incident pattern identified by DATAFORENSIC AI: {pattern}",
                },
            )
            operations.append("createTag")
        except Exception as exc:  # noqa: BLE001 - tag may already exist
            logger.info("datahub_tag_exists", extra={"tag": tag_urn, "detail": str(exc)[:120]})
        link_url = (
            f"{settings.public_app_url}/investigations/{document.get('investigation_id')}"
        )
        label = f"DATAFORENSIC investigation - {pattern} ({int(float(document.get('confidence', 0)) * 100)}%)"
        for urn in dict.fromkeys([target, *affected_urns]):
            if not urn:
                continue
            try:
                await self.gql.execute(ADD_TAGS, {"tagUrns": [tag_urn], "resourceUrn": urn})
                operations.append(f"addTags:{urn}")
            except Exception as exc:  # noqa: BLE001
                logger.warning("datahub_add_tag_failed", extra={"urn": urn, "error": str(exc)[:160]})
        # addLink is best effort. `createTag` and `addTags` are documented with
        # their exact input shapes in the DataHub tutorials; `addLink` appears in
        # the mutations index but its input fields were not confirmed against the
        # official docs, so the whole write-back must not hang on it. The tag is
        # what makes the investigation discoverable in DataHub; the link is a
        # convenience pointing back at the report.
        try:
            await self.gql.execute(
                ADD_LINK, {"linkUrl": link_url, "label": label, "resourceUrn": target}
            )
            operations.append("addLink")
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "datahub_add_link_failed", extra={"urn": target, "error": str(exc)[:160]}
            )
        if not any(op.startswith("addTags") for op in operations):
            return self._fail(
                "write_incident_memory",
                "No tag could be applied to any affected asset; nothing was recorded.",
            )
        return self._ok(
            "write_incident_memory",
            {
                # The tag URN is the durable reference: it survives even when the
                # link could not be attached, and it is what a later search finds.
                "reference": link_url,
                "resource_urn": target,
                "tag_urn": tag_urn,
                "link_attached": "addLink" in operations,
                "operations": operations,
                "document": document,
                "written_at": to_iso(utcnow()),
            },
            "datahub-graphql:mutation",
        )

    @guarded
    async def read_incident_memory(self, reference: str) -> ToolResult:
        """Verify the write-back by reading institutional memory back from DataHub."""
        if not self.gql:
            return self._fail("read_incident_memory", "No DataHub GraphQL endpoint configured")
        urn = reference.split("#")[0] if reference.startswith("urn:") else None
        if not urn:
            return self._fail(
                "read_incident_memory",
                "Reference is a link URL; provide the resource URN to verify",
            )
        data = await self.gql.execute(DATASET_QUERY, {"urn": urn})
        elements = (((data.get("dataset") or {}).get("institutionalMemory") or {}).get("elements")) or []
        return self._ok(
            "read_incident_memory",
            {"reference": reference, "elements": elements},
            "datahub-graphql:institutionalMemory",
        )

    @guarded
    async def search_incident_memory(
        self, pattern: str | None = None, asset_urn: str | None = None, limit: int = 10
    ) -> ToolResult:
        if not self.gql or not asset_urn:
            return self._ok("search_incident_memory", {"matches": []}, "datahub-graphql")
        data = await self.gql.execute(DATASET_QUERY, {"urn": asset_urn})
        elements = (((data.get("dataset") or {}).get("institutionalMemory") or {}).get("elements")) or []
        matches = [
            {
                "reference": element.get("url"),
                "document": {
                    "root_cause": element.get("description", ""),
                    "pattern": pattern,
                    "asset_urn": asset_urn,
                },
                "written_at": None,
            }
            for element in elements
            if "DATAFORENSIC" in (element.get("label") or "")
        ]
        return self._ok(
            "search_incident_memory",
            {"pattern": pattern, "asset_urn": asset_urn, "matches": matches[:limit]},
            "datahub-graphql:institutionalMemory",
        )

    async def close(self) -> None:
        if self.mcp:
            await self.mcp.close()
        if self.gql:
            await self.gql.close()
