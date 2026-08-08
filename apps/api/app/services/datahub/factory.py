"""Provider selection.

DATAHUB_MODE:
  live    -> a real DataHub is mandatory; failures surface as DATAHUB_UNAVAILABLE
  fixture -> always the deterministic local graph
  auto    -> probe the live provider, otherwise fall back to the fixture and
             label every result DEMO_FIXTURE (never claim live DataHub)
"""

from __future__ import annotations

from time import monotonic
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

# A failed startup must not be a permanent verdict. DataHub is a heavy stack: it
# routinely comes up after the API, and it can be restarted underneath a running
# deployment. Without a retry the application stays broken until someone notices
# and restarts it - which, over a two-week judging window, is exactly what would
# happen.
_RETRY_AFTER_SECONDS = 15.0
_last_attempt: float = 0.0


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
    global _last_attempt
    if _provider is not None:
        return _provider

    # Rate-limited: the UI polls status every 20s, and each attempt against an
    # unreachable host costs a full connection timeout.
    now = monotonic()
    if now - _last_attempt < _RETRY_AFTER_SECONDS and _status.get("detail") != "not initialised":
        raise DataHubUnavailableError(
            str(_status.get("detail") or "DataHub is not reachable"),
            details={"retry_after_seconds": round(_RETRY_AFTER_SECONDS - (now - _last_attempt), 1)},
        )
    _last_attempt = now
    return await build_provider()


async def probe_status() -> dict[str, Any]:
    """Current truth, not the startup snapshot.

    `/health` and the context badge are read to answer "is it working *now*",
    so they retry the connection instead of reporting whatever happened when
    the process started.
    """
    try:
        await get_provider()
    except Exception as exc:  # noqa: BLE001 - reporting, never raising
        logger.info("datahub_probe_failed", extra={"error": str(exc)[:200]})
    return provider_status()


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
        # No provider means not connected, whatever the last snapshot said.
        # The cached status outlives the provider it described, and reporting a
        # stale `true` is the same failure as reporting a stale `false` - it just
        # errs in the more dangerous direction.
        "connected": bool(_status.get("connected")) and provider is not None,
        "detail": str(_status.get("detail", "")),
        "mcp": _mcp_status(provider),
    }


def _mcp_status(provider: DataHubProvider | None) -> dict[str, Any]:
    if provider is None:
        return {
            "configured": bool(settings.datahub_mcp_url),
            "ready": False,
            "tools": [],
            "error": str(_status.get("detail") or "not initialised"),
            "detail": (
                "No DataHub provider is initialised: the last attempt to reach "
                "DataHub failed. The next request retries."
            ),
        }
    if hasattr(provider, "mcp_status"):
        return provider.mcp_status()
    return {
        "configured": False,
        "ready": False,
        "tools": [],
        "error": None,
        "detail": "Fixture provider: no MCP transport is involved.",
    }


async def reset_provider() -> None:
    """Used by tests and by scripts/reset-demo.sh."""
    global _provider, _status, _last_attempt
    _last_attempt = 0.0
    if _provider is not None:
        await _provider.close()
    _provider = None
    _status = {"connected": False, "detail": "not initialised"}
