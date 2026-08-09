"""Progressive context acquisition (DOCUMENT 05 - section 3).

The agent never scans all of DataHub: it starts from the affected asset and
expands along lineage only as far as it needs.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from app.core.errors import DataHubUnavailableError
from app.core.utils import ensure_aware, urn_name
from app.domain.enums import SourceMode
from app.services.datahub.base import DataHubProvider, ToolResult

Emitter = Callable[[str, str, dict[str, Any]], Awaitable[None]]


@dataclass(slots=True)
class InvestigationContext:
    asset_urn: str
    asset: dict[str, Any] = field(default_factory=dict)
    schema: dict[str, Any] = field(default_factory=dict)
    lineage: dict[str, Any] = field(default_factory=dict)
    owners: list[dict[str, Any]] = field(default_factory=list)
    quality: dict[str, Any] = field(default_factory=dict)
    related: list[dict[str, Any]] = field(default_factory=list)
    changes: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    incident_time: datetime | None = None
    source_mode: SourceMode = SourceMode.DEMO_FIXTURE
    tool_results: list[ToolResult] = field(default_factory=list)
    # Schemas of the target *and* of the upstream assets close enough to be
    # implicated. Without them the agent can name a field it never verified.
    schemas: dict[str, dict[str, Any]] = field(default_factory=dict)

    # -- graph helpers ----------------------------------------------------
    @property
    def nodes(self) -> list[dict[str, Any]]:
        return self.lineage.get("nodes", [])

    @property
    def upstream(self) -> list[dict[str, Any]]:
        return [n for n in self.nodes if n.get("direction") == "UPSTREAM"]

    @property
    def downstream(self) -> list[dict[str, Any]]:
        return [n for n in self.nodes if n.get("direction") == "DOWNSTREAM"]

    def node(self, urn: str) -> dict[str, Any] | None:
        return next((n for n in self.nodes if n.get("urn") == urn), None)

    def distance_to_target(self, urn: str) -> int | None:
        if urn == self.asset_urn:
            return 0
        node = self.node(urn)
        return node.get("distance") if node else None

    def on_path_to_target(self, urn: str) -> bool:
        node = self.node(urn)
        return bool(node) and node.get("direction") in {"UPSTREAM", "SELF"}

    def asset_name(self, urn: str | None) -> str:
        if not urn:
            return ""
        node = self.node(urn)
        if node:
            return str(node.get("name") or urn_name(urn))
        return urn_name(urn)

    def summary(self) -> dict[str, Any]:
        return {
            "asset_urn": self.asset_urn,
            "asset_name": self.asset.get("name"),
            "platform": self.asset.get("platform"),
            "domain": self.asset.get("domain"),
            "tags": self.asset.get("tags", []),
            "owners": [o.get("name") for o in self.owners],
            "schema_field_count": len(self.schema.get("fields", [])),
            "upstream_count": len(self.upstream),
            "downstream_count": len(self.downstream),
            "lineage_edges": len(self.lineage.get("edges", [])),
            "quality_signal_count": len(self.quality.get("assertions", [])),
            "changes_inspected": sum(len(v) for v in self.changes.values()),
            "source_mode": str(self.source_mode),
            "tools_used": sorted({t.tool for t in self.tool_results}),
        }


MAX_UPSTREAM_SCHEMAS = 5


class ContextBuilder:
    def __init__(self, provider: DataHubProvider, emit: Emitter | None = None) -> None:
        self.provider = provider
        self.emit = emit

    async def _emit(
        self,
        event: str,
        message: str,
        payload: dict[str, Any] | None = None,
        level: str = "info",
    ) -> None:
        if self.emit:
            await self.emit(event, message, payload or {}, level=level)

    async def build(
        self,
        asset_urn: str,
        incident_time: datetime | None,
        depth: int = 4,
        lookback_minutes: int = 720,
    ) -> InvestigationContext:
        context = InvestigationContext(
            asset_urn=asset_urn,
            incident_time=ensure_aware(incident_time),
            source_mode=self.provider.source_mode,
        )

        asset = await self.provider.get_asset_context(asset_urn)
        context.tool_results.append(asset)
        if not asset.success:
            raise DataHubUnavailableError(
                f"Unable to retrieve asset context for {asset_urn}",
                details={"error": asset.error, "source": asset.source},
            )
        context.asset = asset.data
        await self._emit(
            "context_loaded",
            f"Asset context loaded from {asset.source}",
            {
                "asset_urn": asset_urn,
                "asset_name": context.asset.get("name"),
                "platform": context.asset.get("platform"),
                "source": asset.source,
                "source_mode": str(asset.source_mode),
            },
        )

        schema = await self.provider.get_schema(asset_urn)
        context.tool_results.append(schema)
        context.schema = schema.unwrap({"fields": []}) or {"fields": []}
        context.schemas[asset_urn] = context.schema

        lineage = await self.provider.get_lineage(asset_urn, "BOTH", depth)
        context.tool_results.append(lineage)
        if not lineage.success:
            raise DataHubUnavailableError(
                f"Unable to trace lineage for {asset_urn}",
                details={"error": lineage.error, "source": lineage.source},
            )
        context.lineage = lineage.data
        await self._emit(
            "lineage_loaded",
            f"Lineage traced: {len(context.upstream)} upstream / {len(context.downstream)} downstream",
            {
                "upstream": len(context.upstream),
                "downstream": len(context.downstream),
                "edges": len(context.lineage.get("edges", [])),
                "source": lineage.source,
            },
        )

        ownership = await self.provider.get_ownership(asset_urn)
        context.tool_results.append(ownership)
        context.owners = (ownership.unwrap({}) or {}).get("owners", [])

        quality = await self.provider.get_quality_context(asset_urn)
        context.tool_results.append(quality)
        context.quality = quality.unwrap({"assertions": []}) or {"assertions": []}

        related = await self.provider.find_related_assets(asset_urn, limit=10)
        context.tool_results.append(related)
        context.related = (related.unwrap({}) or {}).get("related", [])

        # An asset can exist in DataHub and still carry nothing: a URN that only
        # ever received a tag has an entity row, no schema and no lineage. The
        # investigation can still run on behavioural signals, but every
        # structural conclusion - blast radius above all - will be empty, and
        # that deserves to be said out loud rather than inferred from a zero.
        if not context.schema.get("fields") and not context.nodes:
            await self._emit(
                "context_incomplete",
                (
                    f"{context.asset_name(asset_urn)} exists in DataHub but has no schema "
                    "and no lineage. Impact analysis will be empty and the trust score "
                    "will reflect it. Load the datapack, or ingest the demo graph."
                ),
                {
                    "asset_urn": asset_urn,
                    "schema_fields": 0,
                    "lineage_nodes": 0,
                },
                level="warning",
            )

        # A field-level root cause is only defensible if the schema holding that
        # field was actually read, so the nearest upstream assets are inspected
        # too rather than trusting the target's schema alone.
        nearby_upstream = [
            node["urn"]
            for node in sorted(context.upstream, key=lambda n: n.get("distance") or 99)
            if node.get("urn") and (node.get("distance") or 99) <= 2
        ][:MAX_UPSTREAM_SCHEMAS]
        for urn in nearby_upstream:
            upstream_schema = await self.provider.get_schema(urn)
            context.tool_results.append(upstream_schema)
            if upstream_schema.success:
                context.schemas[urn] = upstream_schema.data
        if nearby_upstream:
            await self._emit(
                "schemas_inspected",
                f"Schemas read for the affected asset and {len(nearby_upstream)} upstream asset(s)",
                {
                    "assets": len(context.schemas),
                    "fields": sum(
                        len(payload.get("fields", [])) for payload in context.schemas.values()
                    ),
                },
            )

        # Change history: target asset + the upstream chain (closest first).
        incident_time = ensure_aware(incident_time)
        since = incident_time - timedelta(minutes=lookback_minutes) if incident_time else None
        until = incident_time + timedelta(minutes=30) if incident_time else None
        inspect = [asset_urn] + [
            n["urn"]
            for n in sorted(context.upstream, key=lambda n: n.get("distance", 99))
            if n.get("urn")
        ]
        for urn in inspect[:15]:
            changes = await self.provider.find_changes(urn, since, until)
            context.tool_results.append(changes)
            if changes.success:
                found = changes.data.get("changes", [])
                if found:
                    context.changes[urn] = found

        await self._emit(
            "changes_inspected",
            f"Change history inspected on {len(inspect[:15])} asset(s)",
            {
                "assets_inspected": len(inspect[:15]),
                "assets_with_changes": len(context.changes),
                "window_minutes": lookback_minutes,
            },
        )
        return context
