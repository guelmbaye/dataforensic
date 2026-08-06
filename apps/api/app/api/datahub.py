from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import datahub_provider
from app.core.errors import DataHubUnavailableError, NotFoundError
from app.schemas.datahub import AssetContextOut, DataHubStatus
from app.services.datahub import provider_status
from app.services.datahub.base import DataHubProvider

router = APIRouter(prefix="/datahub", tags=["datahub"])


@router.get("/status", response_model=DataHubStatus)
async def status(provider: DataHubProvider = Depends(datahub_provider)) -> DataHubStatus:
    health = await provider.health()
    base = provider_status()
    return DataHubStatus(
        mode=base["mode"],
        source_mode=str(provider.source_mode),
        provider=provider.name,
        connected=bool(health.success),
        datahub_url=base["datahub_url"],
        mcp_url=base["mcp_url"],
        write_back_enabled=base["write_back_enabled"],
        detail=base["detail"] if health.success else (health.error or ""),
        tools=base.get("tools", []),
        mcp=base.get("mcp", {}),
    )


@router.get("/assets/{urn:path}/context", response_model=AssetContextOut)
async def asset_context(
    urn: str, provider: DataHubProvider = Depends(datahub_provider)
) -> AssetContextOut:
    result = await provider.get_asset_context(urn)
    if not result.success:
        if "not found" in (result.error or "").lower():
            raise NotFoundError(result.error or f"Asset {urn} not found")
        raise DataHubUnavailableError(result.error or "DataHub context unavailable")
    return AssetContextOut(
        **{
            **result.data,
            "source": result.source,
            "source_mode": str(result.source_mode),
        }
    )


@router.get("/lineage")
async def lineage(
    urn: str = Query(...),
    direction: str = Query(default="BOTH"),
    depth: int = Query(default=3, ge=1, le=6),
    provider: DataHubProvider = Depends(datahub_provider),
) -> dict:
    result = await provider.get_lineage(urn, direction, depth)
    if not result.success:
        raise DataHubUnavailableError(result.error or "Lineage unavailable")
    return {**result.data, "source": result.source, "source_mode": str(result.source_mode)}


@router.get("/search")
async def search(
    query: str = Query(...),
    limit: int = Query(default=10, ge=1, le=50),
    provider: DataHubProvider = Depends(datahub_provider),
) -> dict:
    result = await provider.search_assets(query, limit)
    if not result.success:
        raise DataHubUnavailableError(result.error or "Search unavailable")
    return {**result.data, "source": result.source, "source_mode": str(result.source_mode)}
