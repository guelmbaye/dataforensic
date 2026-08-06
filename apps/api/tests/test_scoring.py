"""Confidence scoring (DOCUMENT 04 - section 8)."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.agents.scoring import classify, score_hypothesis
from app.domain.enums import EvidenceType, HypothesisStatus, Relevance
from app.domain.evidence import EvidenceItem
from app.domain.hypothesis import HypothesisCandidate

INCIDENT_TIME = datetime.fromisoformat("2026-03-11T10:20:00+00:00")


def ev(
    kind: EvidenceType,
    relevance: Relevance = Relevance.HIGH,
    minutes_before: int = 10,
    distance: int | None = 1,
) -> EvidenceItem:
    return EvidenceItem(
        type=kind,
        observation="signal",
        source="test",
        relevance=relevance,
        observed_at=INCIDENT_TIME - timedelta(minutes=minutes_before),
        lineage_distance=distance,
        asset_urn="urn:li:dataset:(urn:li:dataPlatform:snowflake,a,PROD)",
    )


def candidate(supporting, contradicting=None) -> HypothesisCandidate:
    return HypothesisCandidate(
        pattern="TEST",
        description="test",
        supporting=supporting,
        contradicting=contradicting or [],
    )


class TestScoreComponents:
    def test_strong_corroborated_evidence_reaches_high_confidence(self) -> None:
        score, breakdown = score_hypothesis(
            candidate(
                [
                    ev(EvidenceType.METRIC_CHANGE, distance=0),
                    ev(EvidenceType.SCHEMA_CHANGE, distance=3),
                    ev(EvidenceType.QUALITY_ANOMALY, distance=0),
                    ev(EvidenceType.PIPELINE_CHANGE, distance=1),
                    ev(EvidenceType.LINEAGE_DEPENDENCY, distance=1),
                ]
            ),
            INCIDENT_TIME,
        )
        assert score >= 85
        assert set(breakdown) == {
            "evidence_strength",
            "lineage_relevance",
            "temporal_correlation",
            "cross_signal_agreement",
            "contradicting_evidence",
            "total",
        }
        assert breakdown["total"] == score

    def test_the_symptom_alone_cannot_confirm_anything(self) -> None:
        """A metric moving is what we are explaining, not an explanation."""
        score, breakdown = score_hypothesis(
            candidate([ev(EvidenceType.METRIC_CHANGE, distance=0)]), INCIDENT_TIME
        )
        assert breakdown["cross_signal_agreement"] == 0
        assert score < 30

    def test_contradicting_evidence_lowers_the_score(self) -> None:
        supporting = [
            ev(EvidenceType.METRIC_CHANGE, distance=0),
            ev(EvidenceType.QUALITY_ANOMALY),
            ev(EvidenceType.PIPELINE_CHANGE),
        ]
        clean, _ = score_hypothesis(candidate(supporting), INCIDENT_TIME)
        contradicted, breakdown = score_hypothesis(
            candidate(supporting, [ev(EvidenceType.PIPELINE_CHANGE), ev(EvidenceType.QUALITY_ANOMALY)]),
            INCIDENT_TIME,
        )
        assert contradicted < clean
        # The breakdown is displayed as a sum in the UI, so the penalty is stored
        # signed rather than as an absolute value.
        assert breakdown["contradicting_evidence"] < 0

    def test_a_cause_after_the_incident_scores_lower_than_one_before(self) -> None:
        before = candidate(
            [ev(EvidenceType.METRIC_CHANGE, distance=0), ev(EvidenceType.SCHEMA_CHANGE, minutes_before=18)]
        )
        after = candidate(
            [ev(EvidenceType.METRIC_CHANGE, distance=0), ev(EvidenceType.SCHEMA_CHANGE, minutes_before=-90)]
        )
        score_before, _ = score_hypothesis(before, INCIDENT_TIME)
        score_after, _ = score_hypothesis(after, INCIDENT_TIME)
        assert score_before > score_after

    def test_a_distant_cause_scores_lower_than_a_close_one(self) -> None:
        close = candidate([ev(EvidenceType.SCHEMA_CHANGE, distance=0)])
        far = candidate([ev(EvidenceType.SCHEMA_CHANGE, distance=6)])
        assert score_hypothesis(close, INCIDENT_TIME)[0] > score_hypothesis(far, INCIDENT_TIME)[0]


class TestClassification:
    def test_confirmation_requires_more_than_a_high_score(self) -> None:
        """One loud signal is not corroboration."""
        single_type = candidate(
            [
                ev(EvidenceType.SCHEMA_CHANGE, distance=0),
                ev(EvidenceType.SCHEMA_CHANGE, distance=0),
                ev(EvidenceType.SCHEMA_CHANGE, distance=0),
            ]
        )
        assert classify(single_type, 95.0) is not HypothesisStatus.CONFIRMED

    def test_corroborated_signals_can_be_confirmed(self) -> None:
        corroborated = candidate(
            [
                ev(EvidenceType.SCHEMA_CHANGE, distance=0),
                ev(EvidenceType.QUALITY_ANOMALY, distance=0),
                ev(EvidenceType.PIPELINE_CHANGE, distance=1),
            ]
        )
        assert classify(corroborated, 95.0) is HypothesisStatus.CONFIRMED

    def test_low_scores_are_rejected(self) -> None:
        weak = candidate([ev(EvidenceType.METRIC_CHANGE, relevance=Relevance.LOW)])
        assert classify(weak, 5.0) is HypothesisStatus.REJECTED
