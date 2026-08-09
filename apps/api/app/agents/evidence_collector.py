"""Evidence engine (DOCUMENT 04 - section 6).

Rules are generic: they describe *shapes* of signals (a change before the
incident on an asset that feeds the target, a quality reading far from its
baseline, an unresolved column mapping...), never a specific scenario. The same
code produces schema-drift evidence, freshness evidence or quality evidence
depending only on what DataHub and the scenario runtime actually contain.
"""

from __future__ import annotations

from typing import Any

from app.core.utils import parse_dt, urn_name
from app.domain.enums import EvidenceType, Relevance, SourceMode, SourceSystem
from app.domain.evidence import EvidenceItem
from app.agents.context import InvestigationContext
from app.services.scenario import ScenarioDefinition, ScenarioRuntime

FAILING_STATUSES = {"FAIL", "FAILURE", "ERROR", "FAILED", "BREACHED"}
SUCCESS_STATUSES = {"SUCCESS", "SUCCEEDED", "PASS", "OK", "COMPLETED"}
ML_ENTITY_TYPES = {"MLMODEL", "MLMODELGROUP", "MLFEATURETABLE", "MLFEATURE"}
DEFINITION_CHANGE_TYPES = {
    "JOB_DEFINITION_CHANGE",
    "TRANSFORMATION_CHANGE",
    "PIPELINE_CHANGE",
    "DATA_JOB_CHANGE",
}


def _deviation(value: float | None, baseline: float | None) -> float | None:
    if value is None or baseline is None:
        return None
    if baseline == 0:
        return None if value == 0 else float("inf")
    return abs(value - baseline) / abs(baseline)


# A schema change only breaks a downstream mapping when something the consumer
# relied on disappeared or changed shape. DataHub's timeline says which:
# `modificationCategory` RENAME / TYPE_CHANGE, a REMOVE operation, or a MAJOR
# semantic version bump. A newly added field is compatible by construction.
BREAKING_MODIFICATIONS = {"RENAME", "TYPE_CHANGE"}
BREAKING_OPERATIONS = {"REMOVE", "MODIFY"}


def _is_breaking_change(change: dict[str, Any], details: dict[str, Any]) -> bool:
    modification = str(details.get("modification_category") or "").upper()
    if modification in BREAKING_MODIFICATIONS:
        return True
    if str(details.get("sem_ver_change") or "").upper() == "MAJOR":
        return True
    if str(change.get("operation") or "").upper() in BREAKING_OPERATIONS:
        return True
    # A rename described in prose but not categorised: the fixture graph and
    # some connectors report it this way.
    summary = str(change.get("summary") or "").lower()
    return "renamed" in summary or "removed" in summary or "->" in summary


def _signed_change(value: float | None, baseline: float | None) -> float | None:
    """Signed relative change, for display.

    Scoring uses the magnitude (`_deviation`); a human reading the timeline
    needs the direction, so a revenue drop must not be printed as "+18.5%".
    """
    if value is None or baseline is None or baseline == 0:
        return None
    return (value - baseline) / abs(baseline)


def _relevance_from_deviation(deviation: float | None) -> Relevance:
    """Relevance scale for technical signals (null rates, freshness ratios...).

    Those signals move by orders of magnitude, so the thresholds are wide.
    """
    if deviation is None:
        return Relevance.MEDIUM
    if deviation >= 1.0:
        return Relevance.HIGH
    if deviation >= 0.25:
        return Relevance.MEDIUM
    return Relevance.LOW


def _relevance_from_metric_deviation(deviation: float | None) -> Relevance:
    """Relevance scale for *business* metrics.

    A revenue metric does not need to double to be alarming: a 18.5% drop is a
    major business signal, while the same ratio on a null rate is noise. Using
    the technical scale here would silently downgrade the incident symptom.
    """
    if deviation is None:
        return Relevance.MEDIUM
    if deviation >= 0.15:
        return Relevance.HIGH
    if deviation >= 0.05:
        return Relevance.MEDIUM
    return Relevance.LOW


class EvidenceCollector:
    def __init__(
        self,
        context: InvestigationContext,
        runtime: ScenarioRuntime | None = None,
        scenario: ScenarioDefinition | None = None,
        source_mode: SourceMode = SourceMode.DEMO_FIXTURE,
    ) -> None:
        self.context = context
        self.runtime = runtime
        self.scenario = scenario
        self.source_mode = source_mode

    # -- helpers ----------------------------------------------------------
    def _distance(self, urn: str | None) -> int | None:
        if not urn:
            return None
        return self.context.distance_to_target(urn)

    def _first_distance(self, *urns: str | None) -> int | None:
        """First resolvable lineage distance.

        `or` chaining cannot be used here: distance 0 (the incident asset
        itself) is falsy and would be silently skipped.
        """
        for urn in urns:
            distance = self._distance(urn)
            if distance is not None:
                return distance
        return None

    def _scenario_source(self, detail: str) -> str:
        return f"scenario-runtime:{self.scenario.id}:{detail}" if self.scenario else detail

    # -- collection -------------------------------------------------------
    async def collect(
        self, observed_value: str | None = None, expected_value: str | None = None
    ) -> list[EvidenceItem]:
        items: list[EvidenceItem] = []
        items.extend(await self._metric_evidence(observed_value, expected_value))
        items.extend(await self._quality_evidence())
        items.extend(self._schema_change_evidence())
        items.extend(await self._pipeline_evidence())
        items.extend(self._lineage_evidence(items))
        items.extend(self._ownership_evidence())
        items.extend(self._ml_evidence())
        return items

    async def _metric_evidence(
        self, observed_value: str | None, expected_value: str | None
    ) -> list[EvidenceItem]:
        items: list[EvidenceItem] = []
        if self.scenario and self.runtime:
            for reading in await self.runtime.metrics(self.scenario):
                deviation = _deviation(
                    _as_float(reading.get("value")), _as_float(reading.get("baseline"))
                )
                if deviation is None or deviation < 0.05:
                    continue
                change = _signed_change(
                    _as_float(reading.get("value")), _as_float(reading.get("baseline"))
                )
                items.append(
                    EvidenceItem(
                        type=EvidenceType.METRIC_CHANGE,
                        observation=(
                            f"{reading.get('name')} on "
                            f"{self.context.asset_name(reading.get('asset_urn'))}: "
                            f"{reading.get('value'):,} vs baseline {reading.get('baseline'):,}"
                            + (f" ({change:+.1%})" if change is not None else "")
                        ),
                        source=self._scenario_source("metrics"),
                        source_system=SourceSystem.SCENARIO_RUNTIME,
                        source_mode=self.source_mode,
                        asset_urn=reading.get("asset_urn"),
                        relevance=_relevance_from_metric_deviation(deviation),
                        observed_at=parse_dt(reading.get("observed_at"))
                        or self.context.incident_time,
                        lineage_distance=self._distance(reading.get("asset_urn")),
                        metadata={
                            "metric": reading.get("name"),
                            "value": reading.get("value"),
                            "baseline": reading.get("baseline"),
                            "unit": reading.get("unit"),
                            "deviation": round(deviation, 4),
                            "change": round(change, 4) if change is not None else None,
                        },
                    )
                )
        if not items and (observed_value or expected_value):
            items.append(
                EvidenceItem(
                    type=EvidenceType.METRIC_CHANGE,
                    observation=(
                        f"Reported anomaly on {self.context.asset_name(self.context.asset_urn)}: "
                        f"observed {observed_value}, expected {expected_value}"
                    ),
                    source="incident-report",
                    source_system=SourceSystem.APPLICATION,
                    source_mode=self.source_mode,
                    asset_urn=self.context.asset_urn,
                    relevance=Relevance.HIGH,
                    observed_at=self.context.incident_time,
                    lineage_distance=0,
                    metadata={"observed": observed_value, "expected": expected_value},
                )
            )
        return items

    async def _quality_evidence(self) -> list[EvidenceItem]:
        items: list[EvidenceItem] = []

        # 1. DataHub assertions (authoritative quality context).
        for assertion in self.context.quality.get("assertions", []):
            status = str(assertion.get("status", "")).upper()
            value = _as_float(assertion.get("value"))
            baseline = _as_float(assertion.get("baseline"))
            deviation = _deviation(value, baseline)
            if status not in FAILING_STATUSES and (deviation is None or deviation < 0.25):
                continue
            items.append(
                EvidenceItem(
                    type=EvidenceType.QUALITY_ANOMALY,
                    observation=_quality_sentence(assertion, deviation, self.context),
                    source="datahub:assertions",
                    source_system=SourceSystem.DATAHUB,
                    source_mode=self.source_mode,
                    asset_urn=assertion.get("asset_urn") or self.context.asset_urn,
                    field_path=assertion.get("field"),
                    relevance=Relevance.HIGH
                    if status in FAILING_STATUSES
                    else _relevance_from_deviation(deviation),
                    observed_at=parse_dt(assertion.get("observed_at")),
                    lineage_distance=self._distance(
                        assertion.get("asset_urn") or self.context.asset_urn
                    ),
                    metadata={k: v for k, v in assertion.items() if k != "asset_urn"},
                )
            )

        # 2. Scenario runtime readings (live-like measurements for the demo).
        if self.scenario and self.runtime:
            for reading in await self.runtime.quality(self.scenario):
                status = str(reading.get("status", "")).upper()
                deviation = _deviation(
                    _as_float(reading.get("value")), _as_float(reading.get("baseline"))
                )
                if status not in FAILING_STATUSES and (deviation is None or deviation < 0.25):
                    continue
                items.append(
                    EvidenceItem(
                        type=EvidenceType.QUALITY_ANOMALY,
                        observation=_quality_sentence(reading, deviation, self.context),
                        source=self._scenario_source("quality"),
                        source_system=SourceSystem.SCENARIO_RUNTIME,
                        source_mode=self.source_mode,
                        asset_urn=reading.get("asset_urn"),
                        field_path=reading.get("field"),
                        relevance=Relevance.HIGH
                        if status in FAILING_STATUSES
                        else _relevance_from_deviation(deviation),
                        observed_at=parse_dt(reading.get("observed_at")),
                        lineage_distance=self._distance(reading.get("asset_urn")),
                        metadata={
                            "check": reading.get("check"),
                            "value": reading.get("value"),
                            "baseline": reading.get("baseline"),
                            "status": reading.get("status"),
                            "kind": reading.get("kind"),
                        },
                    )
                )
        return items

    def _schema_change_evidence(self) -> list[EvidenceItem]:
        items: list[EvidenceItem] = []
        for urn, changes in self.context.changes.items():
            distance = self._distance(urn)
            for change in changes:
                change_type = str(change.get("type", "")).upper()
                if change_type in DEFINITION_CHANGE_TYPES:
                    items.append(self._definition_change_evidence(urn, change, distance))
                    continue
                if change_type not in {"SCHEMA_CHANGE", "TECHNICAL_SCHEMA"}:
                    continue
                moment = parse_dt(change.get("timestamp"))
                precedes = bool(
                    moment and self.context.incident_time and moment <= self.context.incident_time
                )
                # A change that happened *after* the incident cannot have caused
                # it. Seeding a catalog, or any later edit, otherwise shows up as
                # a pile of schema changes competing with the real cause — and
                # winning, because there are more of them.
                if moment and self.context.incident_time and not precedes:
                    continue

                details = change.get("details", {}) or {}
                breaking = _is_breaking_change(change, details)
                on_path = self.context.on_path_to_target(urn)
                if not breaking:
                    # An additive, backwards-compatible change cannot break an
                    # existing mapping. It stays in the record as context, but it
                    # must not carry a causal hypothesis.
                    relevance = Relevance.LOW
                else:
                    relevance = (
                        Relevance.HIGH
                        if precedes and on_path
                        else Relevance.MEDIUM
                        if precedes or on_path
                        else Relevance.LOW
                    )
                items.append(
                    EvidenceItem(
                        type=EvidenceType.SCHEMA_CHANGE,
                        observation=(
                            f"{self.context.asset_name(urn)}: {change.get('summary')}"
                        ),
                        source="datahub:timeline",
                        source_system=SourceSystem.DATAHUB,
                        source_mode=self.source_mode,
                        asset_urn=urn,
                        field_path=details.get("field") or details.get("from_field"),
                        relevance=relevance,
                        observed_at=moment,
                        lineage_distance=distance,
                        metadata={
                            "operation": change.get("operation"),
                            "precedes_incident": precedes,
                            "on_path_to_target": on_path,
                            "breaking": breaking,
                            **details,
                        },
                    )
                )
        return items

    def _definition_change_evidence(
        self, urn: str, change: dict[str, Any], distance: int | None
    ) -> EvidenceItem:
        moment = parse_dt(change.get("timestamp"))
        precedes = bool(
            moment and self.context.incident_time and moment <= self.context.incident_time
        )
        return EvidenceItem(
            type=EvidenceType.PIPELINE_CHANGE,
            observation=f"{self.context.asset_name(urn)}: {change.get('summary')}",
            source="datahub:timeline",
            source_system=SourceSystem.DATAHUB,
            source_mode=self.source_mode,
            asset_urn=urn,
            relevance=Relevance.HIGH if precedes else Relevance.MEDIUM,
            observed_at=moment,
            lineage_distance=distance,
            metadata={
                "definition_changed": True,
                "operation": change.get("operation"),
                "precedes_incident": precedes,
                **(change.get("details", {}) or {}),
            },
        )

    async def _pipeline_evidence(self) -> list[EvidenceItem]:
        items: list[EvidenceItem] = []
        if not (self.scenario and self.runtime):
            return items

        # Unresolved column mappings in a transformation are a first class signal.
        for mapping in await self.runtime.mappings(self.scenario):
            resolved = mapping.get("resolved_source_field")
            expected = mapping.get("expected_source_field")
            if resolved and resolved == expected:
                continue
            items.append(
                EvidenceItem(
                    type=EvidenceType.PIPELINE_CHANGE,
                    observation=(
                        f"{self.context.asset_name(mapping.get('job_urn'))}: column mapping for "
                        f"'{mapping.get('field')}' is unresolved "
                        f"(expects '{expected}', resolved '{resolved}')"
                    ),
                    source=self._scenario_source("mappings"),
                    source_system=SourceSystem.SCENARIO_RUNTIME,
                    source_mode=self.source_mode,
                    asset_urn=mapping.get("job_urn"),
                    field_path=mapping.get("field"),
                    relevance=Relevance.HIGH,
                    observed_at=parse_dt(mapping.get("observed_at"))
                    or self.context.incident_time,
                    lineage_distance=self._first_distance(
                        mapping.get("output_urn"), mapping.get("job_urn")
                    ),
                    metadata={
                        "mapping_unresolved": True,
                        "expected_source_field": expected,
                        "resolved_source_field": resolved,
                        "job_urn": mapping.get("job_urn"),
                        "output_urn": mapping.get("output_urn"),
                    },
                )
            )

        # Pipeline executions: failures, lags, and healthy runs (which contradict
        # a "pipeline failure" hypothesis).
        for run in await self.runtime.pipeline_runs(self.scenario):
            status = str(run.get("status", "")).upper()
            lag = _as_float(run.get("lag_minutes"))
            sla = _as_float(run.get("sla_minutes"))
            failed = status in FAILING_STATUSES
            late = lag is not None and sla is not None and lag > sla
            if failed:
                observation = (
                    f"{self.context.asset_name(run.get('job_urn'))}: last execution FAILED "
                    f"({run.get('detail', 'no detail')})"
                )
                relevance = Relevance.HIGH
            elif late:
                observation = (
                    f"{self.context.asset_name(run.get('job_urn'))}: last successful execution is "
                    f"{lag:.0f} min old (SLA {sla:.0f} min)"
                )
                relevance = Relevance.HIGH
            else:
                observation = (
                    f"{self.context.asset_name(run.get('job_urn'))}: last execution completed "
                    f"successfully at {run.get('finished_at')}"
                )
                relevance = Relevance.MEDIUM
            items.append(
                EvidenceItem(
                    type=EvidenceType.PIPELINE_CHANGE,
                    observation=observation,
                    source=self._scenario_source("pipeline_runs"),
                    source_system=SourceSystem.SCENARIO_RUNTIME,
                    source_mode=self.source_mode,
                    asset_urn=run.get("job_urn"),
                    relevance=relevance,
                    observed_at=parse_dt(run.get("finished_at")),
                    lineage_distance=self._first_distance(
                        run.get("output_urn"), run.get("job_urn")
                    ),
                    metadata={
                        "status": status,
                        "failed": failed,
                        "late": late,
                        "lag_minutes": lag,
                        "sla_minutes": sla,
                        "job_urn": run.get("job_urn"),
                    },
                )
            )
        return items

    def _lineage_evidence(self, collected: list[EvidenceItem]) -> list[EvidenceItem]:
        """Prove that each implicated asset actually feeds the target asset."""
        items: list[EvidenceItem] = []
        seen: set[str] = set()
        edges = self.context.lineage.get("edges", [])
        for item in collected:
            urn = item.asset_urn
            if not urn or urn in seen or urn == self.context.asset_urn:
                continue
            if item.type in {EvidenceType.OWNERSHIP_SIGNAL, EvidenceType.ML_SIGNAL}:
                continue
            node = self.context.node(urn)
            if not node or node.get("direction") != "UPSTREAM":
                continue
            seen.add(urn)
            path = _path_labels(edges, urn, self.context.asset_urn, self.context)
            distance = node.get("distance")
            items.append(
                EvidenceItem(
                    type=EvidenceType.LINEAGE_DEPENDENCY,
                    observation=(
                        f"{self.context.asset_name(urn)} feeds "
                        f"{self.context.asset_name(self.context.asset_urn)} "
                        f"({distance} hop(s)): {path}"
                    ),
                    source="datahub:lineage",
                    source_system=SourceSystem.DATAHUB,
                    source_mode=self.source_mode,
                    asset_urn=urn,
                    relevance=Relevance.HIGH if (distance or 99) <= 3 else Relevance.MEDIUM,
                    observed_at=self.context.incident_time,
                    lineage_distance=distance,
                    metadata={"path": path, "distance": distance},
                )
            )
        return items

    def _ownership_evidence(self) -> list[EvidenceItem]:
        if not self.context.owners:
            return []
        names = ", ".join(
            str(o.get("name") or o.get("urn")) for o in self.context.owners[:5]
        )
        return [
            EvidenceItem(
                type=EvidenceType.OWNERSHIP_SIGNAL,
                observation=(
                    f"{self.context.asset_name(self.context.asset_urn)} is owned by {names}"
                ),
                source="datahub:ownership",
                source_system=SourceSystem.DATAHUB,
                source_mode=self.source_mode,
                asset_urn=self.context.asset_urn,
                relevance=Relevance.LOW,
                observed_at=self.context.incident_time,
                lineage_distance=0,
                metadata={"owners": self.context.owners},
            )
        ]

    def _ml_evidence(self) -> list[EvidenceItem]:
        ml_nodes = [
            n
            for n in self.context.downstream
            if str(n.get("entity_type", "")).upper() in ML_ENTITY_TYPES
        ]
        if not ml_nodes:
            return []
        names = ", ".join(str(n.get("name") or urn_name(n.get("urn"))) for n in ml_nodes[:5])
        return [
            EvidenceItem(
                type=EvidenceType.ML_SIGNAL,
                observation=(
                    f"{len(ml_nodes)} ML asset(s) consume the affected data downstream: {names}"
                ),
                source="datahub:lineage",
                source_system=SourceSystem.DATAHUB,
                source_mode=self.source_mode,
                asset_urn=self.context.asset_urn,
                relevance=Relevance.MEDIUM,
                observed_at=self.context.incident_time,
                lineage_distance=0,
                metadata={"ml_assets": [n.get("urn") for n in ml_nodes]},
            )
        ]


def _as_float(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _quality_sentence(
    reading: dict[str, Any], deviation: float | None, context: InvestigationContext
) -> str:
    asset = context.asset_name(reading.get("asset_urn") or context.asset_urn)
    check = reading.get("check") or reading.get("name") or reading.get("type") or "quality check"
    field = reading.get("field")
    scope = f"{check} on {field}" if field else str(check)
    value = reading.get("value")
    baseline = reading.get("baseline")
    if value is not None and baseline is not None:
        change = f"{baseline} -> {value}"
        if deviation is not None and deviation != float("inf"):
            change += f" ({deviation:+.1%})"
        return f"{asset}: {scope} moved {change}"
    return f"{asset}: {scope} status {reading.get('status', 'UNKNOWN')}"


def _path_labels(
    edges: list[dict[str, Any]], source: str, target: str, context: InvestigationContext
) -> str:
    """Shortest path label from source to target using the retrieved edges."""
    from collections import deque

    adjacency: dict[str, list[str]] = {}
    for edge in edges:
        adjacency.setdefault(edge["upstream"], []).append(edge["downstream"])
    queue: deque[list[str]] = deque([[source]])
    visited = {source}
    while queue:
        path = queue.popleft()
        if path[-1] == target:
            return " -> ".join(context.asset_name(urn) for urn in path)
        for neighbour in adjacency.get(path[-1], []):
            if neighbour in visited:
                continue
            visited.add(neighbour)
            queue.append([*path, neighbour])
    return f"{context.asset_name(source)} -> ... -> {context.asset_name(target)}"
