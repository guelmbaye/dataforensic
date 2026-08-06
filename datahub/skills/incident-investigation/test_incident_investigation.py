"""Skill tests. Run against a fake client so no DataHub instance is needed."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from incident_investigation import IncidentInvestigationSkill, SkillError

A = "urn:li:dataset:(urn:li:dataPlatform:postgres,src,PROD)"
B = "urn:li:dataset:(urn:li:dataPlatform:snowflake,mid,PROD)"
C = "urn:li:dataset:(urn:li:dataPlatform:snowflake,target,PROD)"
DASH = "urn:li:dashboard:(looker,board)"
ML = "urn:li:mlModel:(urn:li:dataPlatform:mlflow,model,PROD)"

OWNER = {"urn": "urn:li:corpGroup:team", "name": "Team"}


class FakeClient:
    def __init__(self, changes: dict[str, list[dict[str, Any]]] | None = None) -> None:
        self.changes = changes or {A: [{"type": "SCHEMA_CHANGE", "timestamp": "2026-03-11T10:02:00Z"}]}
        self.calls: list[str] = []

    async def get_asset_context(self, urn: str):
        self.calls.append(f"get_asset_context:{urn}")
        return {"urn": urn, "name": "target", "platform": "snowflake"}

    async def get_schema(self, urn: str):
        return {"urn": urn, "fields": [{"path": "amount", "type": "number"}]}

    async def get_lineage(self, urn: str, direction: str = "BOTH", depth: int = 3):
        nodes = [{"urn": urn, "direction": "SELF", "distance": 0, "name": "target"}]
        if direction in {"BOTH", "UPSTREAM"}:
            nodes += [
                {"urn": B, "direction": "UPSTREAM", "distance": 1, "name": "mid", "entity_type": "DATASET"},
                {"urn": A, "direction": "UPSTREAM", "distance": 2, "name": "src", "entity_type": "DATASET"},
            ]
        if direction in {"BOTH", "DOWNSTREAM"}:
            nodes += [
                {"urn": DASH, "direction": "DOWNSTREAM", "distance": 1, "name": "board",
                 "entity_type": "DASHBOARD", "owners": [OWNER]},
                {"urn": ML, "direction": "DOWNSTREAM", "distance": 1, "name": "model",
                 "entity_type": "MLMODEL", "owners": [OWNER]},
            ]
        edges = [
            {"upstream": A, "downstream": B},
            {"upstream": B, "downstream": C},
            {"upstream": C, "downstream": DASH},
            {"upstream": C, "downstream": ML},
        ]
        return {"nodes": nodes, "edges": edges, "direction": direction, "depth": depth}

    async def get_ownership(self, urn: str):
        return {"urn": urn, "owners": [OWNER]}

    async def get_quality_context(self, urn: str):
        return {"urn": urn, "assertions": [{"name": "freshness", "status": "PASS"}]}

    async def find_changes(self, urn: str, since: Any = None, until: Any = None):
        return {"urn": urn, "changes": self.changes.get(urn, [])}


class FailingContext(FakeClient):
    async def get_asset_context(self, urn: str):
        class Result:
            success = False
            error = "connection refused"
            data: dict = {}

        return Result()


class TestContextCollection:
    def test_collects_every_dimension(self) -> None:
        skill = IncidentInvestigationSkill(FakeClient())
        context = asyncio.run(
            skill.collect_incident_context(C, incident_time="2026-03-11T10:20:00Z", depth=3)
        )
        assert context["asset"]["urn"] == C
        assert context["schema"]["fields"]
        assert context["owners"] == [OWNER]
        assert context["quality_signals"]
        assert context["counts"]["upstream"] == 2
        assert context["counts"]["downstream"] == 2

    def test_upstream_paths_are_ordered_by_distance(self) -> None:
        skill = IncidentInvestigationSkill(FakeClient())
        context = asyncio.run(skill.collect_incident_context(C))
        distances = [node["distance"] for node in context["upstream_paths"]]
        assert distances == sorted(distances)

    def test_missing_required_context_raises_instead_of_returning_empty(self) -> None:
        skill = IncidentInvestigationSkill(FailingContext())
        with pytest.raises(SkillError, match="connection refused"):
            asyncio.run(skill.collect_incident_context(C))


class TestLineage:
    def test_path_between_source_and_target_is_reconstructed(self) -> None:
        skill = IncidentInvestigationSkill(FakeClient())
        traced = asyncio.run(skill.trace_incident_lineage(C, depth=3))
        assert traced["paths_to_target"][A] == [A, B, C]

    def test_changes_are_collected_on_upstream_assets_too(self) -> None:
        skill = IncidentInvestigationSkill(FakeClient())
        changes = asyncio.run(
            skill.find_recent_changes(C, incident_time="2026-03-11T10:20:00Z")
        )
        assert A in changes
        assert changes[A][0]["type"] == "SCHEMA_CHANGE"


class TestImpact:
    def test_consumers_are_bucketed_and_owners_deduplicated(self) -> None:
        skill = IncidentInvestigationSkill(FakeClient())
        impact = asyncio.run(skill.summarise_downstream_impact(C, depth=3))
        assert impact["counts"]["dashboards"] == 1
        assert impact["counts"]["ml_assets"] == 1
        assert impact["total_affected_assets"] == 2
        assert impact["terminal_consumers"] == 2
        assert impact["owner_count"] == 1


class TestWriteBack:
    def _summary(self, **overrides: Any) -> dict[str, Any]:
        return {
            "incident_id": "abc",
            "asset_urn": C,
            "pattern": "schema drift",
            "root_cause": "Broken mapping",
            "confidence": 0.97,
            "evidence": [{"type": "SCHEMA_CHANGE", "observation": "renamed", "relevance": "HIGH"}],
            "affected_assets": [DASH],
            **overrides,
        }

    def test_document_is_normalised(self) -> None:
        skill = IncidentInvestigationSkill(FakeClient())
        document = skill.prepare_incident_writeback(self._summary())
        assert document["pattern"] == "SCHEMA_DRIFT"
        assert document["tag"] == "DataForensic:SCHEMA_DRIFT"
        assert document["schema_version"] == "1.0"

    def test_missing_fields_are_refused(self) -> None:
        skill = IncidentInvestigationSkill(FakeClient())
        summary = self._summary()
        del summary["root_cause"]
        with pytest.raises(SkillError, match="root_cause"):
            skill.prepare_incident_writeback(summary)

    def test_confidence_outside_zero_one_is_refused(self) -> None:
        skill = IncidentInvestigationSkill(FakeClient())
        with pytest.raises(SkillError, match="between 0 and 1"):
            skill.prepare_incident_writeback(self._summary(confidence=97))


class TestOptionalCapabilities:
    def test_memory_search_degrades_when_unsupported(self) -> None:
        skill = IncidentInvestigationSkill(FakeClient())
        assert asyncio.run(skill.find_similar_incident(asset_urn=C)) == []
