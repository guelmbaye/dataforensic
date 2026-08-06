#!/usr/bin/env python3
"""Run one scenario end-to-end without HTTP. Debug/demo harness.

    python -m app.cli.run_scenario revenue-collapse
"""

from __future__ import annotations

import asyncio
import json
import sys

from app.agents.investigator import InvestigationAgent
from app.core.logging import configure_logging
from app.domain.enums import InvestigationPhase, InvestigationStatus
from app.models.database import init_db, session_scope
from app.models.tables import Incident, Investigation
from app.schemas.incident import IncidentCreate
from app.services.datahub import get_provider
from app.services.incidents import IncidentService
from app.services.investigation import InvestigationService
from app.services.scenario import ScenarioRuntime, get_registry


async def main(scenario_id: str) -> int:
    configure_logging("WARNING")
    await init_db()
    scenario = get_registry().get(scenario_id)
    if scenario is None:
        print(f"unknown scenario: {scenario_id}")
        return 2

    async with session_scope() as session:
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
        incident_id, investigation_id = incident.id, investigation.id

    async with session_scope() as session:
        incident = await session.get(Incident, incident_id)
        investigation = await session.get(Investigation, investigation_id)
        provider = await get_provider()
        agent = InvestigationAgent(session, provider, incident, investigation)
        await agent.run()

    async with session_scope() as session:
        service = InvestigationService(session)
        investigation = await service.get(investigation_id)
        output = await service.build_output(investigation)
        events = await service.events_since(investigation_id, 0)

    print("=" * 78)
    print(f"SCENARIO {scenario_id}  |  provider={output['datahub_source_mode']}")
    print("=" * 78)
    for event in events:
        print(f"  {event.seq:>3} {event.event:<28} {event.message[:90]}")
    print("-" * 78)
    print(f"status            : {output['status']} / phase {output['phase']}")
    print(f"root cause        : {output['root_cause']['pattern']} "
          f"({output['root_cause']['confidence']:.0%})")
    print(f"                    {output['root_cause']['summary']}")
    print(f"score breakdown   : {json.dumps(output['root_cause']['score_breakdown'])}")
    print(f"evidence          : {len(output['evidence'])}")
    for item in output["evidence"]:
        print(f"    [{item['relevance']:<6}] {item['type']:<20} {item['observation'][:80]}")
    print(f"hypotheses        : {len(output['hypotheses'])}")
    for item in output["hypotheses"]:
        flag = "*" if item["is_primary"] else " "
        print(f"  {flag} {item['pattern']:<30} {item['confidence']:>6.0%}  {item['status']}")
    blast = output["blast_radius"]
    if blast:
        print(f"blast radius      : {blast['total_affected_assets']} assets / "
              f"{blast['consumers']} consumers / {blast['owner_count']} owners / "
              f"risk {blast['risk_level']} ({blast['risk_score']})")
        print(f"                    counts={json.dumps(blast['counts'])}")
    if output["remediation"]:
        print(f"remediation       : {output['remediation']['status']} "
              f"risk={output['remediation']['risk_level']} "
              f"steps={len(output['remediation']['steps'])}")
    if output["verification"]:
        print(f"verification      : {output['verification']['status']} "
              f"({output['verification']['summary']})")
        for check in output["verification"]["checks"]:
            print(f"    {check['status']:<5} {check['name']:<32} "
                  f"expected={check['expected']} actual={check['actual']}")
    if output["memory"]:
        print(f"memory            : {output['memory']['write_back_status']} -> "
              f"{output['memory']['datahub_reference']}")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "revenue-collapse")))
