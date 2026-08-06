"""Shared helpers for the agent and end-to-end tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.agents.investigator import InvestigationAgent
from app.domain.enums import InvestigationPhase, InvestigationStatus
from app.models.tables import Incident, Investigation
from app.schemas.incident import IncidentCreate
from app.services.datahub import get_provider
from app.services.incidents import IncidentService
from app.services.investigation import InvestigationService
from app.services.scenario import ScenarioRuntime, get_registry

REPO_ROOT = Path(__file__).resolve().parents[3]


def expected_truth(scenario_id: str) -> dict[str, Any]:
    """expected.json is the test truth. It is never given to the agent."""
    return json.loads(
        (REPO_ROOT / "scenarios" / scenario_id / "expected.json").read_text(encoding="utf-8")
    )


async def run_scenario(session, scenario_id: str) -> dict[str, Any]:
    """Run one scenario end to end and return the projected investigation."""
    scenario = get_registry().get(scenario_id)
    assert scenario is not None, f"unknown scenario {scenario_id}"

    await ScenarioRuntime(session).reset(scenario_id)
    incident = await IncidentService(session).create(
        IncidentCreate.model_validate(scenario.incident)
    )
    investigation = Investigation(
        incident_id=incident.id,
        status=str(InvestigationStatus.RUNNING),
        phase=str(InvestigationPhase.CREATED),
    )
    session.add(investigation)
    await session.flush()

    provider = await get_provider()
    agent = InvestigationAgent(session, provider, incident, investigation)
    await agent.run()

    service = InvestigationService(session)
    output = await service.build_output(investigation)
    events = await service.events_since(investigation.id, 0)
    output["_events"] = [
        {"seq": e.seq, "event": e.event, "message": e.message, "payload": e.payload} for e in events
    ]
    output["_incident"] = await session.get(Incident, incident.id)
    return output


def event_names(output: dict[str, Any]) -> list[str]:
    return [event["event"] for event in output["_events"]]
