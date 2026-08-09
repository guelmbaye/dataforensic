"""DataHub integration surface (fixture provider + provenance contract)."""

from __future__ import annotations

import pytest

from app.domain.enums import SourceMode

SALES = "urn:li:dataset:(urn:li:dataPlatform:snowflake,ECOMMERCE.ANALYTICS.SALES_DAILY,PROD)"
ERP = "urn:li:dataset:(urn:li:dataPlatform:postgres,erp.public.orders,PROD)"
ENRICHED = "urn:li:dataset:(urn:li:dataPlatform:snowflake,ECOMMERCE.ANALYTICS.ORDERS_ENRICHED,PROD)"


class TestProvenance:
    async def test_every_result_declares_where_it_came_from(self, provider) -> None:
        """DOCUMENT 03 - section 14: the fallback never claims to be live DataHub."""
        result = await provider.get_asset_context(SALES)
        assert result.success
        assert result.source_mode is SourceMode.DEMO_FIXTURE
        assert result.source
        assert "datahub-live" not in result.source

    async def test_a_missing_asset_fails_explicitly(self, provider) -> None:
        """DOCUMENT 09 - section 5: no silent empty result."""
        result = await provider.get_asset_context("urn:li:dataset:(urn:li:dataPlatform:x,nope,PROD)")
        assert result.success is False
        assert result.error
        assert result.data in ({}, None)


class TestContextRetrieval:
    async def test_schema_is_returned_with_fields(self, provider) -> None:
        result = await provider.get_schema(SALES)
        assert result.success
        paths = {field["path"] for field in result.data["fields"]}
        assert {"net_revenue", "sales_date"} <= paths

    async def test_lineage_traverses_both_directions(self, provider) -> None:
        result = await provider.get_lineage(SALES, "BOTH", 4)
        assert result.success
        directions = {node["direction"] for node in result.data["nodes"]}
        assert {"UPSTREAM", "DOWNSTREAM", "SELF"} <= directions
        urns = {node["urn"] for node in result.data["nodes"]}
        assert ERP in urns, "the ERP source must be reachable within 4 hops"

    async def test_lineage_depth_is_honoured(self, provider) -> None:
        shallow = await provider.get_lineage(SALES, "UPSTREAM", 1)
        deep = await provider.get_lineage(SALES, "UPSTREAM", 4)
        assert len(shallow.data["nodes"]) < len(deep.data["nodes"])

    async def test_ownership_is_available(self, provider) -> None:
        result = await provider.get_ownership(SALES)
        assert result.success
        assert result.data["owners"]

    async def test_changes_are_filtered_by_time_window(self, provider) -> None:
        inside = await provider.find_changes(ERP, "2026-03-11T00:00:00Z", "2026-03-11T12:00:00Z")
        outside = await provider.find_changes(ERP, "2026-03-12T00:00:00Z", "2026-03-13T00:00:00Z")
        assert any(c["type"] == "SCHEMA_CHANGE" for c in inside.data["changes"])
        assert outside.data["changes"] == []

    async def test_time_window_accepts_iso_strings(self, provider) -> None:
        """Tool arguments arrive as JSON, so strings must not break the provider."""
        result = await provider.find_changes(ERP, "2026-03-10T00:00:00Z")
        assert result.success


class TestWriteBack:
    async def test_memory_is_written_and_readable_again(self, provider) -> None:
        document = {
            "schema_version": 1,
            "incident_id": "test-incident",
            "pattern": "SCHEMA_DRIFT",
            "root_cause": "Broken discount mapping",
            "symptom": "Revenue dropped",
            "confidence": 0.97,
            "asset_urn": SALES,
            "affected_assets": [ENRICHED],
        }
        write = await provider.write_incident_memory(document, [ENRICHED])
        assert write.success
        reference = write.data["reference"]

        read = await provider.read_incident_memory(reference)
        assert read.success
        assert read.data["document"]["pattern"] == "SCHEMA_DRIFT"

        found = await provider.search_incident_memory(asset_urn=SALES)
        assert any(item["document"]["incident_id"] == "test-incident" for item in found.data["matches"])

    async def test_write_back_is_reflected_on_the_asset(self, provider) -> None:
        await provider.write_incident_memory(
            {
                "schema_version": 1,
                "incident_id": "test-incident-2",
                "pattern": "SCHEMA_DRIFT",
                "root_cause": "x",
                "confidence": 0.9,
                "asset_urn": SALES,
                "affected_assets": [],
            },
            [],
        )
        context = await provider.get_asset_context(SALES)
        blob = str(context.data)
        assert "DataForensic" in blob or "institutional_memory" in blob


class TestMcpResponseFraming:
    """The MCP reply has to be found whatever the gateway's framing.

    The first version took the first `data:` line it saw. Against a gateway that
    announces itself first, or splits one payload across several `data:` lines,
    it reported "No JSON-RPC payload found" without ever saying what had
    arrived — leaving a live deployment with zero tools and no way to tell why.
    """

    def test_a_payload_split_across_several_data_lines(self) -> None:
        from app.services.datahub.mcp_client import MCPClient

        body = 'event: message\ndata: {"jsonrpc": "2.0", "id": 1,\ndata:  "result": {"tools": []}}\n\n'
        assert MCPClient._parse_sse(body)["result"] == {"tools": []}

    def test_a_preamble_event_is_skipped(self) -> None:
        from app.services.datahub.mcp_client import MCPClient

        body = (
            ": keep-alive\n\n"
            'event: endpoint\ndata: {"url": "/messages"}\n\n'
            'event: message\ndata: {"jsonrpc": "2.0", "id": 1, "result": {"ok": true}}\n\n'
        )
        assert MCPClient._parse_sse(body)["result"] == {"ok": True}

    def test_an_empty_body_says_what_that_means(self) -> None:
        import pytest as _pytest

        from app.services.datahub.mcp_client import MCPClient, MCPError

        with _pytest.raises(MCPError, match="empty body"):
            MCPClient._parse_sse("", "text/event-stream", 202)

    def test_an_unrecognised_body_is_quoted_back(self) -> None:
        import pytest as _pytest

        from app.services.datahub.mcp_client import MCPClient, MCPError

        with _pytest.raises(MCPError, match="ping"):
            MCPClient._parse_sse("event: ping\ndata: nope\n\n", "text/event-stream", 200)

    def test_a_payload_split_mid_token_is_still_read(self) -> None:
        """Not spec-compliant, but gateways do it — and the spec's newline join
        turns such a payload into invalid JSON."""
        from app.services.datahub.mcp_client import MCPClient

        body = (
            'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"protocolV\n'
            'data: ersion":"2025-06-18"}}\n\n'
        )
        assert MCPClient._parse_sse(body)["result"]["protocolVersion"] == "2025-06-18"

    def test_a_streamed_reply_is_routed_to_its_waiter(self) -> None:
        """The shape supergateway uses: the POST answers empty and the reply
        arrives on the separately opened stream."""
        import asyncio

        from app.services.datahub.mcp_client import MCPClient

        async def scenario() -> dict:
            client = MCPClient("http://localhost:1/mcp", token=None, timeout=1)
            waiter = asyncio.get_running_loop().create_future()
            client._pending[7] = waiter
            client._dispatch('event: message\ndata: {"jsonrpc":"2.0","id":7,"result":{"ok":1}}')
            return await asyncio.wait_for(waiter, timeout=1)

        assert asyncio.run(scenario())["result"] == {"ok": 1}
