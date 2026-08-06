"""Agent reasoning: the same engine must reach different conclusions."""

from __future__ import annotations

import pytest

from app.domain.enums import EvidenceType, HypothesisStatus, IncidentStatus
from tests.helpers import expected_truth, run_scenario

SCENARIOS = ["revenue-collapse", "pipeline-freshness", "healthcare-quality"]


class TestEveryScenarioIsSolvedByTheSameEngine:
    """Anti-cheat (DOCUMENT 08 - section 20).

    Nothing maps an incident title to an answer: three different signal shapes
    over one generic engine must produce three different root causes.
    """

    @pytest.mark.parametrize("scenario_id", SCENARIOS)
    async def test_expected_root_cause_is_found(self, session, scenario_id: str) -> None:
        truth = expected_truth(scenario_id)
        output = await run_scenario(session, scenario_id)

        assert output["root_cause"]["pattern"] == truth["root_cause_pattern"]
        assert output["root_cause"]["confidence"] >= truth["minimum_confidence"]

    @pytest.mark.parametrize("scenario_id", SCENARIOS)
    async def test_expected_evidence_types_are_collected(self, session, scenario_id: str) -> None:
        truth = expected_truth(scenario_id)
        output = await run_scenario(session, scenario_id)
        collected = {item["type"] for item in output["evidence"]}
        assert set(truth["expected_evidence_types"]) <= collected

    @pytest.mark.parametrize("scenario_id", SCENARIOS)
    async def test_alternative_hypotheses_are_evaluated_and_rejected(
        self, session, scenario_id: str
    ) -> None:
        truth = expected_truth(scenario_id)
        output = await run_scenario(session, scenario_id)

        assert len(output["hypotheses"]) >= truth["minimum_hypotheses"]
        by_pattern = {h["pattern"]: h for h in output["hypotheses"]}
        for pattern in truth["rejected_patterns"]:
            assert pattern in by_pattern, f"{pattern} was never even considered"
            assert by_pattern[pattern]["status"] in {
                str(HypothesisStatus.REJECTED),
                str(HypothesisStatus.WEAKENED),
            }

    async def test_the_three_scenarios_do_not_share_a_conclusion(self, session) -> None:
        patterns = set()
        for scenario_id in SCENARIOS:
            output = await run_scenario(session, scenario_id)
            patterns.add(output["root_cause"]["pattern"])
        assert len(patterns) == len(SCENARIOS)


class TestEvidenceDiscipline:
    """Golden rule: evidence before inference (DOCUMENT 04 - section 21)."""

    async def test_the_root_cause_is_backed_by_non_symptom_evidence(self, session) -> None:
        output = await run_scenario(session, "revenue-collapse")
        by_id = {item["id"]: item for item in output["evidence"]}
        supporting = [by_id[eid] for eid in output["root_cause"]["evidence_ids"] if eid in by_id]

        assert supporting, "a root cause with no evidence must never be published"
        causal = [e for e in supporting if e["type"] != str(EvidenceType.METRIC_CHANGE)]
        assert causal, "the symptom alone cannot support its own explanation"

    async def test_every_evidence_item_declares_its_source(self, session) -> None:
        output = await run_scenario(session, "revenue-collapse")
        for item in output["evidence"]:
            assert item["source"], f"evidence {item['id']} has no source"
            assert item["source_system"] in {"DATAHUB", "SCENARIO_RUNTIME", "APPLICATION"}
            assert item["source_mode"] in {"LIVE_DATAHUB", "DEMO_FIXTURE"}

    async def test_the_causal_chain_links_back_to_evidence(self, session) -> None:
        output = await run_scenario(session, "revenue-collapse")
        chain = output["causal_chain"]
        assert len(chain) >= 3
        assert any(step.get("evidence_ids") for step in chain)

    async def test_lineage_is_traversed_beyond_the_incident_asset(self, session) -> None:
        """AC2: the agent must not stop at the asset it was handed."""
        output = await run_scenario(session, "revenue-collapse")
        distances = [
            item["lineage_distance"]
            for item in output["evidence"]
            if item["lineage_distance"] is not None
        ]
        assert max(distances) >= 2


class TestResolutionDiscipline:
    async def test_resolution_requires_a_passing_verification(self, session) -> None:
        output = await run_scenario(session, "revenue-collapse")
        assert output["verification"]["status"] == "PASS"
        assert output["_incident"].status == str(IncidentStatus.RESOLVED)

    async def test_knowledge_is_written_back_after_resolution(self, session) -> None:
        output = await run_scenario(session, "revenue-collapse")
        memory = output["memory"]
        assert memory is not None
        assert memory["write_back_status"] in {"VERIFIED", "WRITTEN_UNVERIFIED"}
        assert memory["datahub_reference"]
        assert memory["document"]["pattern"] == "SCHEMA_DRIFT"

    async def test_blast_radius_is_computed_from_lineage(self, session) -> None:
        truth = expected_truth("revenue-collapse")
        output = await run_scenario(session, "revenue-collapse")
        blast = output["blast_radius"]
        assert blast["total_affected_assets"] >= truth["blast_radius"]["minimum_affected_assets"]
        assert blast["owner_count"] >= truth["blast_radius"]["minimum_owners"]
        assert blast["computed_from"]["lineage_node_count"] > 0
        assert blast["affected_assets"]
