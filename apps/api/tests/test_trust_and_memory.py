"""Trust score and organisational memory.

The claim being tested is the product's central one: every resolved incident
becomes knowledge, and that knowledge makes the next investigation better
without ever replacing it.
"""

from __future__ import annotations

import pytest

from app.agents.context import InvestigationContext
from app.agents.trust import compute_trust_score
from app.domain.enums import EvidenceType, Relevance
from app.domain.evidence import EvidenceItem
from app.domain.hypothesis import HypothesisCandidate
from app.domain.trust import TrustCheckStatus, TrustDecision
from app.models.tables import Investigation, KnowledgePattern
from app.schemas.memory import PreviousIncidentMatch
from app.services.patterns import PatternLibrary
from tests.helpers import event_names, run_scenario

TARGET = "urn:li:dataset:(urn:li:dataPlatform:snowflake,TARGET,PROD)"
UPSTREAM = "urn:li:dataset:(urn:li:dataPlatform:snowflake,UPSTREAM,PROD)"


def context(*, schemas=True, lineage=True, quality=True) -> InvestigationContext:
    ctx = InvestigationContext(asset_urn=TARGET)
    if schemas:
        ctx.schema = {"fields": [{"path": "net_amount"}, {"path": "discount_amount"}]}
        ctx.schemas = {TARGET: ctx.schema}
    if lineage:
        ctx.lineage = {
            "nodes": [
                {"urn": TARGET, "direction": "SELF", "distance": 0},
                {"urn": UPSTREAM, "direction": "UPSTREAM", "distance": 1},
                {"urn": "urn:li:dashboard:(looker,board)", "direction": "DOWNSTREAM", "distance": 1},
            ],
            "edges": [],
        }
    if quality:
        ctx.quality = {"assertions": [{"name": "freshness", "status": "PASS"}]}
    return ctx


def evidence(kind: EvidenceType, relevance=Relevance.HIGH, field=None, asset=UPSTREAM):
    return EvidenceItem(
        type=kind,
        observation="signal",
        source="test",
        relevance=relevance,
        asset_urn=asset,
        field_path=field,
    )


def rich_evidence() -> list[EvidenceItem]:
    return [
        evidence(EvidenceType.SCHEMA_CHANGE, field="discount_amount"),
        evidence(EvidenceType.QUALITY_ANOMALY),
        evidence(EvidenceType.PIPELINE_CHANGE),
        evidence(EvidenceType.LINEAGE_DEPENDENCY, Relevance.MEDIUM),
    ]


def hypothesis(items: list[EvidenceItem], pattern="SCHEMA_DRIFT") -> HypothesisCandidate:
    return HypothesisCandidate(
        pattern=pattern, description="test", supporting=items, confidence=0.97
    )


class TestTrustIsIndependentOfConfidence:
    def test_a_well_grounded_investigation_scores_high(self) -> None:
        items = rich_evidence()
        score = compute_trust_score(
            context(),
            items,
            hypothesis(items),
            [PreviousIncidentMatch(root_cause="x", pattern="SCHEMA_DRIFT", similarity=0.9)],
        )
        assert score.score >= 85
        assert score.decision is TrustDecision.HIGH_CONFIDENCE

    def test_a_confident_conclusion_on_a_thin_context_is_not_trusted(self) -> None:
        """The case the score exists for: certain, and barely grounded."""
        thin = [evidence(EvidenceType.QUALITY_ANOMALY)]
        score = compute_trust_score(
            context(schemas=False, lineage=False, quality=False),
            thin,
            hypothesis(thin),
            [],
        )
        assert score.score < 40
        assert score.decision is TrustDecision.INSUFFICIENT_GROUNDING
        assert "incomplete" in score.rationale()

    def test_the_score_never_reads_the_hypothesis_confidence(self) -> None:
        items = rich_evidence()
        certain = hypothesis(items)
        certain.confidence = 0.99
        doubtful = hypothesis(items)
        doubtful.confidence = 0.11
        assert (
            compute_trust_score(context(), items, certain, []).score
            == compute_trust_score(context(), items, doubtful, []).score
        )


class TestTrustChecks:
    def test_missing_schema_fails_schema_validation(self) -> None:
        items = rich_evidence()
        score = compute_trust_score(context(schemas=False), items, hypothesis(items), [])
        check = next(c for c in score.checks if c.key == "schema_validation")
        assert check.status is TrustCheckStatus.FAIL
        assert check.points == 0

    def test_a_field_absent_from_every_schema_fails(self) -> None:
        items = [evidence(EvidenceType.SCHEMA_CHANGE, field="field_that_does_not_exist")]
        score = compute_trust_score(context(), items, hypothesis(items), [])
        check = next(c for c in score.checks if c.key == "schema_validation")
        assert check.status is TrustCheckStatus.FAIL
        assert "field_that_does_not_exist" in check.detail

    def test_a_signal_outside_the_graph_downgrades_lineage_coverage(self) -> None:
        items = [*rich_evidence(), evidence(EvidenceType.QUALITY_ANOMALY, asset="urn:li:dataset:(x,orphan,PROD)")]
        score = compute_trust_score(context(), items, hypothesis(items), [])
        check = next(c for c in score.checks if c.key == "lineage_coverage")
        assert check.status is TrustCheckStatus.PARTIAL

    def test_no_precedent_is_reported_neutrally_not_as_a_defect(self) -> None:
        items = rich_evidence()
        score = compute_trust_score(context(), items, hypothesis(items), [])
        check = next(c for c in score.checks if c.key == "historical_match")
        assert check.status is TrustCheckStatus.FAIL
        assert "First time" in check.detail
        # A first-ever incident must still be able to clear the high bar.
        assert score.score >= 85 - 15

    def test_a_precedent_with_a_different_conclusion_only_partially_counts(self) -> None:
        items = rich_evidence()
        score = compute_trust_score(
            context(),
            items,
            hypothesis(items),
            [PreviousIncidentMatch(root_cause="x", pattern="PIPELINE_FAILURE", similarity=0.7)],
        )
        check = next(c for c in score.checks if c.key == "historical_match")
        assert check.status is TrustCheckStatus.PARTIAL


class TestPatternLibrary:
    async def _pattern(self, session, verified=True, pattern="SCHEMA_DRIFT") -> KnowledgePattern:
        investigation = Investigation(
            incident_id="incident-1",
            status="COMPLETED",
            phase="MEMORY_WRITTEN",
            root_cause_pattern=pattern,
            root_cause_summary="Broken mapping",
            confidence=0.97,
            trust_score=90.0,
        )
        session.add(investigation)
        await session.flush()
        return await PatternLibrary(session).record(
            investigation=investigation,
            symptom="Revenue anomaly on sales_daily",
            evidence=[{"type": "SCHEMA_CHANGE", "relevance": "HIGH"}],
            remediation_plan={"steps": [{"id": "a", "title": "Restore mapping", "risk": "LOW"}]},
            affected_assets=[TARGET],
            verification_passed=verified,
        )

    async def test_a_resolved_incident_becomes_a_pattern(self, session) -> None:
        row = await self._pattern(session)
        assert row is not None
        assert row.occurrences == 1
        assert row.verified_resolutions == 1
        assert row.resolution_steps == ["Restore mapping"]
        assert "SCHEMA_CHANGE" in row.evidence_signature

    async def test_repeat_occurrences_accumulate(self, session) -> None:
        await self._pattern(session)
        row = await self._pattern(session)
        assert row.occurrences == 2
        assert row.average_confidence == pytest.approx(0.97)
        assert row.average_trust_score == pytest.approx(90.0)
        assert len(row.occurrences_log) == 2

    async def test_an_unverified_fix_never_becomes_the_recommendation(self, session) -> None:
        """Otherwise the library would teach the next investigation a fix that failed."""
        row = await self._pattern(session, verified=False)
        assert row.occurrences == 1
        assert row.verified_resolutions == 0
        assert row.resolution_steps == []

    async def test_a_similar_symptom_matches_the_pattern(self, session) -> None:
        await self._pattern(session)
        matches = await PatternLibrary(session).match(
            symptom="Revenue anomaly detected on sales_daily", asset_urn=TARGET
        )
        assert matches
        assert matches[0].pattern == "SCHEMA_DRIFT"
        assert matches[0].similarity > 0
        assert matches[0].recommended_remediation == ["Restore mapping"]
        assert matches[0].match_reasons

    async def test_an_unrelated_symptom_does_not_match(self, session) -> None:
        await self._pattern(session)
        matches = await PatternLibrary(session).match(
            symptom="Kafka consumer lag on the clickstream topic"
        )
        assert matches == []


class TestOrganisationalLearningLoop:
    async def test_the_first_investigation_has_no_precedent(self, session) -> None:
        output = await run_scenario(session, "revenue-collapse")
        assert output["learning"]["memory_assisted"] is False
        assert output["learning"]["matched_pattern"] is None
        assert output["learning"]["remediation_source"] == "generated"
        assert "known_pattern_detected" not in event_names(output)

    async def test_the_second_investigation_recognises_the_pattern(self, session) -> None:
        await run_scenario(session, "revenue-collapse")
        second = await run_scenario(session, "revenue-collapse")

        assert second["learning"]["memory_assisted"] is True
        assert second["learning"]["matched_pattern"] == "SCHEMA_DRIFT"
        assert second["learning"]["remediation_source"] == "knowledge_pattern:SCHEMA_DRIFT"
        assert second["learning"]["reused_from_investigation_id"]
        names = event_names(second)
        assert "known_pattern_detected" in names
        assert "remediation_reused" in names

    async def test_trust_rises_once_a_precedent_exists(self, session) -> None:
        first = await run_scenario(session, "revenue-collapse")
        second = await run_scenario(session, "revenue-collapse")
        assert second["trust"]["score"] > first["trust"]["score"]
        assert second["trust"]["decision"] == "HIGH_CONFIDENCE"

    async def test_memory_accelerates_but_never_replaces_the_investigation(
        self, session
    ) -> None:
        """The line the whole design depends on.

        A recognised pattern must not let the agent skip work: the second run
        still gathers its own evidence, still scores every alternative, and still
        verifies before resolving. Otherwise memory becomes a cache of answers.
        """
        first = await run_scenario(session, "revenue-collapse")
        second = await run_scenario(session, "revenue-collapse")

        first_causal = {e["type"] for e in first["evidence"]}
        second_causal = {e["type"] for e in second["evidence"]}
        assert first_causal <= second_causal, "the second run collected less evidence"

        assert len(second["hypotheses"]) >= len(first["hypotheses"])
        assert {h["pattern"] for h in second["hypotheses"]} >= {
            h["pattern"] for h in first["hypotheses"]
        }
        assert second["verification"]["status"] == "PASS"
        assert second["learning"]["tool_call_count"] > 0

    async def test_the_effort_of_both_runs_is_measured(self, session) -> None:
        first = await run_scenario(session, "revenue-collapse")
        second = await run_scenario(session, "revenue-collapse")
        for run in (first, second):
            assert run["learning"]["duration_ms"] > 0
            assert run["learning"]["tool_call_count"] > 0

    async def test_a_different_incident_does_not_reuse_the_wrong_plan(
        self, session
    ) -> None:
        await run_scenario(session, "revenue-collapse")
        other = await run_scenario(session, "pipeline-freshness")
        assert other["root_cause"]["pattern"] == "FRESHNESS_STALENESS"
        assert other["learning"]["remediation_source"] == "generated"

    async def test_the_library_grows_across_different_failure_modes(
        self, session
    ) -> None:
        await run_scenario(session, "revenue-collapse")
        await run_scenario(session, "pipeline-freshness")
        patterns = {row.pattern for row in await PatternLibrary(session).all()}
        assert {"SCHEMA_DRIFT", "FRESHNESS_STALENESS"} <= patterns


class TestWriteBackCarriesTheKnowledge:
    async def test_the_document_contains_the_full_investigation_object(
        self, session
    ) -> None:
        output = await run_scenario(session, "revenue-collapse")
        document = output["memory"]["document"]
        assert document["pattern"] == "SCHEMA_DRIFT"
        assert document["hypotheses_considered"], "rejected alternatives must travel too"
        assert document["blast_radius"]["total_affected_assets"] > 0
        assert document["trust_score"] > 0
        assert document["trust_decision"]
        assert document["knowledge_pattern"]["evidence_signature"]
        assert document["knowledge_pattern"]["resolution"]


class TestLearningSurvivesAWriteBackFailure:
    """DataHub refusing a write must not erase what the organisation learned.

    Recording the pattern only on a successful write-back meant that a token
    without tag-write permission silently disabled the entire learning loop: the
    incident resolved, the pattern library stayed empty, and nothing said why.
    """

    async def test_the_pattern_is_recorded_even_when_datahub_refuses(
        self, session, provider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from typing import Any

        from app.services.datahub.base import ToolResult

        async def refused(*args: Any, **kwargs: Any) -> ToolResult:
            return ToolResult(
                tool="write_incident_memory",
                success=False,
                data={},
                source="datahub",
                source_mode=provider.source_mode,
                error="Unauthorized to modify tags",
            )

        monkeypatch.setattr(provider, "write_incident_memory", refused)
        output = await run_scenario(session, "revenue-collapse")

        assert output["verification"]["status"] == "PASS"
        patterns = await PatternLibrary(session).all()
        assert [row.pattern for row in patterns] == ["SCHEMA_DRIFT"]
        assert patterns[0].occurrences == 1
        assert patterns[0].occurrences_log[0]["written_to_datahub"] is False

    async def test_the_next_incident_still_recognises_it(
        self, session, provider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from typing import Any

        from app.services.datahub.base import ToolResult

        async def refused(*args: Any, **kwargs: Any) -> ToolResult:
            return ToolResult(
                tool="write_incident_memory",
                success=False,
                data={},
                source="datahub",
                source_mode=provider.source_mode,
                error="Unauthorized to modify tags",
            )

        monkeypatch.setattr(provider, "write_incident_memory", refused)
        await run_scenario(session, "revenue-collapse")
        second = await run_scenario(session, "revenue-collapse")

        assert second["learning"]["matched_pattern"] == "SCHEMA_DRIFT"
        assert "known_pattern_detected" in event_names(second)

    async def test_the_status_does_not_claim_datahub_was_enriched(
        self, session, provider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from typing import Any

        from app.models.tables import MemoryReference
        from app.services.datahub.base import ToolResult

        async def refused(*args: Any, **kwargs: Any) -> ToolResult:
            return ToolResult(
                tool="write_incident_memory",
                success=False,
                data={},
                source="datahub",
                source_mode=provider.source_mode,
                error="Unauthorized to modify tags",
            )

        monkeypatch.setattr(provider, "write_incident_memory", refused)
        output = await run_scenario(session, "revenue-collapse")

        from sqlalchemy import select

        rows = (await session.execute(select(MemoryReference))).scalars().all()
        assert [row.write_back_status for row in rows] == ["LOCAL_ONLY"]
        assert rows[0].datahub_reference == ""
        assert "memory_write_failed" in event_names(output)


class TestDisplayAndPrecedentHygiene:
    """Small defects, all visible on the deployed instance."""

    def test_urn_display_names_cover_every_entity_shape(self) -> None:
        from app.core.utils import urn_name

        assert (
            urn_name("urn:li:dataset:(urn:li:dataPlatform:snowflake,A.B.SALES_DAILY,PROD)")
            == "SALES_DAILY"
        )
        # These two rendered as "PROD)" and "looker,taxi_operations".
        assert (
            urn_name("urn:li:dataJob:(urn:li:dataFlow:(dbt,flow,PROD),orders_enriched)")
            == "orders_enriched"
        )
        assert urn_name("urn:li:dashboard:(looker,taxi_operations)") == "taxi_operations"
        assert urn_name("urn:li:corpGroup:analytics-engineering") == "analytics-engineering"

    async def test_a_coincidental_precedent_is_not_offered(self, session) -> None:
        """A 1% overlap was arriving as evidence and costing trust points."""
        await run_scenario(session, "pipeline-freshness")
        output = await run_scenario(session, "healthcare-quality")

        historical = [e for e in output["evidence"] if e["type"] == "HISTORICAL_INCIDENT"]
        assert historical == [], "an unrelated past incident must not become evidence"
        assert output["root_cause"]["pattern"] == "SOURCE_DATA_ANOMALY"

    def test_the_rationale_does_not_claim_more_than_the_checks_show(self) -> None:
        from app.domain.trust import TrustCheck, TrustCheckStatus, TrustScore

        partial = TrustScore(
            checks=[
                TrustCheck("evidence_quality", TrustCheckStatus.PASS, 30, 30, ""),
                TrustCheck("lineage_coverage", TrustCheckStatus.PARTIAL, 8, 20, ""),
            ]
        )
        assert "Every grounding check passed" not in partial.rationale()
        assert "not complete" in partial.rationale()

    async def test_the_pattern_signature_excludes_symptom_and_precedent(
        self, session
    ) -> None:
        await run_scenario(session, "revenue-collapse")
        pattern = (await PatternLibrary(session).all())[0]
        assert "METRIC_CHANGE" not in pattern.evidence_signature
        assert "HISTORICAL_INCIDENT" not in pattern.evidence_signature
        assert pattern.evidence_signature, "the signature must not be empty either"
