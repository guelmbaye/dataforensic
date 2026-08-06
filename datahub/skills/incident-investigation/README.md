# DataHub Skill — Incident Investigation

Every agent investigating a data incident starts the same way: find the asset,
read its schema, walk lineage both ways, find who owns what, pull quality
signals, and look at what changed recently. That preparation is identical
whether the agent then concludes schema drift, a stale pipeline or a bad source
batch — and it is the part everyone rewrites.

This skill packages that preparation, and nothing else.

## What it deliberately does not do

- It does not decide a root cause. Scoring and hypothesis logic stay in the agent.
- It does not write to DataHub. `prepare_incident_writeback` validates and
  normalises a document; performing the write stays with the caller, so the
  permission boundary stays where the caller controls it.
- It contains no scenario, dataset or company specific logic.

## Usage

```python
from incident_investigation import IncidentInvestigationSkill

skill = IncidentInvestigationSkill(datahub_client)

context = await skill.collect_incident_context(
    asset_urn="urn:li:dataset:(urn:li:dataPlatform:snowflake,ANALYTICS.SALES_DAILY,PROD)",
    incident_time="2026-03-11T10:20:00Z",
    depth=4,
)

for path in context["upstream_paths"]:
    print(path["distance"], path["urn"])

impact = await skill.summarise_downstream_impact(asset_urn, depth=4)
print(impact["counts"], impact["owners"])

document = skill.prepare_incident_writeback({
    "incident_id": "...",
    "asset_urn": asset_urn,
    "pattern": "SCHEMA_DRIFT",
    "root_cause": "Broken discount mapping after an upstream rename",
    "confidence": 0.97,
    "evidence": [...],
    "affected_assets": [...],
})
```

`datahub_client` is any object exposing the DataHub read methods listed in
`skill.yaml`. The DataHub MCP server satisfies this contract; so does the
provider in `apps/api/app/services/datahub/`.

## Tests

```bash
python3 -m pytest datahub/skills/incident-investigation/
```

The tests run against an in-memory fake client, so the skill can be validated
without a DataHub instance.

## Packaging note

The layout here follows this repository's conventions. Adapting it to the
upstream DataHub Skills repository format is a packaging change, not a rewrite:
the skill has no dependency on DATAFORENSIC AI.

Licensed under Apache 2.0.
