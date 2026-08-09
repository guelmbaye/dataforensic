"""Golden path over HTTP: exactly what a judge exercises (DOCUMENT 09 - section 28)."""

from __future__ import annotations

import asyncio
import json

from app.services.investigation import wait_for
from tests.helpers import expected_truth

SALES = "urn:li:dataset:(urn:li:dataPlatform:snowflake,ECOMMERCE.ANALYTICS.SALES_DAILY,PROD)"


async def _create_and_investigate(client) -> tuple[str, str]:
    await client.post("/api/v1/scenarios/revenue-collapse/reset")
    created = await client.post(
        "/api/v1/incidents",
        json={
            "title": "Revenue anomaly",
            "description": "Revenue dropped by 18.5%",
            "asset_urn": SALES,
            "severity": "HIGH",
            "observed_value": "$10.1M",
            "expected_value": "$12.4M",
            "detected_at": "2026-03-11T10:20:00Z",
        },
    )
    assert created.status_code == 201, created.text
    incident_id = created.json()["id"]

    started = await client.post(f"/api/v1/incidents/{incident_id}/investigate")
    assert started.status_code == 202, started.text
    investigation_id = started.json()["investigation_id"]
    await wait_for(investigation_id, timeout=120)
    return incident_id, investigation_id


class TestHealthAndMeta:
    async def test_health_reports_every_dependency(self, client) -> None:
        response = await client.get("/api/v1/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["database"] == "ok"
        assert body["datahub"]["mode"]
        assert body["llm"]["provider"] == "none"

    async def test_datahub_status_declares_the_mode_honestly(self, client) -> None:
        body = (await client.get("/api/v1/datahub/status")).json()
        assert body["source_mode"] in {"LIVE_DATAHUB", "DEMO_FIXTURE"}
        assert body["connected"] is True

    async def test_the_agent_tool_surface_is_explicit_and_typed(self, client) -> None:
        body = (await client.get("/api/v1/agent/tools")).json()
        names = {tool["name"] for tool in body["tools"]}
        assert {"get_lineage", "calculate_blast_radius", "write_incident_memory"} <= names
        for tool in body["tools"]:
            assert tool["input_schema"]["type"] == "object"
            assert tool["side_effects"] in {"NONE", "READ", "LOW_RISK_WRITE", "SIMULATED_WRITE"}


class TestGoldenPath:
    async def test_the_whole_loop_runs_over_http(self, client) -> None:
        truth = expected_truth("revenue-collapse")
        incident_id, investigation_id = await _create_and_investigate(client)

        investigation = (await client.get(f"/api/v1/investigations/{investigation_id}")).json()
        assert investigation["status"] == "COMPLETED"
        assert investigation["root_cause"]["pattern"] == truth["root_cause_pattern"]
        assert investigation["root_cause"]["confidence"] >= truth["minimum_confidence"]
        assert investigation["verification"]["status"] == truth["verification"]
        assert investigation["memory"]["datahub_reference"]

        incident = (await client.get(f"/api/v1/incidents/{incident_id}")).json()
        assert incident["status"] == "RESOLVED"
        assert incident["resolved_at"]

    async def test_evidence_and_hypotheses_are_queryable(self, client) -> None:
        _, investigation_id = await _create_and_investigate(client)

        evidence = (await client.get(f"/api/v1/investigations/{investigation_id}/evidence")).json()
        assert len(evidence) >= 5

        filtered = (
            await client.get(
                f"/api/v1/investigations/{investigation_id}/evidence",
                params={"type": "SCHEMA_CHANGE"},
            )
        ).json()
        assert filtered and all(item["type"] == "SCHEMA_CHANGE" for item in filtered)

        hypotheses = (
            await client.get(f"/api/v1/investigations/{investigation_id}/hypotheses")
        ).json()
        assert len(hypotheses) >= 2
        assert sum(1 for h in hypotheses if h["is_primary"]) == 1
        confidences = [h["confidence"] for h in hypotheses]
        assert confidences == sorted(confidences, reverse=True)

    async def test_memory_search_finds_the_previous_investigation(self, client) -> None:
        await _create_and_investigate(client)
        found = (
            await client.get("/api/v1/memory/search", params={"asset_urn": SALES})
        ).json()
        assert found["matches"], "a resolved incident must be findable afterwards"
        assert found["matches"][0]["pattern"] == "SCHEMA_DRIFT"

    async def test_a_second_similar_incident_reuses_the_memory(self, client) -> None:
        await _create_and_investigate(client)
        _, second_id = await _create_and_investigate(client)

        events = (await client.get(f"/api/v1/investigations/{second_id}")).json()
        assert events["status"] == "COMPLETED"

        evidence = (await client.get(f"/api/v1/investigations/{second_id}/evidence")).json()
        historical = [e for e in evidence if e["type"] == "HISTORICAL_INCIDENT"]
        assert historical, "the second investigation must recall the first one"


class TestStreaming:
    async def test_the_timeline_streams_and_replays(self, client) -> None:
        _, investigation_id = await _create_and_investigate(client)

        received: list[dict] = []
        async with client.stream(
            "GET", f"/api/v1/investigations/{investigation_id}/events"
        ) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    payload = json.loads(line[6:])
                    if "seq" in payload:
                        received.append(payload)

        names = [event["event"] for event in received]
        for expected in [
            "context_loaded",
            "lineage_loaded",
            "evidence_found",
            "hypothesis_created",
            "hypothesis_scored",
            "root_cause_identified",
            "blast_radius_calculated",
            "remediation_planned",
            "verification_completed",
            "memory_written",
            "investigation_completed",
        ]:
            assert expected in names, f"missing SSE event: {expected}"

        sequences = [event["seq"] for event in received]
        assert sequences == sorted(sequences)
        assert len(set(sequences)) == len(sequences), "events must not be duplicated"

    async def test_resuming_from_a_sequence_number_skips_replayed_events(self, client) -> None:
        _, investigation_id = await _create_and_investigate(client)
        response = await client.get(
            f"/api/v1/investigations/{investigation_id}/events",
            headers={"Last-Event-ID": "5"},
        )
        payloads = [
            json.loads(line[6:])
            for line in response.text.splitlines()
            if line.startswith("data: ") and "seq" in line
        ]
        assert payloads
        assert min(event["seq"] for event in payloads) == 6


class TestGuardrailsOverHttp:
    async def test_a_high_risk_action_cannot_be_executed_without_approval(self, client) -> None:
        from app.models.database import session_scope
        from app.models.tables import Action

        _, investigation_id = await _create_and_investigate(client)
        async with session_scope() as session:
            from sqlalchemy import select

            action = (
                (
                    await session.execute(
                        select(Action).where(Action.investigation_id == investigation_id)
                    )
                )
                .scalars()
                .first()
            )
            action.risk_level = "HIGH"
            action.requires_approval = True
            action.status = "PLANNED"
            action_id = action.id

        refused = await client.post(f"/api/v1/actions/{action_id}/execute", json={"approved": False})
        assert refused.status_code == 403
        assert refused.json()["error"]["code"] == "ACTION_NOT_ALLOWED"

        approved = await client.post(
            f"/api/v1/actions/{action_id}/execute",
            json={"approved": True, "approved_by": "on-call@example.com"},
        )
        assert approved.status_code == 200
        assert approved.json()["status"] == "EXECUTED"

    async def test_unknown_resources_use_the_common_error_contract(self, client) -> None:
        response = await client.get("/api/v1/investigations/does-not-exist")
        assert response.status_code == 404
        error = response.json()["error"]
        assert error["code"] == "NOT_FOUND"
        assert error["retryable"] is False

    async def test_an_invalid_urn_is_rejected(self, client) -> None:
        response = await client.post(
            "/api/v1/incidents",
            json={
                "title": "bad",
                "description": "bad",
                "asset_urn": "not-a-urn",
                "severity": "LOW",
            },
        )
        assert response.status_code == 422

    async def test_idempotency_key_replays_instead_of_duplicating(self, client) -> None:
        payload = {
            "title": "Idempotent incident",
            "description": "x",
            "asset_urn": SALES,
            "severity": "LOW",
        }
        headers = {"Idempotency-Key": "test-key-1"}
        first = await client.post("/api/v1/incidents", json=payload, headers=headers)
        second = await client.post("/api/v1/incidents", json=payload, headers=headers)
        assert first.json()["id"] == second.json()["id"]

    async def test_the_same_key_with_a_different_body_is_refused(self, client) -> None:
        headers = {"Idempotency-Key": "test-key-2"}
        base = {"title": "A", "description": "x", "asset_urn": SALES, "severity": "LOW"}
        await client.post("/api/v1/incidents", json=base, headers=headers)
        conflicting = await client.post(
            "/api/v1/incidents", json={**base, "title": "B"}, headers=headers
        )
        assert conflicting.status_code == 422


class TestDemoReset:
    async def test_reset_puts_the_environment_back_to_its_initial_state(self, client) -> None:
        await _create_and_investigate(client)
        before = (await client.get("/api/v1/incidents")).json()
        assert before["total"] >= 1

        reset = (await client.post("/api/v1/demo/reset")).json()
        assert "revenue-collapse" in reset["scenarios_reset"]
        assert reset["incident_memory_cleared"] is True

        after = (await client.get("/api/v1/incidents")).json()
        assert after["total"] == 0

        memory = (await client.get("/api/v1/memory/search", params={"asset_urn": SALES})).json()
        assert memory["matches"] == []

    async def test_the_golden_scenario_still_runs_after_a_reset(self, client) -> None:
        await client.post("/api/v1/demo/reset")
        _, investigation_id = await _create_and_investigate(client)
        investigation = (await client.get(f"/api/v1/investigations/{investigation_id}")).json()
        assert investigation["verification"]["status"] == "PASS"


class TestKnowledgeApi:
    async def test_the_library_is_empty_before_anything_is_resolved(self, client) -> None:
        body = (await client.get("/api/v1/patterns")).json()
        assert body["total"] == 0

    async def test_a_resolved_incident_publishes_a_pattern(self, client) -> None:
        await _create_and_investigate(client)
        body = (await client.get("/api/v1/patterns")).json()
        assert body["total"] == 1
        pattern = body["items"][0]
        assert pattern["pattern"] == "SCHEMA_DRIFT"
        assert pattern["verified_resolutions"] == 1
        assert pattern["resolution_steps"]
        assert pattern["evidence_signature"]

    async def test_a_pattern_can_be_fetched_and_matched(self, client) -> None:
        await _create_and_investigate(client)

        detail = (await client.get("/api/v1/patterns/SCHEMA_DRIFT")).json()
        assert detail["occurrences"] == 1
        assert detail["history"]

        matches = (
            await client.get(
                "/api/v1/patterns/match",
                params={"symptom": "Revenue anomaly", "asset_urn": SALES},
            )
        ).json()
        assert matches and matches[0]["pattern"] == "SCHEMA_DRIFT"

    async def test_an_unknown_pattern_is_a_404(self, client) -> None:
        response = await client.get("/api/v1/patterns/NOT_A_PATTERN")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"

    async def test_the_investigation_exposes_trust_and_learning(self, client) -> None:
        _, investigation_id = await _create_and_investigate(client)
        body = (await client.get(f"/api/v1/investigations/{investigation_id}")).json()

        assert body["trust"]["score"] > 0
        assert body["trust"]["decision"]
        assert len(body["trust"]["checks"]) == 5
        assert body["learning"]["tool_call_count"] > 0
        assert body["learning"]["duration_ms"] > 0

    async def test_reset_clears_what_the_system_learned(self, client) -> None:
        await _create_and_investigate(client)
        await client.post("/api/v1/demo/reset")
        assert (await client.get("/api/v1/patterns")).json()["total"] == 0


class TestStatusReportsCurrentTruth:
    """A startup snapshot is not a status.

    DataHub is a heavy stack that comes up after the API and can be restarted
    underneath it. Reporting whatever happened at boot left the deployment
    saying `provider: uninitialised` long after DataHub had recovered.
    """

    async def test_status_answers_even_when_datahub_is_unreachable(
        self, client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.core.errors import DataHubUnavailableError
        from app.services import datahub as datahub_module

        async def unreachable():
            raise DataHubUnavailableError("Cannot resolve 'datahub-gms'")

        monkeypatch.setattr(datahub_module.factory, "get_provider", unreachable)
        monkeypatch.setattr(datahub_module.factory, "_provider", None)

        response = await client.get("/api/v1/datahub/status")
        assert response.status_code == 200, "a status endpoint must not 503"
        body = response.json()
        assert body["connected"] is False
        assert body["mcp"]["ready"] is False
        assert "fixture provider" not in body["mcp"]["detail"].lower()

    async def test_health_stays_ok_while_datahub_is_down(
        self, client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.core.errors import DataHubUnavailableError
        from app.services import datahub as datahub_module

        async def unreachable():
            raise DataHubUnavailableError("Cannot resolve 'datahub-gms'")

        monkeypatch.setattr(datahub_module.factory, "get_provider", unreachable)
        monkeypatch.setattr(datahub_module.factory, "_provider", None)

        body = (await client.get("/api/v1/health")).json()
        # The API itself is healthy; only its context source is not.
        assert body["database"] == "ok"
        assert body["datahub"]["connected"] is False

    async def test_the_provider_is_rebuilt_once_datahub_returns(self, client) -> None:
        from app.services.datahub import factory, reset_provider

        await reset_provider()
        factory._last_attempt = 0.0

        body = (await client.get("/api/v1/datahub/status")).json()
        assert body["connected"] is True
        assert body["provider"] != "uninitialised"


class TestStreamFramesAreConsumableByABrowser:
    """EventSource has no wildcard listener.

    A frame carrying `event: <name>` is delivered only to a listener registered
    for that exact name — `onmessage` never sees it. Naming every frame after
    its event type made the entire timeline invisible in the browser while every
    server-side test passed, because the tests parse `data:` lines directly.
    """

    async def test_data_frames_carry_no_event_name(self, client) -> None:
        _, investigation_id = await _create_and_investigate(client)
        response = await client.get(f"/api/v1/investigations/{investigation_id}/events")
        lines = response.text.splitlines()

        named = [line for line in lines if line.startswith("event: ")]
        assert all(line == "event: stream_closed" for line in named), (
            "only control frames may be named; data frames must reach onmessage"
        )

    async def test_every_frame_still_identifies_its_event_in_the_payload(
        self, client
    ) -> None:
        _, investigation_id = await _create_and_investigate(client)
        response = await client.get(f"/api/v1/investigations/{investigation_id}/events")
        payloads = [
            json.loads(line[6:])
            for line in response.text.splitlines()
            if line.startswith("data: ") and '"seq"' in line
        ]
        assert payloads
        assert all(p.get("event") for p in payloads)
        assert any(p["event"] == "root_cause_identified" for p in payloads)


class TestRerunningAnInvestigation:
    """An investigation has to be restartable, or a stuck demo stays stuck."""

    async def test_a_resolved_incident_refuses_a_plain_rerun(self, client) -> None:
        incident_id, _ = await _create_and_investigate(client)
        response = await client.post(f"/api/v1/incidents/{incident_id}/investigate")
        assert response.status_code == 422
        assert "force" in response.json()["error"]["message"]

    async def test_force_starts_a_fresh_investigation(self, client) -> None:
        incident_id, first_id = await _create_and_investigate(client)

        started = await client.post(
            f"/api/v1/incidents/{incident_id}/investigate", params={"force": "true"}
        )
        assert started.status_code == 202
        second_id = started.json()["investigation_id"]
        assert second_id != first_id

        await wait_for(second_id, timeout=120)
        second = (await client.get(f"/api/v1/investigations/{second_id}")).json()
        assert second["status"] == "COMPLETED"
        # The world was reset, so the re-run faces the same broken state and
        # reaches the same verified conclusion rather than finding nothing.
        assert second["root_cause"]["pattern"] == "SCHEMA_DRIFT"
        assert second["verification"]["status"] == "PASS"

    async def test_an_abandoned_run_is_superseded_not_blocking(self, client) -> None:
        """What an API restart mid-investigation leaves behind."""
        from sqlalchemy import select

        from app.models.database import session_scope
        from app.models.tables import Incident, Investigation

        incident_id, first_id = await _create_and_investigate(client)
        # Model exactly what an API restart mid-investigation leaves behind:
        # an incident still under investigation, and a run marked RUNNING with
        # no process behind it.
        async with session_scope() as session:
            row = await session.get(Investigation, first_id)
            row.status = "RUNNING"
            row.completed_at = None
            incident = await session.get(Incident, incident_id)
            incident.status = "INVESTIGATING"
            incident.resolved_at = None

        started = await client.post(f"/api/v1/incidents/{incident_id}/investigate")
        assert started.status_code == 202
        assert started.json()["investigation_id"] != first_id

        async with session_scope() as session:
            abandoned = await session.get(Investigation, first_id)
            assert abandoned.status == "FAILED"
            assert "Abandoned" in (abandoned.error or "")

        async with session_scope() as session:
            rows = (
                (
                    await session.execute(
                        select(Investigation).where(Investigation.incident_id == incident_id)
                    )
                )
                .scalars()
                .all()
            )
            assert len(rows) == 2, "the history keeps both runs"


class TestResetSurvivesAnUnreachableDataHub:
    """Getting a broken environment back to a known state is exactly when the
    catalog is likely to be down. Depending on it here meant the reset raised,
    the transaction rolled back, and nothing was cleaned."""

    async def test_reset_still_purges_when_datahub_is_unreachable(
        self, client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.api import scenarios as scenarios_module
        from app.core.errors import DataHubUnavailableError

        await _create_and_investigate(client)
        assert (await client.get("/api/v1/incidents")).json()["total"] >= 1

        async def unreachable():
            raise DataHubUnavailableError("Cannot resolve 'datahub-gms'")

        monkeypatch.setattr(scenarios_module, "get_provider", unreachable)

        response = await client.post("/api/v1/demo/reset")
        assert response.status_code == 200
        body = response.json()
        assert body["rows_purged"] > 0
        assert body["incident_memory_cleared"] is False
        assert "datahub-gms" in body["datahub_error"]

        assert (await client.get("/api/v1/incidents")).json()["total"] == 0
        assert (await client.get("/api/v1/patterns")).json()["total"] == 0
