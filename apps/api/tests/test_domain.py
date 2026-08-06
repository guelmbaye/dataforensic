"""Domain invariants: the rules that must hold whatever the agent decides."""

from __future__ import annotations

import pytest

from app.core.errors import ActionNotAllowedError, InvalidStateTransitionError
from app.domain.action import RemediationPlan, RemediationStep, assert_executable, classify_risk
from app.domain.enums import (
    ActionType,
    ExecutionMode,
    IncidentStatus,
    InvestigationStatus,
    RiskLevel,
    VerificationStatus,
)
from app.domain.resolution import CheckResult, VerificationOutcome, can_resolve
from app.domain.state_machine import (
    assert_incident_transition,
    assert_investigation_transition,
)


class TestIncidentStateMachine:
    def test_nominal_path_is_allowed(self) -> None:
        assert_incident_transition(IncidentStatus.CREATED, IncidentStatus.INVESTIGATING)
        assert_incident_transition(IncidentStatus.INVESTIGATING, IncidentStatus.REMEDIATING)
        assert_incident_transition(IncidentStatus.REMEDIATING, IncidentStatus.VERIFYING)
        assert_incident_transition(IncidentStatus.VERIFYING, IncidentStatus.RESOLVED)

    @pytest.mark.parametrize(
        "start",
        [IncidentStatus.CREATED, IncidentStatus.INVESTIGATING, IncidentStatus.REMEDIATING],
    )
    def test_resolution_without_verification_is_structurally_impossible(self, start) -> None:
        """DOCUMENT 06 - section 25."""
        with pytest.raises(InvalidStateTransitionError):
            assert_incident_transition(start, IncidentStatus.RESOLVED)

    def test_investigation_cannot_leave_a_terminal_state(self) -> None:
        with pytest.raises(InvalidStateTransitionError):
            assert_investigation_transition(
                InvestigationStatus.COMPLETED, InvestigationStatus.RUNNING
            )


class TestActionPolicy:
    def test_destructive_wording_escalates_risk(self) -> None:
        assert classify_risk("Drop the affected partition") is RiskLevel.HIGH
        assert classify_risk("Restore field mapping") is RiskLevel.LOW

    def test_medium_risk_requires_approval(self) -> None:
        plan = RemediationPlan(
            diagnosis="x",
            steps=[RemediationStep(id="a", title="a", description="", risk=RiskLevel.MEDIUM)],
        )
        assert plan.risk is RiskLevel.MEDIUM
        assert plan.requires_approval is True

    def test_backend_blocks_unapproved_risky_action(self) -> None:
        """The agent asking nicely is never enough (DOCUMENT 09 - section 12)."""
        with pytest.raises(ActionNotAllowedError):
            assert_executable(
                ActionType.EXECUTE_SIMULATED,
                RiskLevel.HIGH,
                ExecutionMode.SIMULATED,
                approved=False,
            )

    def test_approval_unblocks_the_same_action(self) -> None:
        assert_executable(
            ActionType.EXECUTE_SIMULATED, RiskLevel.HIGH, ExecutionMode.SIMULATED, approved=True
        )

    def test_real_execution_is_disabled_by_configuration(self) -> None:
        with pytest.raises(ActionNotAllowedError):
            assert_executable(
                ActionType.EXECUTE_SIMULATED, RiskLevel.LOW, ExecutionMode.REAL, approved=True
            )


class TestVerificationOutcome:
    def _outcome(self, *results: CheckResult) -> VerificationOutcome:
        return VerificationOutcome(checks=list(results))

    def test_all_passing_is_pass(self) -> None:
        outcome = self._outcome(
            CheckResult(name="a", status=VerificationStatus.PASS),
            CheckResult(name="b", status=VerificationStatus.PASS),
        )
        assert outcome.status is VerificationStatus.PASS
        assert can_resolve(outcome) is True

    def test_a_failing_critical_check_fails_the_whole_verification(self) -> None:
        outcome = self._outcome(
            CheckResult(name="a", status=VerificationStatus.PASS),
            CheckResult(name="b", status=VerificationStatus.FAIL, critical=True),
        )
        assert outcome.status is VerificationStatus.FAIL
        assert can_resolve(outcome) is False

    def test_a_failing_non_critical_check_is_partial_and_blocks_resolution(self) -> None:
        outcome = self._outcome(
            CheckResult(name="a", status=VerificationStatus.PASS),
            CheckResult(name="b", status=VerificationStatus.FAIL, critical=False),
        )
        assert outcome.status is VerificationStatus.PARTIAL
        assert can_resolve(outcome) is False
