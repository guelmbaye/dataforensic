"""Remediation planning (DOCUMENT 04 - section 12).

The plan is derived from the confirmed root cause pattern and the evidence, and
is bound to the scenario's controlled simulation when one exists. The MVP never
performs destructive production actions.
"""

from __future__ import annotations

from typing import Any

from app.core.utils import urn_name
from app.domain.action import RemediationPlan, RemediationStep, classify_risk
from app.domain.enums import EvidenceType, ExecutionMode, RiskLevel
from app.domain.evidence import EvidenceItem
from app.services.scenario import ScenarioDefinition

GENERIC_TEMPLATES: dict[str, dict[str, Any]] = {
    "SCHEMA_DRIFT": {
        "diagnosis": "An upstream schema change broke a field mapping in the transformation chain.",
        "expected_result": "The affected field is populated again and the business metric recovers.",
        "rollback": "Re-apply the previous mapping version; no data is deleted at any point.",
        "steps": [
            ("restore_field_mapping", "Restore field mapping", "Point the transformation at the renamed upstream field.", RiskLevel.LOW),
            ("replay_affected_records", "Replay affected records", "Reprocess the records ingested since the schema change.", RiskLevel.LOW),
            ("recompute_metric", "Recompute the affected metric", "Recompute the downstream aggregate for the impacted window.", RiskLevel.LOW),
            ("validate_downstream", "Validate downstream assets", "Re-run quality checks on downstream consumers.", RiskLevel.LOW),
            ("notify_owners", "Notify owners", "Inform the owning teams of the change and of the fix.", RiskLevel.LOW),
        ],
    },
    "PIPELINE_FAILURE": {
        "diagnosis": "A pipeline execution failed or degraded, leaving downstream assets incomplete or stale.",
        "expected_result": "The pipeline completes successfully and freshness returns to its SLA.",
        "rollback": "Stop the backfill; the previous partition remains untouched.",
        "steps": [
            ("investigate_job_logs", "Inspect the failing job", "Review the last executions of the responsible pipeline.", RiskLevel.LOW),
            ("rerun_pipeline", "Re-run the pipeline stage", "Trigger the failed stage again for the affected window.", RiskLevel.LOW),
            ("backfill_window", "Backfill the missing window", "Reprocess the missing partitions.", RiskLevel.LOW),
            ("validate_downstream", "Validate downstream assets", "Confirm freshness and volume downstream.", RiskLevel.LOW),
            ("notify_owners", "Notify owners", "Inform the pipeline owners.", RiskLevel.LOW),
        ],
    },
    "SOURCE_DATA_ANOMALY": {
        "diagnosis": "The source system delivered anomalous data that propagated downstream.",
        "expected_result": "Source data is corrected or quarantined and downstream values return to their expected range.",
        "rollback": "Release the quarantine and restore the previous ingestion configuration.",
        "steps": [
            ("quarantine_batch", "Quarantine the anomalous batch", "Isolate the affected batch before it spreads further.", RiskLevel.MEDIUM),
            ("contact_source_owner", "Contact the source owner", "Confirm the anomaly with the upstream system owner.", RiskLevel.LOW),
            ("reingest_corrected_batch", "Re-ingest the corrected batch", "Ingest the corrected extract once available.", RiskLevel.LOW),
            ("validate_downstream", "Validate downstream assets", "Re-run quality checks downstream.", RiskLevel.LOW),
        ],
    },
    "FRESHNESS_STALENESS": {
        "diagnosis": "An upstream dataset stopped refreshing, so downstream consumers read stale data.",
        "expected_result": "Freshness returns within the SLA for the whole chain.",
        "rollback": "Not applicable: no data is modified, only refreshed.",
        "steps": [
            ("identify_stale_stage", "Identify the stale stage", "Find the first stage of the chain that stopped refreshing.", RiskLevel.LOW),
            ("trigger_refresh", "Trigger a refresh", "Re-run the ingestion for the stale stage.", RiskLevel.LOW),
            ("propagate_refresh", "Propagate downstream", "Refresh the downstream assets in lineage order.", RiskLevel.LOW),
            ("notify_owners", "Notify owners", "Inform the owners of the stale chain.", RiskLevel.LOW),
        ],
    },
    "TRANSFORMATION_LOGIC_CHANGE": {
        "diagnosis": "A transformation definition changed and altered downstream results.",
        "expected_result": "The transformation produces the expected values again.",
        "rollback": "Restore the previous transformation version.",
        "steps": [
            ("review_transformation_diff", "Review the transformation change", "Compare the current definition with the previous version.", RiskLevel.LOW),
            ("restore_previous_logic", "Restore the previous logic", "Revert the transformation to its last known good version.", RiskLevel.MEDIUM),
            ("recompute_metric", "Recompute the affected metric", "Recompute the impacted aggregates.", RiskLevel.LOW),
            ("validate_downstream", "Validate downstream assets", "Re-run downstream checks.", RiskLevel.LOW),
        ],
    },
}

FALLBACK_TEMPLATE: dict[str, Any] = {
    "diagnosis": "The investigation could not isolate a single dominant technical cause.",
    "expected_result": "A human owner confirms or rejects the leading hypothesis.",
    "rollback": "Not applicable: recommendation only.",
    "steps": [
        ("collect_additional_context", "Collect additional context", "Gather more signals around the affected asset.", RiskLevel.LOW),
        ("engage_owner", "Engage the asset owner", "Ask the owning team to confirm the leading hypothesis.", RiskLevel.LOW),
    ],
}


def _interpolate(text: str, evidence: list[EvidenceItem], asset_urn: str) -> str:
    schema_evidence = next(
        (e for e in evidence if e.type is EvidenceType.SCHEMA_CHANGE and e.field_path), None
    )
    quality_evidence = next(
        (e for e in evidence if e.type is EvidenceType.QUALITY_ANOMALY and e.field_path), None
    )
    field = (schema_evidence or quality_evidence).field_path if (schema_evidence or quality_evidence) else None
    replacements = {
        "{field}": field or "the affected field",
        "{asset}": urn_name(asset_urn),
    }
    for token, value in replacements.items():
        text = text.replace(token, value)
    return text


def build_remediation_plan(
    pattern: str | None,
    evidence: list[EvidenceItem],
    asset_urn: str,
    owners: list[dict[str, Any]] | None = None,
    scenario: ScenarioDefinition | None = None,
    allow_simulation: bool = True,
) -> RemediationPlan:
    template: dict[str, Any] | None = None
    if scenario and scenario.remediation_template:
        applies = scenario.remediation_template.get("applies_to_patterns")
        if not applies or (pattern and pattern in applies):
            template = scenario.remediation_template

    if template:
        steps = [
            RemediationStep(
                id=str(step["id"]),
                title=str(step["title"]),
                description=_interpolate(str(step.get("description", "")), evidence, asset_urn),
                risk=classify_risk(
                    f"{step.get('title', '')} {step.get('description', '')}",
                    RiskLevel(str(step.get("risk", "LOW")).upper()),
                ),
                effect=step.get("effect"),
            )
            for step in template.get("steps", [])
        ]
        plan = RemediationPlan(
            diagnosis=_interpolate(str(template.get("diagnosis", "")), evidence, asset_urn),
            steps=steps,
            expected_result=str(template.get("expected_result", "")),
            rollback=str(template.get("rollback", "")),
            execution_mode=ExecutionMode.SIMULATED if allow_simulation else ExecutionMode.REAL,
        )
    else:
        generic = GENERIC_TEMPLATES.get(pattern or "", FALLBACK_TEMPLATE)
        plan = RemediationPlan(
            diagnosis=_interpolate(str(generic["diagnosis"]), evidence, asset_urn),
            steps=[
                RemediationStep(
                    id=step_id,
                    title=title,
                    description=_interpolate(description, evidence, asset_urn),
                    risk=classify_risk(f"{title} {description}", risk),
                )
                for step_id, title, description, risk in generic["steps"]
            ],
            expected_result=str(generic["expected_result"]),
            rollback=str(generic["rollback"]),
            execution_mode=ExecutionMode.SIMULATED,
        )

    plan.notify_owners = [
        str(owner.get("name") or owner.get("urn"))
        for owner in (owners or [])
        if owner.get("name") or owner.get("urn")
    ]
    return plan
