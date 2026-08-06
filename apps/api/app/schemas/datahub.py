from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DataHubStatus(BaseModel):
    mode: str
    source_mode: str
    provider: str
    connected: bool
    datahub_url: str | None = None
    mcp_url: str | None = None
    write_back_enabled: bool = True
    detail: str = ""
    tools: list[str] = Field(default_factory=list)
    mcp: dict[str, Any] = Field(default_factory=dict)


class AssetContextOut(BaseModel):
    urn: str
    name: str
    entity_type: str
    platform: str | None = None
    env: str | None = None
    description: str | None = None
    domain: str | None = None
    tags: list[str] = Field(default_factory=list)
    glossary_terms: list[str] = Field(default_factory=list)
    owners: list[dict[str, Any]] = Field(default_factory=list)
    schema_fields: list[dict[str, Any]] = Field(default_factory=list)
    criticality: str | None = None
    source: str = ""
    source_mode: str = "DEMO_FIXTURE"
