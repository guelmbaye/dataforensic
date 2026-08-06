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
