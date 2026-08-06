"""Typed agent tool surface (DOCUMENT 03 - section 6, DOCUMENT 04 - section 17).

Every tool call is logged (tool_calls table) and streamed to the UI: there are
no hidden actions. The agent can only reach DataHub through this surface - no
arbitrary infrastructure operation, no shell, no free-form write.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.tables import ToolCallLog
from app.services.datahub.base import DataHubProvider, ToolResult

logger = get_logger(__name__)

Emitter = Callable[[str, str, dict[str, Any]], Awaitable[None]]

TOOL_CATALOG: list[dict[str, Any]] = [
    # --- DataHub context tools -------------------------------------------
    {
        "name": "get_asset_context",
        "category": "datahub",
        "description": "Read the metadata of a DataHub asset (platform, domain, tags, terms, owners).",
        "input_schema": {"type": "object", "properties": {"urn": {"type": "string"}}, "required": ["urn"]},
        "side_effects": "READ",
    },
    {
        "name": "get_schema",
        "category": "datahub",
        "description": "Read the schema fields of a DataHub dataset.",
        "input_schema": {"type": "object", "properties": {"urn": {"type": "string"}}, "required": ["urn"]},
        "side_effects": "READ",
    },
    {
        "name": "get_lineage",
        "category": "datahub",
        "description": "Traverse upstream and/or downstream lineage from an asset.",
        "input_schema": {
            "type": "object",
            "properties": {
                "urn": {"type": "string"},
                "direction": {"type": "string", "enum": ["UPSTREAM", "DOWNSTREAM", "BOTH"]},
                "depth": {"type": "integer", "minimum": 1, "maximum": 6},
            },
            "required": ["urn"],
        },
        "side_effects": "READ",
    },
    {
        "name": "get_ownership",
        "category": "datahub",
        "description": "Read the owners of an asset.",
        "input_schema": {"type": "object", "properties": {"urn": {"type": "string"}}, "required": ["urn"]},
        "side_effects": "READ",
    },
    {
        "name": "get_quality_context",
        "category": "datahub",
        "description": "Read available data quality signals / assertions for an asset.",
        "input_schema": {"type": "object", "properties": {"urn": {"type": "string"}}, "required": ["urn"]},
        "side_effects": "READ",
    },
    {
        "name": "find_changes",
        "category": "datahub",
        "description": "Read the change history (schema, documentation, ownership) of an asset in a time window.",
        "input_schema": {
            "type": "object",
            "properties": {
                "urn": {"type": "string"},
                "since": {"type": "string", "format": "date-time"},
                "until": {"type": "string", "format": "date-time"},
            },
            "required": ["urn"],
        },
        "side_effects": "READ",
    },
    {
        "name": "find_related_assets",
        "category": "datahub",
        "description": "Find assets related by domain, tags or glossary terms.",
        "input_schema": {
            "type": "object",
            "properties": {"urn": {"type": "string"}, "limit": {"type": "integer"}},
            "required": ["urn"],
        },
        "side_effects": "READ",
    },
    {
        "name": "search_assets",
        "category": "datahub",
        "description": "Search the DataHub context graph.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}},
            "required": ["query"],
        },
        "side_effects": "READ",
    },
    # --- Investigation tools ---------------------------------------------
    {
        "name": "create_evidence",
        "category": "investigation",
        "description": "Record an observable fact linked to its source.",
        "input_schema": {"type": "object", "properties": {"type": {"type": "string"}}},
        "side_effects": "LOW_RISK_WRITE",
    },
    {
        "name": "create_hypothesis",
        "category": "investigation",
        "description": "Create a candidate explanation with supporting and contradicting evidence.",
        "input_schema": {"type": "object", "properties": {"pattern": {"type": "string"}}},
        "side_effects": "LOW_RISK_WRITE",
    },
    {
        "name": "score_hypothesis",
        "category": "investigation",
        "description": "Score a hypothesis with the explainable confidence formula.",
        "input_schema": {"type": "object", "properties": {"hypothesis_id": {"type": "string"}}},
        "side_effects": "NONE",
    },
    {
        "name": "calculate_blast_radius",
        "category": "investigation",
        "description": "Compute affected assets, consumers and owners from the retrieved lineage.",
        "input_schema": {"type": "object", "properties": {"origin_urn": {"type": "string"}}},
        "side_effects": "NONE",
    },
    # --- Resolution tools -------------------------------------------------
    {
        "name": "create_remediation_plan",
        "category": "resolution",
        "description": "Produce a stepwise remediation plan with risk levels and rollback.",
        "input_schema": {"type": "object", "properties": {"pattern": {"type": "string"}}},
        "side_effects": "LOW_RISK_WRITE",
    },
    {
        "name": "execute_simulated_remediation",
        "category": "resolution",
        "description": "Execute the plan inside the controlled scenario environment only.",
        "input_schema": {"type": "object", "properties": {"action_id": {"type": "string"}}},
        "side_effects": "SIMULATED_WRITE",
    },
    {
        "name": "verify_resolution",
        "category": "resolution",
        "description": "Re-read metric, quality and downstream state to verify the remediation.",
        "input_schema": {"type": "object", "properties": {"investigation_id": {"type": "string"}}},
        "side_effects": "READ",
    },
    # --- Memory tools ------------------------------------------------------
    {
        "name": "find_previous_incidents",
        "category": "memory",
        "description": "Look for a previous investigation with a similar pattern or asset.",
        "input_schema": {
            "type": "object",
            "properties": {"asset_urn": {"type": "string"}, "pattern": {"type": "string"}},
        },
        "side_effects": "READ",
    },
    {
        "name": "write_incident_memory",
        "category": "memory",
        "description": "Write the validated investigation summary back into DataHub.",
        "input_schema": {"type": "object", "properties": {"investigation_id": {"type": "string"}}},
        "side_effects": "LOW_RISK_WRITE",
    },
]

TOOL_NAMES = [tool["name"] for tool in TOOL_CATALOG]


class AgentToolbox:
    """DataHub-facing tools with logging, event streaming and explicit failures.

    Exposes the same signatures as DataHubProvider so it can be handed to the
    ContextBuilder directly.
    """

    def __init__(
        self,
        session: AsyncSession,
        provider: DataHubProvider,
        investigation_id: str,
        emit: Emitter | None = None,
    ) -> None:
        self.session = session
        self.provider = provider
        self.investigation_id = investigation_id
        self.emit = emit
        self.calls: list[ToolResult] = []

    @property
    def source_mode(self):  # noqa: ANN201 - mirrors DataHubProvider
        return self.provider.source_mode

    async def _log(self, result: ToolResult, arguments: dict[str, Any]) -> None:
        self.calls.append(result)
        self.session.add(
            ToolCallLog(
                investigation_id=self.investigation_id,
                tool=result.tool,
                arguments=arguments,
                success=result.success,
                source=result.source,
                source_mode=str(result.source_mode),
                latency_ms=result.latency_ms,
                error=result.error,
                result_summary=result.summary(),
            )
        )
        await self.session.flush()
        if self.emit and not result.success:
            await self.emit(
                "tool_failed",
                f"Tool {result.tool} failed: {result.error}",
                {"tool": result.tool, "error": result.error, "arguments": arguments},
            )

    async def _call(self, coro, arguments: dict[str, Any]) -> ToolResult:
        import time

        start = time.perf_counter()
        try:
            result = await coro
        except Exception as exc:  # noqa: BLE001 - never a silent failure
            result = ToolResult.fail(
                arguments.get("_tool", "unknown"),
                f"{exc.__class__.__name__}: {exc}",
                source_mode=self.provider.source_mode,
            )
        result.latency_ms = result.latency_ms or int((time.perf_counter() - start) * 1000)
        await self._log(result, {k: v for k, v in arguments.items() if k != "_tool"})
        return result

    # -- DataHubProvider-compatible surface --------------------------------
    async def get_asset_context(self, urn: str) -> ToolResult:
        return await self._call(
            self.provider.get_asset_context(urn), {"_tool": "get_asset_context", "urn": urn}
        )

    async def get_schema(self, urn: str) -> ToolResult:
        return await self._call(self.provider.get_schema(urn), {"_tool": "get_schema", "urn": urn})

    async def get_lineage(self, urn: str, direction: str = "BOTH", depth: int = 3) -> ToolResult:
        return await self._call(
            self.provider.get_lineage(urn, direction, depth),
            {"_tool": "get_lineage", "urn": urn, "direction": direction, "depth": depth},
        )

    async def get_ownership(self, urn: str) -> ToolResult:
        return await self._call(
            self.provider.get_ownership(urn), {"_tool": "get_ownership", "urn": urn}
        )

    async def get_quality_context(self, urn: str) -> ToolResult:
        return await self._call(
            self.provider.get_quality_context(urn), {"_tool": "get_quality_context", "urn": urn}
        )

    async def find_changes(
        self, urn: str, since: datetime | str | None = None, until: datetime | str | None = None
    ) -> ToolResult:
        return await self._call(
            self.provider.find_changes(urn, since, until),
            {"_tool": "find_changes", "urn": urn, "since": str(since), "until": str(until)},
        )

    async def find_related_assets(self, urn: str, limit: int = 20) -> ToolResult:
        return await self._call(
            self.provider.find_related_assets(urn, limit),
            {"_tool": "find_related_assets", "urn": urn, "limit": limit},
        )

    async def search_assets(self, query: str, limit: int = 10) -> ToolResult:
        return await self._call(
            self.provider.search_assets(query, limit),
            {"_tool": "search_assets", "query": query, "limit": limit},
        )

    async def write_incident_memory(
        self, document: dict[str, Any], affected_urns: list[str]
    ) -> ToolResult:
        return await self._call(
            self.provider.write_incident_memory(document, affected_urns),
            {
                "_tool": "write_incident_memory",
                "incident_id": document.get("incident_id"),
                "affected_count": len(affected_urns),
            },
        )

    async def read_incident_memory(self, reference: str) -> ToolResult:
        return await self._call(
            self.provider.read_incident_memory(reference),
            {"_tool": "read_incident_memory", "reference": reference},
        )

    async def search_incident_memory(
        self, pattern: str | None = None, asset_urn: str | None = None, limit: int = 10
    ) -> ToolResult:
        return await self._call(
            self.provider.search_incident_memory(pattern, asset_urn, limit),
            {"_tool": "search_incident_memory", "pattern": pattern, "asset_urn": asset_urn},
        )
