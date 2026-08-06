"""Verification engine (DOCUMENT 04 - section 14).

Verification re-reads the world *after* the remediation. It is independent from
the remediation itself: if nothing was actually fixed, the checks fail and the
incident cannot become RESOLVED.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.utils import utcnow
from app.domain.enums import VerificationStatus
from app.domain.resolution import CheckResult, VerificationOutcome, can_resolve
from app.models.tables import Investigation, Verification
from app.services.datahub.base import DataHubProvider
from app.services.scenario import ScenarioDefinition, ScenarioRuntime


class VerificationService:
    def __init__(self, session: AsyncSession, provider: DataHubProvider) -> None:
        self.session = session
        self.provider = provider
        self.runtime = ScenarioRuntime(session)

    async def run(
        self,
        investigation: Investigation,
        asset_urn: str,
        scenario: ScenarioDefinition | None,
        expected_value: str | None = None,
    ) -> tuple[Verification, VerificationOutcome]:
        checks: list[CheckResult] = []

        if scenario:
            checks.extend(await self.runtime.run_checks(scenario))

        checks.append(await self._asset_still_readable(asset_urn))
        quality_check = await self._quality_signals_healthy(asset_urn)
        if quality_check:
            checks.append(quality_check)

        outcome = VerificationOutcome(checks=checks)
        expected: dict[str, Any] = {"expected_value": expected_value}
        actual: dict[str, Any] = {}
        if scenario:
            state = await self.runtime.get_state(scenario)
            actual["scenario_state"] = state
            actual["metrics"] = await self.runtime.metrics(scenario)
            actual["quality"] = await self.runtime.quality(scenario)

        record = Verification(
            investigation_id=investigation.id,
            status=str(outcome.status),
            checks=[c.to_public() for c in outcome.checks],
            expected_result=expected,
            actual_result=actual,
            verified_at=utcnow(),
        )
        self.session.add(record)
        await self.session.flush()
        return record, outcome

    async def _asset_still_readable(self, asset_urn: str) -> CheckResult:
        result = await self.provider.get_asset_context(asset_urn)
        return CheckResult(
            name="target_asset_context_available",
            status=VerificationStatus.PASS if result.success else VerificationStatus.FAIL,
            critical=True,
            expected="Asset context readable from DataHub",
            actual=result.source if result.success else (result.error or "unavailable"),
            detail="The verification must be able to re-read the asset it claims to have fixed.",
            asset_urn=asset_urn,
        )

    async def _quality_signals_healthy(self, asset_urn: str) -> CheckResult | None:
        result = await self.provider.get_quality_context(asset_urn)
        if not result.success:
            return CheckResult(
                name="quality_context_available",
                status=VerificationStatus.FAIL,
                critical=False,
                expected="Quality context readable",
                actual=result.error or "unavailable",
                asset_urn=asset_urn,
            )
        assertions = result.data.get("assertions", [])
        if not assertions:
            return None
        failing = [
            a
            for a in assertions
            if str(a.get("status", "")).upper() in {"FAIL", "FAILURE", "ERROR"}
        ]
        return CheckResult(
            name="datahub_assertions_passing",
            status=VerificationStatus.PASS if not failing else VerificationStatus.FAIL,
            critical=False,
            expected=f"0 failing assertions out of {len(assertions)}",
            actual=f"{len(failing)} failing",
            detail="DataHub assertion status for the target asset.",
            asset_urn=asset_urn,
        )

    @staticmethod
    def resolves(outcome: VerificationOutcome) -> bool:
        return can_resolve(outcome)
