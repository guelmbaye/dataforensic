"""Blast radius is derived from the retrieved lineage, never hardcoded."""

from __future__ import annotations

from app.services.blast_radius import calculate_blast_radius

ORIGIN = "urn:li:dataset:(urn:li:dataPlatform:snowflake,ORIGIN,PROD)"


def node(urn, entity_type, distance, criticality="MEDIUM", tags=None, owners=None):
    return {
        "urn": urn,
        "name": urn.split(",")[1] if "," in urn else urn,
        "entity_type": entity_type,
        "direction": "DOWNSTREAM",
        "distance": distance,
        "criticality": criticality,
        "tags": tags or [],
        "owners": owners or [],
        "platform": "snowflake",
    }


def graph(nodes, edges=None):
    return {"direction": "DOWNSTREAM", "depth": 3, "nodes": nodes, "edges": edges or []}


class TestBlastRadius:
    def test_no_downstream_means_low_impact(self) -> None:
        result = calculate_blast_radius(graph([]), ORIGIN)
        assert result["total_affected_assets"] == 0
        assert result["risk_level"] == "LOW"
        assert "No downstream consumer" in result["risk_factors"][0]

    def test_assets_are_bucketed_by_entity_type(self) -> None:
        result = calculate_blast_radius(
            graph(
                [
                    node("urn:a", "DATASET", 1),
                    node("urn:b", "DASHBOARD", 2),
                    node("urn:c", "MLMODEL", 2),
                ]
            ),
            ORIGIN,
        )
        assert result["counts"]["datasets"] == 1
        assert result["counts"]["dashboards"] == 1
        assert result["counts"]["ml_assets"] == 1
        assert result["total_affected_assets"] == 3

    def test_consumers_are_the_terminal_nodes_of_the_impacted_subgraph(self) -> None:
        nodes = [
            node("urn:mid", "DATASET", 1),
            node("urn:leaf1", "DASHBOARD", 2),
            node("urn:leaf2", "DASHBOARD", 2),
        ]
        edges = [
            {"upstream": ORIGIN, "downstream": "urn:mid"},
            {"upstream": "urn:mid", "downstream": "urn:leaf1"},
            {"upstream": "urn:mid", "downstream": "urn:leaf2"},
        ]
        result = calculate_blast_radius(graph(nodes, edges), ORIGIN)
        assert result["total_affected_assets"] == 3
        assert result["consumers"] == 2

    def test_ml_and_critical_assets_raise_the_risk(self) -> None:
        low = calculate_blast_radius(graph([node("urn:a", "DATASET", 3)]), ORIGIN)
        high = calculate_blast_radius(
            graph(
                [
                    node("urn:a", "DATASET", 1, "CRITICAL", ["Tier1"]),
                    node("urn:b", "MLMODEL", 1, "HIGH"),
                    node("urn:c", "DASHBOARD", 1, "CRITICAL", ["Finance"]),
                ]
            ),
            ORIGIN,
        )
        assert high["risk_score"] > low["risk_score"]
        assert any("ML asset" in factor for factor in high["risk_factors"])

    def test_owners_are_deduplicated_across_assets(self) -> None:
        owner = {"urn": "urn:li:corpGroup:team", "name": "Team"}
        result = calculate_blast_radius(
            graph([node("urn:a", "DATASET", 1, owners=[owner]), node("urn:b", "DASHBOARD", 2, owners=[owner])]),
            ORIGIN,
        )
        assert result["owner_count"] == 1
        assert result["owners"][0]["assets"] == ["urn:a", "urn:b"]

    def test_upstream_nodes_are_never_counted_as_impact(self) -> None:
        nodes = [node("urn:a", "DATASET", 1)]
        nodes.append({**node("urn:up", "DATASET", 1), "direction": "UPSTREAM"})
        result = calculate_blast_radius(graph(nodes), ORIGIN)
        assert result["total_affected_assets"] == 1
