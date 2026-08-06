"""Controlled demo scenario runtime.

The scenario runtime owns the *behavioural* signals of the demo world (metric
readings, quality readings, transformation mapping status) and the simulated
remediation. Structural context (schema, lineage, ownership, governance) always
comes from DataHub.

Everything produced here is tagged SourceSystem.SCENARIO_RUNTIME so the UI can
show exactly which system produced which evidence. Nothing here ever touches a
production system: `apply_remediation` mutates a scenario state row only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.logging import get_logger
from app.core.utils import parse_dt, utcnow
from app.domain.enums import VerificationStatus
from app.domain.resolution import CheckResult
from app.models.tables import ScenarioState

logger = get_logger(__name__)

def _fmt(value: float) -> str:
    """Readable formatting for both large counters and small ratios."""
    if abs(value) >= 1000:
        return f"{value:,.0f}"
    if abs(value) >= 10:
        return f"{value:,.2f}"
    return f"{value:.4g}"


STATE_BROKEN = "BROKEN"
STATE_REMEDIATED = "REMEDIATED"


@dataclass(slots=True)
class ScenarioDefinition:
    id: str
    path: Path
    raw: dict[str, Any]
    incident: dict[str, Any]
    expected: dict[str, Any]

    @property
    def title(self) -> str:
        return self.raw.get("title", self.id)

    @property
    def target_asset_urn(self) -> str | None:
        return self.raw.get("target_asset_urn")

    @property
    def corruption_entry_urn(self) -> str | None:
        return self.raw.get("corruption_entry_urn") or self.target_asset_urn

    @property
    def incident_time(self) -> datetime | None:
        return parse_dt(self.raw.get("incident_time"))

    @property
    def initial_state(self) -> str:
        return self.raw.get("initial_state", STATE_BROKEN)

    @property
    def timeline(self) -> list[dict[str, Any]]:
        return self.raw.get("timeline", [])

    @property
    def remediation_template(self) -> dict[str, Any]:
        return self.raw.get("remediation", {})

    @property
    def verification_checks(self) -> list[dict[str, Any]]:
        return self.raw.get("verification_checks", [])

    def state_view(self, state: str) -> dict[str, Any]:
        return self.raw.get("states", {}).get(state, {})

    def effect_for(self, step_id: str) -> str | None:
        return self.raw.get("remediation_effects", {}).get(step_id)


class ScenarioRegistry:
    """Loads scenarios/<id>/{scenario,incident,expected}.json."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or settings.scenarios_dir
        self._items: dict[str, ScenarioDefinition] = {}
        self.reload()

    def reload(self) -> None:
        self._items = {}
        if not self.root.exists():
            logger.warning("scenarios_dir_missing", extra={"path": str(self.root)})
            return
        for directory in sorted(p for p in self.root.iterdir() if p.is_dir()):
            scenario_file = directory / "scenario.json"
            if not scenario_file.exists():
                continue
            try:
                raw = json.loads(scenario_file.read_text(encoding="utf-8"))
                incident = self._maybe(directory / "incident.json")
                expected = self._maybe(directory / "expected.json")
            except json.JSONDecodeError as exc:  # pragma: no cover - config error
                logger.error("scenario_invalid_json", extra={"path": str(scenario_file), "error": str(exc)})
                continue
            scenario_id = raw.get("id", directory.name)
            self._items[scenario_id] = ScenarioDefinition(
                id=scenario_id, path=directory, raw=raw, incident=incident, expected=expected
            )

    @staticmethod
    def _maybe(path: Path) -> dict[str, Any]:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return {}

    def all(self) -> list[ScenarioDefinition]:
        return list(self._items.values())

    def get(self, scenario_id: str | None) -> ScenarioDefinition | None:
        if not scenario_id:
            return None
        return self._items.get(scenario_id)

    def for_asset(self, asset_urn: str) -> ScenarioDefinition | None:
        for scenario in self._items.values():
            if scenario.target_asset_urn == asset_urn:
                return scenario
        return None


@lru_cache
def get_registry() -> ScenarioRegistry:
    return ScenarioRegistry()


class ScenarioRuntime:
    """Reads and mutates the scenario world state (DB backed, resettable)."""

    def __init__(self, session: AsyncSession, registry: ScenarioRegistry | None = None) -> None:
        self.session = session
        self.registry = registry or get_registry()

    async def _row(self, scenario: ScenarioDefinition) -> ScenarioState:
        row = await self.session.get(ScenarioState, scenario.id)
        if row is None:
            row = ScenarioState(
                scenario_id=scenario.id, state=scenario.initial_state, applied_effects=[]
            )
            self.session.add(row)
            await self.session.flush()
        return row

    async def get_state(self, scenario: ScenarioDefinition) -> str:
        row = await self._row(scenario)
        return row.state

    async def reset(self, scenario_id: str | None = None) -> list[str]:
        stmt = select(ScenarioState)
        if scenario_id:
            stmt = stmt.where(ScenarioState.scenario_id == scenario_id)
        rows = (await self.session.execute(stmt)).scalars().all()
        reset_ids = []
        for row in rows:
            definition = self.registry.get(row.scenario_id)
            row.state = definition.initial_state if definition else STATE_BROKEN
            row.applied_effects = []
            row.updated_at = utcnow()
            reset_ids.append(row.scenario_id)
        return reset_ids

    # -- readings ---------------------------------------------------------
    async def metrics(
        self, scenario: ScenarioDefinition, asset_urn: str | None = None
    ) -> list[dict[str, Any]]:
        view = scenario.state_view(await self.get_state(scenario))
        items = view.get("metrics", [])
        return [m for m in items if not asset_urn or m.get("asset_urn") == asset_urn]

    async def quality(
        self, scenario: ScenarioDefinition, asset_urn: str | None = None
    ) -> list[dict[str, Any]]:
        view = scenario.state_view(await self.get_state(scenario))
        items = view.get("quality", [])
        return [q for q in items if not asset_urn or q.get("asset_urn") == asset_urn]

    async def mappings(self, scenario: ScenarioDefinition) -> list[dict[str, Any]]:
        view = scenario.state_view(await self.get_state(scenario))
        return view.get("mappings", [])

    async def pipeline_runs(
        self, scenario: ScenarioDefinition, asset_urn: str | None = None
    ) -> list[dict[str, Any]]:
        view = scenario.state_view(await self.get_state(scenario))
        items = view.get("pipeline_runs", [])
        return [r for r in items if not asset_urn or r.get("asset_urn") == asset_urn]

    def timeline(
        self, scenario: ScenarioDefinition, window_minutes: int | None = None
    ) -> list[dict[str, Any]]:
        events = sorted(scenario.timeline, key=lambda e: e.get("timestamp") or "")
        if not window_minutes or not scenario.incident_time:
            return events
        floor = scenario.incident_time - timedelta(minutes=window_minutes)
        return [e for e in events if (parse_dt(e.get("timestamp")) or floor) >= floor]

    # -- simulated remediation -------------------------------------------
    async def apply_remediation(
        self, scenario: ScenarioDefinition, step_ids: list[str]
    ) -> dict[str, Any]:
        row = await self._row(scenario)
        applied: list[str] = list(row.applied_effects or [])
        new_state = row.state
        for step_id in step_ids:
            effect = scenario.effect_for(step_id)
            if effect:
                new_state = effect
            applied.append(step_id)
        row.state = new_state
        row.applied_effects = applied
        row.updated_at = utcnow()
        await self.session.flush()
        logger.info(
            "scenario_remediation_applied",
            extra={"scenario_id": scenario.id, "state": new_state, "steps": step_ids},
        )
        return {"scenario_id": scenario.id, "state": new_state, "applied_steps": applied}

    # -- verification -----------------------------------------------------
    async def run_checks(self, scenario: ScenarioDefinition) -> list[CheckResult]:
        state = await self.get_state(scenario)
        view = scenario.state_view(state)
        results: list[CheckResult] = []
        for check in scenario.verification_checks:
            results.append(self._evaluate_check(check, view))
        return results

    def _evaluate_check(self, check: dict[str, Any], view: dict[str, Any]) -> CheckResult:
        kind = str(check.get("type", "")).upper()
        name = check.get("name", "check")
        critical = bool(check.get("critical", True))
        if kind == "METRIC":
            reading = next(
                (
                    m
                    for m in view.get("metrics", [])
                    if m.get("asset_urn") == check.get("asset_urn")
                    and m.get("name") == check.get("metric")
                ),
                None,
            )
            expected = float(check.get("expected", 0))
            tolerance = float(check.get("tolerance", 0.05))
            actual = float(reading.get("value")) if reading else None
            ok = (
                actual is not None
                and expected > 0
                and abs(actual - expected) / expected <= tolerance
            )
            return CheckResult(
                name=name,
                status=VerificationStatus.PASS if ok else VerificationStatus.FAIL,
                critical=critical,
                expected=f"{_fmt(expected)} (+/-{tolerance:.0%})",
                actual=_fmt(actual) if actual is not None else "unavailable",
                detail=check.get("description", ""),
                asset_urn=check.get("asset_urn"),
            )
        if kind == "QUALITY":
            reading = next(
                (
                    q
                    for q in view.get("quality", [])
                    if q.get("asset_urn") == check.get("asset_urn")
                    and q.get("check") == check.get("check")
                    and (check.get("field") is None or q.get("field") == check.get("field"))
                ),
                None,
            )
            max_value = float(check.get("max", 1.0))
            actual = float(reading.get("value")) if reading else None
            ok = actual is not None and actual <= max_value
            return CheckResult(
                name=name,
                status=VerificationStatus.PASS if ok else VerificationStatus.FAIL,
                critical=critical,
                expected=f"<= {max_value}",
                actual=actual if actual is not None else "unavailable",
                detail=check.get("description", ""),
                asset_urn=check.get("asset_urn"),
            )
        if kind == "MAPPING":
            mapping = next(
                (
                    m
                    for m in view.get("mappings", [])
                    if m.get("job_urn") == check.get("job_urn")
                    and (check.get("field") is None or m.get("field") == check.get("field"))
                ),
                None,
            )
            ok = bool(mapping) and mapping.get("status") == check.get("expected_status", "HEALTHY")
            return CheckResult(
                name=name,
                status=VerificationStatus.PASS if ok else VerificationStatus.FAIL,
                critical=critical,
                expected=check.get("expected_status", "HEALTHY"),
                actual=(mapping or {}).get("status", "unavailable"),
                detail=check.get("description", ""),
                asset_urn=check.get("job_urn"),
            )
        if kind == "DOWNSTREAM":
            checks = view.get("downstream_checks", {})
            total = int(check.get("expected_count", len(checks)))
            passing = sum(1 for value in checks.values() if value in (True, "PASS"))
            ok = total > 0 and passing >= total
            return CheckResult(
                name=name,
                status=VerificationStatus.PASS if ok else VerificationStatus.FAIL,
                critical=critical,
                expected=f"{total} downstream assets healthy",
                actual=f"{passing} / {total}",
                detail=check.get("description", ""),
            )
        return CheckResult(
            name=name,
            status=VerificationStatus.FAIL,
            critical=critical,
            detail=f"Unknown check type: {kind}",
        )
