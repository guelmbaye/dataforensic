"""What the agent does when things go wrong.

These are the tests that protect credibility: a demo that always succeeds proves
nothing. The agent must degrade honestly.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.domain.enums import IncidentStatus, InvestigationPhase, InvestigationStatus
from app.services.datahub.base import ToolResult
from tests.helpers import event_names, run_scenario


class TestEngineIsEvidenceDriven:
    async def test_removing_the_schema_change_collapses_schema_drift(
        self, session, provider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The conclusion follows the evidence, not the scenario name."""
        baseline = await run_scenario(session, "revenue-collapse")
        assert baseline["root_cause"]["pattern"] == "SCHEMA_DRIFT"

        async def no_changes(urn: str, since: Any = None, until: Any = None) -> ToolResult:
            return ToolResult(
                tool="find_changes",
                success=True,
                data={"urn": urn, "changes": []},
                source="test:no-changes",
                source_mode=provider.source_mode,
            )

        monkeypatch.setattr(provider, "find_changes", no_changes)
        blind = await run_scenario(session, "revenue-collapse")

        assert blind["root_cause"]["pattern"] != "SCHEMA_DRIFT" or blind["root_cause"][
            "confidence"
        ] < baseline["root_cause"]["confidence"]

    async def test_a_mapping_break_alone_still_explains_the_incident(
        self, session, provider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two independent signals point at drift; losing one must not lose both."""

        async def no_changes(urn: str, since: Any = None, until: Any = None) -> ToolResult:
            return ToolResult(
                tool="find_changes",
                success=True,
                data={"urn": urn, "changes": []},
                source="test:no-changes",
                source_mode=provider.source_mode,
            )

        monkeypatch.setattr(provider, "find_changes", no_changes)
        output = await run_scenario(session, "revenue-collapse")
        patterns = {h["pattern"] for h in output["hypotheses"]}
        assert "SCHEMA_DRIFT" in patterns


class TestDataHubUnavailable:
    async def test_investigation_is_blocked_not_invented(
        self, session, provider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DOCUMENT 08 - section 22: never fabricate a root cause without context."""

        async def unavailable(*args: Any, **kwargs: Any) -> ToolResult:
            return ToolResult(
                tool="get_asset_context",
                success=False,
                data={},
                source="datahub",
                source_mode=provider.source_mode,
                error="connection refused",
            )

        monkeypatch.setattr(provider, "get_asset_context", unavailable)
        output = await run_scenario(session, "revenue-collapse")

        assert output["status"] == str(InvestigationStatus.BLOCKED)
        assert output["phase"] == str(InvestigationPhase.BLOCKED)
        assert output["root_cause"]["pattern"] is None
        assert output["root_cause"]["summary"] is None
        assert output["_incident"].status == str(IncidentStatus.BLOCKED)
        assert "investigation_blocked" in event_names(output)
        assert output["blocked_reason"]

    async def test_lineage_failure_also_blocks(
        self, session, provider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def unavailable(*args: Any, **kwargs: Any) -> ToolResult:
            return ToolResult(
                tool="get_lineage",
                success=False,
                data={},
                source="datahub",
                source_mode=provider.source_mode,
                error="lineage service timeout",
            )

        monkeypatch.setattr(provider, "get_lineage", unavailable)
        output = await run_scenario(session, "revenue-collapse")
        assert output["status"] == str(InvestigationStatus.BLOCKED)
        assert output["blast_radius"] == {}


class TestVerificationFailure:
    async def test_a_failed_verification_never_resolves_the_incident(
        self, session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DOCUMENT 09 - section 13: FAIL verification != RESOLVED."""
        from app.services import scenario as scenario_module

        async def ineffective_remediation(self, scenario, step_ids):  # noqa: ANN001
            return {"scenario_id": scenario.id, "state": "BROKEN", "applied_steps": step_ids}

        monkeypatch.setattr(
            scenario_module.ScenarioRuntime, "apply_remediation", ineffective_remediation
        )
        output = await run_scenario(session, "revenue-collapse")

        assert output["verification"]["status"] != "PASS"
        assert output["_incident"].status != str(IncidentStatus.RESOLVED)
        assert output["memory"] is None, "nothing may be written back without a resolution"
        assert "resolution_failed" in event_names(output)
        assert "memory_written" not in event_names(output)

    async def test_the_root_cause_survives_a_failed_verification(
        self, session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.services import scenario as scenario_module

        async def ineffective_remediation(self, scenario, step_ids):  # noqa: ANN001
            return {"scenario_id": scenario.id, "state": "BROKEN", "applied_steps": step_ids}

        monkeypatch.setattr(
            scenario_module.ScenarioRuntime, "apply_remediation", ineffective_remediation
        )
        output = await run_scenario(session, "revenue-collapse")
        assert output["root_cause"]["pattern"] == "SCHEMA_DRIFT"


class TestWriteBackFailure:
    async def test_a_failed_write_back_is_reported_not_hidden(
        self, session, provider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def failing_write(*args: Any, **kwargs: Any) -> ToolResult:
            return ToolResult(
                tool="write_incident_memory",
                success=False,
                data={},
                source="datahub",
                source_mode=provider.source_mode,
                error="write rejected",
            )

        monkeypatch.setattr(provider, "write_incident_memory", failing_write)
        output = await run_scenario(session, "revenue-collapse")

        assert output["verification"]["status"] == "PASS"
        assert output["_incident"].status == str(IncidentStatus.RESOLVED)
        assert "memory_write_failed" in event_names(output)
        assert "memory_written" not in event_names(output)
        assert output["phase"] != str(InvestigationPhase.MEMORY_WRITTEN)


class TestTransportErrorsBlockRatherThanCrash:
    """A real network failure must reach the same place as a refused tool call.

    The other DataHub-unavailable tests stub the provider to *return* a failed
    ToolResult. Production instead raises `httpx.ConnectError` from deep inside
    the GraphQL client, and that path walked straight past the guard: the
    investigation ended FAILED with a raw traceback instead of BLOCKED with a
    reason a human can act on.
    """

    def _provider(self):
        from app.services.datahub.live import LiveDataHubProvider

        return LiveDataHubProvider(
            datahub_url="http://datahub-gms:8080",
            token="t",
            mcp_url="http://dataforensic-mcp:8000/mcp",
        )

    async def test_a_dns_failure_becomes_a_failed_tool_result(self) -> None:
        import httpx

        provider = self._provider()

        async def unresolvable(*args, **kwargs):
            raise httpx.ConnectError("[Errno -3] Temporary failure in name resolution")

        provider.gql.execute = unresolvable  # type: ignore[method-assign]
        provider.mcp = None

        result = await provider.get_asset_context("urn:li:dataset:(x,y,PROD)")
        assert result.success is False
        assert "datahub-gms" in result.error, "the failing host must be named"
        assert "name resolution" in result.error
        assert "network" in result.error.lower()

    async def test_a_timeout_names_the_budget(self) -> None:
        import httpx

        provider = self._provider()

        async def slow(*args, **kwargs):
            raise httpx.ReadTimeout("timed out")

        provider.gql.execute = slow  # type: ignore[method-assign]
        provider.mcp = None

        result = await provider.get_lineage("urn:li:dataset:(x,y,PROD)")
        assert result.success is False
        assert "did not answer within" in result.error

    async def test_the_investigation_is_blocked_not_failed(
        self, session, provider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import httpx

        async def unresolvable(*args: Any, **kwargs: Any):
            raise httpx.ConnectError("[Errno -3] Temporary failure in name resolution")

        monkeypatch.setattr(provider, "get_asset_context", unresolvable)
        output = await run_scenario(session, "revenue-collapse")

        assert output["status"] == str(InvestigationStatus.BLOCKED)
        assert output["root_cause"]["pattern"] is None
        assert "investigation_blocked" in event_names(output)
