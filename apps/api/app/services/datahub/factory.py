"""Provider selection.

DATAHUB_MODE:
  live    -> a real DataHub is mandatory; failures surface as DATAHUB_UNAVAILABLE
  fixture -> always the deterministic local graph
  auto    -> probe the live provider, otherwise fall back to the fixture and
             label every result DEMO_FIXTURE (never claim live DataHub)
"""

from __future__ import annotations

from typing import Any

from app.config import settings
from app.core.errors import DataHubUnavailableError
from app.core.logging import get_logger
from app.services.datahub.base import DataHubProvider
from app.services.datahub.fixture import FixtureDataHubProvider
from app.services.datahub.live import LiveDataHubProvider

logger = get_logger(__name__)

_provider: DataHubProvider | None = None
_status: dict[str, Any] = {"connected": False, "detail": "not initialised"}


async def build_provider() -> DataHubProvider:
    """Resolve the provider once, at startup (or lazily on first use)."""
    global _provider, _status

    mode = settings.datahub_mode
    if mode != "fixture" and (settings.datahub_mcp_url or settings.datahub_url):
        live = LiveDataHubProvider()
        health = await live.health()
        if health.success:
            _provider = live
            _status = {
                "connected": True,
                "detail": "Connected to live DataHub",
                "transport": health.source,
                "tools": live.mcp_tools,
            }
            logger.info("datahub_provider_selected", extra={"provider": "live"})
            return live
        await live.close()
        if mode == "live":
            _status = {"connected": False, "detail": health.error or "unreachable"}
            raise DataHubUnavailableError(
                "DATAHUB_MODE=live but no DataHub transport is reachable",
                details={"error": health.error},
            )
        logger.warning(
            "datahub_live_unavailable_falling_back", extra={"error": health.error}
        )
        _status = {
            "connected": False,
            "detail": f"Live DataHub unavailable ({health.error}); using deterministic fixture graph",
        }
    elif mode == "live":
        raise DataHubUnavailableError(
            "DATAHUB_MODE=live requires DATAHUB_URL and/or DATAHUB_MCP_URL"
        )
    else:
        _status = {"connected": True, "detail": "Deterministic fixture graph (no live DataHub)"}

    _provider = FixtureDataHubProvider()
    logger.info("datahub_provider_selected", extra={"provider": "fixture"})
    return _provider


async def get_provider() -> DataHubProvider:
    if _provider is None:
        return await build_provider()
    return _provider


def provider_status() -> dict[str, Any]:
    provider = _provider
    return {
        "mode": settings.datahub_mode,
        "provider": provider.name if provider else "uninitialised",
        "source_mode": str(provider.source_mode) if provider else "UNKNOWN",
        "datahub_url": settings.datahub_url,
        "mcp_url": settings.datahub_mcp_url,
        "write_back_enabled": settings.datahub_writeback_enabled,
        "tools": _status.get("tools", []),
        "connected": bool(_status.get("connected")),
        "detail": str(_status.get("detail", "")),
        "mcp": provider.mcp_status() if hasattr(provider, "mcp_status") else {
            "configured": False,
            "ready": False,
            "tools": [],
            "error": None,
            "detail": "Fixture provider: no MCP transport is involved.",
        },
    }


async def reset_provider() -> None:
    """Used by tests and by scripts/reset-demo.sh."""
    global _provider, _status
    if _provider is not None:
        await _provider.close()
    _provider = None
    _status = {"connected": False, "detail": "not initialised"}
