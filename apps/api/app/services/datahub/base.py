"""DataHub provider contract.

Every call returns a ToolResult carrying explicit provenance. No tool is ever
allowed to silently return [] / null / {} on failure (DOCUMENT 09 - section 5).
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.domain.enums import SourceMode, SourceSystem


@dataclass(slots=True)
class ToolResult:
    tool: str
    success: bool
    data: Any = None
    source: str = ""
    source_mode: SourceMode = SourceMode.DEMO_FIXTURE
    source_system: SourceSystem = SourceSystem.DATAHUB
    error: str | None = None
    latency_ms: int = 0
    meta: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def ok(cls, tool: str, data: Any, **kw: Any) -> ToolResult:
        return cls(tool=tool, success=True, data=data, **kw)

    @classmethod
    def fail(cls, tool: str, error: str, **kw: Any) -> ToolResult:
        return cls(tool=tool, success=False, data=None, error=error, **kw)

    def unwrap(self, default: Any = None) -> Any:
        return self.data if self.success else default

    def summary(self) -> dict[str, Any]:
        data = self.data
        if isinstance(data, list):
            shape: Any = {"kind": "list", "size": len(data)}
        elif isinstance(data, dict):
            shape = {"kind": "dict", "keys": sorted(data.keys())[:12]}
        else:
            shape = {"kind": type(data).__name__}
        return {"success": self.success, "shape": shape, "error": self.error}

    def to_public(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "success": self.success,
            "source": self.source,
            "source_mode": str(self.source_mode),
            "source_system": str(self.source_system),
            "error": self.error,
            "latency_ms": self.latency_ms,
        }


async def timed(tool: str, fn: Callable[[], Awaitable[ToolResult]]) -> ToolResult:
    start = time.perf_counter()
    try:
        result = await fn()
    except Exception as exc:  # noqa: BLE001 - surfaced as an explicit failure
        return ToolResult.fail(tool, f"{exc.__class__.__name__}: {exc}")
    result.latency_ms = int((time.perf_counter() - start) * 1000)
    return result


class DataHubProvider(ABC):
    """Semantic tool surface exposed to the agent (DOCUMENT 03 - section 6)."""

    name: str = "abstract"
    source_mode: SourceMode = SourceMode.DEMO_FIXTURE

    @abstractmethod
    async def health(self) -> ToolResult: ...

    @abstractmethod
    async def get_asset_context(self, urn: str) -> ToolResult: ...

    @abstractmethod
    async def get_schema(self, urn: str) -> ToolResult: ...

    @abstractmethod
    async def get_lineage(
        self, urn: str, direction: str = "BOTH", depth: int = 3
    ) -> ToolResult: ...

    @abstractmethod
    async def get_ownership(self, urn: str) -> ToolResult: ...

    @abstractmethod
    async def get_quality_context(self, urn: str) -> ToolResult: ...

    @abstractmethod
    async def find_changes(
        self, urn: str, since: datetime | str | None = None, until: datetime | str | None = None
    ) -> ToolResult: ...

    @abstractmethod
    async def find_related_assets(self, urn: str, limit: int = 20) -> ToolResult: ...

    @abstractmethod
    async def search_assets(self, query: str, limit: int = 10) -> ToolResult: ...

    @abstractmethod
    async def write_incident_memory(
        self, document: dict[str, Any], affected_urns: list[str]
    ) -> ToolResult: ...

    @abstractmethod
    async def read_incident_memory(self, reference: str) -> ToolResult: ...

    @abstractmethod
    async def search_incident_memory(
        self,
        pattern: str | None = None,
        asset_urn: str | None = None,
        limit: int = 10,
    ) -> ToolResult: ...

    async def close(self) -> None:  # pragma: no cover - optional
        return None
