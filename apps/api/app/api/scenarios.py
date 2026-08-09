from __future__ import annotations

import inspect

from fastapi import APIRouter, Depends
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.tools import TOOL_CATALOG
from app.api.deps import db_session
from app.core.errors import NotFoundError
from app.models.tables import (
    Action,
    Evidence,
    Hypothesis,
    IdempotencyRecord,
    Incident,
    Investigation,
    InvestigationEvent,
    KnowledgePattern,
    MemoryReference,
    ToolCallLog,
    Verification,
)
from app.services.datahub import get_provider
from app.services.scenario import ScenarioRuntime, get_registry

router = APIRouter(tags=["scenarios"])


@router.get("/scenarios")
async def list_scenarios(session: AsyncSession = Depends(db_session)) -> dict:
    runtime = ScenarioRuntime(session)
    items = []
    for scenario in get_registry().all():
        items.append(
            {
                "id": scenario.id,
                "title": scenario.title,
                "target_asset_urn": scenario.target_asset_urn,
                "corruption_entry_urn": scenario.corruption_entry_urn,
                "incident_time": scenario.raw.get("incident_time"),
                "state": await runtime.get_state(scenario),
                "incident_template": scenario.incident,
                "timeline": scenario.timeline,
            }
        )
    return {"items": items, "total": len(items)}


@router.post("/scenarios/{scenario_id}/reset")
async def reset_scenario(scenario_id: str, session: AsyncSession = Depends(db_session)) -> dict:
    scenario = get_registry().get(scenario_id)
    if scenario is None:
        raise NotFoundError(f"Scenario {scenario_id} not found")
    runtime = ScenarioRuntime(session)
    reset = await runtime.reset(scenario_id)
    return {"reset": reset, "state": await runtime.get_state(scenario)}


@router.get("/agent/tools")
async def agent_tools() -> dict:
    """The exact typed tool surface exposed to the agent."""
    return {"tools": TOOL_CATALOG, "total": len(TOOL_CATALOG)}


@router.post("/demo/reset")
async def reset_demo(
    purge_incidents: bool = True,
    session: AsyncSession = Depends(db_session),
) -> dict:
    """Put the demo environment back to its initial state.

    Resets every scenario world state, clears the local incident memory, and
    (by default) removes the application incidents so a rehearsal starts clean.
    Live DataHub write-backs are never deleted from here: removing metadata from
    a real instance is not something a demo script should do silently.
    """
    runtime = ScenarioRuntime(session)
    scenarios = await runtime.reset()

    purged = 0
    if purge_incidents:
        for table in (
            InvestigationEvent, ToolCallLog, Evidence, Hypothesis, Action,
            Verification, MemoryReference, IdempotencyRecord, Investigation, Incident,
            KnowledgePattern,
        ):
            result = await session.execute(delete(table))
            purged += result.rowcount or 0

    # Resetting the application's own state must not depend on DataHub being
    # reachable. It did: an unreachable catalog raised here, the transaction
    # rolled back, and the reset silently did nothing — exactly when someone is
    # trying to get a broken environment back to a known state.
    memory_cleared = False
    source_mode = "UNKNOWN"
    datahub_error: str | None = None
    try:
        provider = await get_provider()
        source_mode = str(provider.source_mode)
        reset_memory = getattr(provider, "reset_memory", None)
        if callable(reset_memory):
            outcome = reset_memory()
            if inspect.isawaitable(outcome):
                await outcome
            memory_cleared = True
    except Exception as exc:  # noqa: BLE001 - reported, never fatal
        datahub_error = str(exc)[:300]

    return {
        "scenarios_reset": scenarios,
        "rows_purged": purged,
        "incident_memory_cleared": memory_cleared,
        "datahub_source_mode": source_mode,
        "datahub_error": datahub_error,
    }
