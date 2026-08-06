"""Regenerate examples/*.json from an actual investigation run."""
import asyncio, json, os, pathlib, sys

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:////tmp/examples.db")
os.environ.setdefault("DATAHUB_MODE", "fixture")
os.environ.setdefault("LOG_LEVEL", "CRITICAL")
os.environ.setdefault("DATAHUB_MEMORY_STORE_PATH", "/tmp/examples-memory.json")

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "apps" / "api"))
from app.agents.investigator import InvestigationAgent
from app.domain.enums import InvestigationPhase, InvestigationStatus
from app.models.database import init_db, session_scope
from app.models.tables import Incident, Investigation
from app.schemas.incident import IncidentCreate
from app.services.datahub import get_provider
from app.services.incidents import IncidentService
from app.services.investigation import InvestigationService
from app.services.scenario import ScenarioRuntime, get_registry

ROOT = pathlib.Path(__file__).resolve().parents[1]

async def main():
    await init_db()
    scenario = get_registry().get("revenue-collapse")
    async with session_scope() as s:
        await ScenarioRuntime(s).reset("revenue-collapse")
        incident = await IncidentService(s).create(IncidentCreate.model_validate(scenario.incident))
        inv = Investigation(incident_id=incident.id, status=str(InvestigationStatus.RUNNING),
                            phase=str(InvestigationPhase.CREATED))
        s.add(inv); await s.flush()
        provider = await get_provider()
        await InvestigationAgent(s, provider, incident, inv).run()
        service = InvestigationService(s)
        out = await service.build_output(inv)
        events = await service.events_since(inv.id, 0)

    def dump(name, payload):
        path = ROOT / "examples" / name
        path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
        print("wrote", path.name)

    dump("investigation.json", {k: v for k, v in out.items() if not k.startswith("_")})
    dump("evidence.json", {"investigation_id": out["id"], "evidence": out["evidence"]})
    dump("hypotheses.json", {"investigation_id": out["id"], "hypotheses": out["hypotheses"]})
    dump("blast-radius.json", out["blast_radius"])
    dump("remediation.json", out["remediation"])
    dump("verification.json", out["verification"])
    dump("memory.json", out["memory"])
    dump("trust-score.json", out["trust"])
    dump("learning.json", out["learning"])
    dump("investigation-timeline.json", {
        "investigation_id": out["id"],
        "events": [
            {"seq": e.seq, "event": e.event, "level": e.level, "message": e.message,
             "created_at": e.created_at}
            for e in events
        ],
    })

async def with_patterns():
    await main()
    # A second identical incident, so the sample outputs show the loop closing:
    # pattern recognised, verified plan replayed, trust score higher.
    from app.services.patterns import PatternLibrary

    async with session_scope() as s:
        rows = await PatternLibrary(s).all()
        payload = [PatternLibrary.to_public(row).model_dump(mode="json") for row in rows]
    path = ROOT / "examples" / "knowledge-patterns.json"
    path.write_text(json.dumps({"items": payload, "total": len(payload)}, indent=2, default=str) + "\n", encoding="utf-8")
    print("wrote knowledge-patterns.json")


asyncio.run(with_patterns())
