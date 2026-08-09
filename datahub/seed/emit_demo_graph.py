#!/usr/bin/env python3
"""Emit the demo context graph into a real DataHub instance.

Why this exists
---------------
The scenarios reference URNs like

    urn:li:dataset:(urn:li:dataPlatform:snowflake,ECOMMERCE.ANALYTICS.SALES_DAILY,PROD)

which mirror the *shape* of the official datapacks but are not the datapacks'
own URNs. Point the agent at a live DataHub that has never seen them and the
investigation degrades in a way that is easy to misread: DataHub answers, the
asset "loads", and then schema, lineage and blast radius all come back empty —
because writing a tag to an unknown URN is enough to create an entity row with
nothing in it.

Running this script makes `DATAHUB_MODE=live` mean what it claims: the agent
walks real lineage, reads real schemas, resolves real owners, and its write-back
lands on assets a judge can open in the DataHub UI.

Usage
-----
    pip install "acryl-datahub>=1.0"
    export DATAHUB_GMS_URL=http://localhost:8080
    export DATAHUB_GMS_TOKEN=<personal access token>
    python3 datahub/seed/emit_demo_graph.py

    # check before writing
    python3 datahub/seed/emit_demo_graph.py --dry-run

This is additive: it emits aspects for the demo URNs and touches nothing else.
The official datapacks can be loaded alongside it.

Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

GRAPH = Path(__file__).resolve().parent / "showcase-ecommerce-demo.json"

# Set before re-executing, so a broken interpreter cannot loop forever.
REEXEC_FLAG = "DATAFORENSIC_EMIT_REEXEC"


def _interpreters_with_sdk() -> list[Path]:
    """Interpreters that might already have the DataHub SDK.

    On Debian, `pip install` is refused (PEP 668) and the usual answer — pipx or
    uv — installs the CLI into an isolated environment. The SDK is then present
    on the machine and invisible to system Python, which reads as "not
    installed" while `datahub` works fine in the shell.
    """
    home = Path.home()
    candidates = [
        Path(os.environ.get("PIPX_HOME", home / ".local/share/pipx"))
        / "venvs/acryl-datahub/bin/python",
        home / ".local/pipx/venvs/acryl-datahub/bin/python",
        home / ".local/share/uv/tools/acryl-datahub/bin/python",
        Path.cwd() / ".venv/bin/python",
        Path.cwd() / "venv/bin/python",
    ]
    return [path for path in candidates if path.is_file()]


def _reexec_with_sdk() -> None:
    """Re-run this script with an interpreter that can import the SDK."""
    if os.environ.get(REEXEC_FLAG):
        return
    for interpreter in _interpreters_with_sdk():
        probe = subprocess.run(
            [
                str(interpreter),
                "-c",
                # Probe everything this script actually imports: a partial
                # install would otherwise pass the check and fail later with a
                # traceback instead of the guidance below.
                "import datahub.emitter.rest_emitter, datahub.emitter.mcp, "
                "datahub.metadata.schema_classes",
            ],
            capture_output=True,
        )
        if probe.returncode == 0:
            print(f"sdk        : found in {interpreter}, re-running with it")
            os.environ[REEXEC_FLAG] = "1"
            os.execv(str(interpreter), [str(interpreter), str(Path(__file__).resolve()), *sys.argv[1:]])
    return

TYPE_MAP = {
    "varchar": "string",
    "string": "string",
    "number": "number",
    "numeric": "number",
    "date": "date",
    "timestamp": "time",
    "boolean": "boolean",
}


def _load_graph() -> dict[str, Any]:
    if not GRAPH.exists():
        sys.exit(f"Graph not found: {GRAPH}\nRun `python3 datahub/seed/build_graph.py` first.")
    return json.loads(GRAPH.read_text(encoding="utf-8"))


def _field_type(raw: str):
    from datahub.metadata.schema_classes import (
        BooleanTypeClass,
        DateTypeClass,
        NumberTypeClass,
        SchemaFieldDataTypeClass,
        StringTypeClass,
        TimeTypeClass,
    )

    kind = TYPE_MAP.get(str(raw).lower(), "string")
    mapping = {
        "string": StringTypeClass(),
        "number": NumberTypeClass(),
        "date": DateTypeClass(),
        "time": TimeTypeClass(),
        "boolean": BooleanTypeClass(),
    }
    return SchemaFieldDataTypeClass(type=mapping[kind])


def build_mcps(graph: dict[str, Any]) -> list[Any]:
    """One flat list of aspect changes, so a dry run can simply count them."""
    from datahub.emitter.mcp import MetadataChangeProposalWrapper
    from datahub.metadata.schema_classes import (
        AuditStampClass,
        ChangeAuditStampsClass,
        DashboardInfoClass,
        DatasetLineageTypeClass,
        DatasetPropertiesClass,
        GlobalTagsClass,
        MLModelPropertiesClass,
        OtherSchemaClass,
        OwnerClass,
        OwnershipClass,
        OwnershipTypeClass,
        SchemaFieldClass,
        SchemaMetadataClass,
        TagAssociationClass,
        UpstreamClass,
        UpstreamLineageClass,
    )

    now = AuditStampClass(time=0, actor="urn:li:corpuser:datahub")
    mcps: list[tuple[str, Any]] = []

    for entity in graph["entities"]:
        urn = entity["urn"]
        kind = str(entity.get("type", "DATASET")).upper()
        is_dataset = kind == "DATASET"
        properties = {
            "criticality": str(entity.get("criticality", "MEDIUM")),
            "domain": str(entity.get("domain", "")),
            "seeded_by": "dataforensic-ai",
        }

        # Each entity type has its own properties aspect. Sending
        # `datasetProperties` to a dashboard is rejected outright:
        #   422 Unknown aspect datasetProperties for entity dashboard
        if is_dataset:
            aspect = DatasetPropertiesClass(
                name=entity.get("name"),
                description=entity.get("description", ""),
                customProperties=properties,
            )
        elif kind == "DASHBOARD":
            aspect = DashboardInfoClass(
                title=entity.get("name", urn),
                description=entity.get("description", ""),
                lastModified=ChangeAuditStampsClass(created=now, lastModified=now),
                customProperties=properties,
            )
        elif kind in {"MLMODEL", "MLMODELGROUP"}:
            aspect = MLModelPropertiesClass(
                description=entity.get("description", ""),
                customProperties=properties,
            )
        else:
            aspect = None

        if aspect is not None:
            mcps.append((f"{kind} properties {entity.get('name', urn)}",
                         MetadataChangeProposalWrapper(entityUrn=urn, aspect=aspect)))

        if entity.get("owners"):
            mcps.append((
                f"{kind} ownership {entity.get('name', urn)}",
                MetadataChangeProposalWrapper(
                    entityUrn=urn,
                    aspect=OwnershipClass(
                        owners=[
                            OwnerClass(
                                owner=owner["urn"],
                                # TECHNICAL_OWNER is the safest widely-supported
                                # value; the demo does not depend on the nuance.
                                type=OwnershipTypeClass.TECHNICAL_OWNER,
                            )
                            for owner in entity["owners"]
                        ]
                    ),
                ),
            ))

        if entity.get("tags"):
            mcps.append((
                f"{kind} tags {entity.get('name', urn)}",
                MetadataChangeProposalWrapper(
                    entityUrn=urn,
                    aspect=GlobalTagsClass(
                        tags=[
                            TagAssociationClass(tag=f"urn:li:tag:{tag}")
                            for tag in entity["tags"]
                        ]
                    ),
                ),
            ))

        fields = (entity.get("schema") or {}).get("fields") or []
        if is_dataset and fields:
            mcps.append((
                f"schema {entity.get('name', urn)}",
                MetadataChangeProposalWrapper(
                    entityUrn=urn,
                    aspect=SchemaMetadataClass(
                        schemaName=entity.get("name", urn),
                        platform=f"urn:li:dataPlatform:{entity.get('platform', 'snowflake')}",
                        version=0,
                        hash="",
                        platformSchema=OtherSchemaClass(rawSchema=""),
                        lastModified=now,
                        fields=[
                            SchemaFieldClass(
                                fieldPath=field["path"],
                                type=_field_type(field.get("type", "string")),
                                nativeDataType=str(field.get("type", "string")),
                                description=field.get("description", ""),
                                nullable=bool(field.get("nullable", True)),
                            )
                            for field in fields
                        ],
                    ),
                ),
            ))

    # Lineage is emitted per downstream asset: DataHub models it as the
    # downstream declaring its upstreams, so edges have to be grouped first.
    upstreams: dict[str, list[str]] = {}
    for edge in graph["lineage"]:
        upstreams.setdefault(edge["downstream"], []).append(edge["upstream"])

    for downstream, sources in upstreams.items():
        if ":dataset:" not in downstream:
            # Dashboards and ML models declare their inputs through different
            # aspects; the demo's reasoning only needs dataset-to-dataset edges
            # plus the consumer entities themselves.
            continue
        mcps.append((
            f"lineage into {downstream.split(',')[1] if ',' in downstream else downstream}",
            MetadataChangeProposalWrapper(
                entityUrn=downstream,
                aspect=UpstreamLineageClass(
                    upstreams=[
                        UpstreamClass(dataset=source, type=DatasetLineageTypeClass.TRANSFORMED)
                        for source in sources
                        if ":dataset:" in source
                    ]
                ),
            ),
        ))

    return mcps


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Count aspects, write nothing.")
    parser.add_argument(
        "--gms", default=os.environ.get("DATAHUB_GMS_URL", "http://localhost:8080")
    )
    parser.add_argument("--token", default=os.environ.get("DATAHUB_GMS_TOKEN", ""))
    args = parser.parse_args()

    graph = _load_graph()
    print(f"graph      : {len(graph['entities'])} entities, {len(graph['lineage'])} edges")

    try:
        from datahub.emitter.rest_emitter import DatahubRestEmitter
    except ImportError:
        _reexec_with_sdk()  # does not return if a usable interpreter is found
        message = (
            "The DataHub SDK is not importable from this interpreter "
            f"({sys.executable}).\n\n"
            "Debian refuses `pip install` system-wide (PEP 668), and pipx or uv\n"
            "install the CLI into an isolated environment this script cannot see.\n"
            "Either of these works:\n\n"
            "  python3 -m venv .venv-datahub\n"
            '  .venv-datahub/bin/pip install "acryl-datahub>=1.0"\n'
            "  .venv-datahub/bin/python datahub/seed/emit_demo_graph.py\n\n"
            "  # or, reusing an existing pipx install:\n"
            "  ~/.local/share/pipx/venvs/acryl-datahub/bin/python \\\n"
            "      datahub/seed/emit_demo_graph.py"
        )
        if args.dry_run:
            # Still useful without the SDK: the graph itself can be checked.
            print(f"aspects    : cannot be counted without the SDK\n{message}")
            return 0
        sys.exit(message)

    mcps = build_mcps(graph)
    print(f"aspects    : {len(mcps)} to emit")
    print(f"target     : {args.gms}")

    if args.dry_run:
        print("dry run    : nothing written")
        return 0

    if not args.token:
        print(
            "warning    : no DATAHUB_GMS_TOKEN set. This only works if metadata "
            "service authentication is disabled.",
            file=sys.stderr,
        )

    emitter = DatahubRestEmitter(gms_server=args.gms, token=args.token or None)
    emitter.test_connection()

    # One rejected aspect must not abandon the graph half-written. A partially
    # seeded DataHub is worse than a failed run: the assets exist, so nothing
    # looks broken, and the investigation quietly degrades instead.
    failures: list[tuple[str, str]] = []
    for index, (label, mcp) in enumerate(mcps, start=1):
        try:
            emitter.emit(mcp)
        except Exception as exc:  # noqa: BLE001 - reported, never fatal
            failures.append((label, str(exc)[:200]))
        if index % 25 == 0:
            print(f"  emitted {index}/{len(mcps)}")

    emitted = len(mcps) - len(failures)
    print(f"done       : {emitted}/{len(mcps)} aspects emitted")

    if failures:
        print(f"\nrefused    : {len(failures)} aspect(s)")
        for label, error in failures[:10]:
            print(f"  - {label}: {error}")
        if len(failures) > 10:
            print(f"  ... and {len(failures) - 10} more")
        print(
            "\nThe rest of the graph was written. Re-running this script is safe: "
            "aspects are upserted."
        )
        return 1

    print(
        "\nVerify in the UI, then run an investigation: lineage and blast radius\n"
        "should stop being empty, and the trust score should rise accordingly."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
