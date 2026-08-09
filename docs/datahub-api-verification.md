# DataHub API surface — what is verified, and what is not

Every DataHub-specific claim this project makes was checked against the official
documentation on **6 August 2026** (DataHub Core **1.6.0**; a later deployment pulled **v1.7.0**). This file exists so
the next person does not have to redo the audit, and so the few unverified
corners are visible rather than buried in code.

## Verified against official documentation

| Claim | Where it is used | Source |
|---|---|---|
| MCP server package is `mcp-server-datahub`, run via `uvx`, env `DATAHUB_GMS_URL` / `DATAHUB_GMS_TOKEN` | deployment guide | docs.datahub.com — MCP Server feature guide |
| MCP read tools: `search`, `get_entities`, `list_schema_fields`, `get_lineage`, `get_lineage_paths_between`, `get_dataset_queries` | `live.py` `MCP_TOOL_CANDIDATES` | idem |
| MCP mutation tools exist from v0.5.0, gated by `TOOLS_IS_MUTATION_ENABLED` | `live.py` comment, deployment guide | idem |
| The self-hosted MCP server is **stdio**; Streamable HTTP is DataHub Cloud only | the whole bridge design | idem |
| Timeline API path `/openapi/v2/timeline/v1/<url-encoded-urn>` | `graphql.py::timeline` | Timeline API guide |
| Timeline parameters `categories`, `start`, `end` (epoch ms) | idem | idem |
| Timeline categories `TECHNICAL_SCHEMA`, `OWNERSHIP`, `TAG`, `DOCUMENTATION`, `GLOSSARY_TERM` | idem | idem |
| ChangeEvent fields `changeType`, `category`, `elementId`, `target`, `description`, `changeDetails`, `modificationCategory` | `live.py::find_changes` | idem |
| Timeline supports Datasets, Glossary Terms, Domains, Data Products | change collection is dataset-scoped | idem |
| GraphQL endpoint `POST /api/graphql`, `Authorization: Bearer <token>` | `graphql.py` | How To Set Up GraphQL |
| `createTag(input: {id, name, description})` returns the tag URN | write-back | Tags tutorial |
| `addTags(input: {tagUrns, resourceUrn})` | write-back | Tags tutorial |
| `searchAcrossEntities` | search / related assets | CLI GraphQL guide |
| URN shapes for dataset, dataJob/dataFlow, mlModel, corpGroup | fixture graph, scenarios | DataHub concepts + entity docs |
| Quickstart is ~14 containers (GMS, frontend, MySQL, OpenSearch, Kafka, actions) | deployment guide sizing | Quickstart guide |
| Quickstart container names `datahub-datahub-gms-quickstart-1`, `datahub-frontend-quickstart-1` | deployment guide | Quickstart guide |
| Frontend on `:9002`, default credentials `datahub` / `datahub` | deployment guide | Quickstart guide |
| `datahub init` then `datahub datapack load showcase-ecommerce` (~1 050 entities) | seed script, guide | Quickstart guide + datapack CLI guide |
| `datapack` is flagged **experimental** | guide caveat | datapack CLI guide |
| `nyc-taxi` has a planted freshness issue, `healthcare` planted quality issues | scenario design | hackathon resources page |
| supergateway flags `--stdio`, `--outputTransport streamableHttp`, `--stateful`, `--streamableHttpPath`, `--healthEndpoint`, `--port` | MCP bridge | supergateway README |

## Confirmed by a real deployment (6 August 2026)

`mcp-server-datahub` **cannot be installed on a musl base**. Its dependency
`google-re2` publishes manylinux and macOS/Windows wheels only — no musllinux —
so pip falls back to compiling `_re2.cc` and fails on a missing C++ toolchain.
The bridge image must be glibc-based; `datahub/mcp-bridge/Dockerfile` uses
Debian and installs the server at build time.

The failure is silent by design of the parts involved: supergateway starts,
answers `/healthz`, and only its child process dies. `/api/v1/datahub/status`
now reports the handshake itself (`mcp.ready`, `mcp.error`) so the state is
readable instead of inferred from an empty list.

## Second finding from the same deployment

A live network error (DNS, refused connection, timeout) used to escape the
provider as an exception and end the investigation as **FAILED** with a raw
`ConnectError`. The intended behaviour — and the one the failure-mode tests
covered — is **BLOCKED**, with a reason. The tests stubbed the provider to
*return* a failed ToolResult, so the transport path was never exercised.

Every public method of `LiveDataHubProvider` is now wrapped by a guard: no
exception leaves the provider, and the message names the host that failed and
why it usually fails here. Three tests cover it, including one that raises a
real `httpx.ConnectError`.

## Third finding: aspects are per entity type

Emitting `datasetProperties` to a dashboard is rejected by GMS with
`422 Unknown aspect datasetProperties for entity dashboard`. Verified shapes now
used by `datahub/seed/emit_demo_graph.py`:

| Entity | Properties aspect | Required fields |
|---|---|---|
| dataset | `DatasetPropertiesClass` | none (name, description, customProperties optional) |
| dataset → dataset lineage | `UpstreamLineageClass` / `UpstreamClass` | verified |
| dashboard → dataset | `DashboardInfoClass.datasetEdges` (`EdgeClass`) | verified; `datasets` is deprecated |
| mlModel → dataset | `mlModelTrainingData` | documented as direct model-to-training-data lineage; the exact class signature is **attempted defensively** and skipped if this SDK version differs |
| dashboard | `DashboardInfoClass` | `title`, `description`, `lastModified` (`ChangeAuditStampsClass`) |
| mlModel | `MLModelPropertiesClass` | none |

Source: DataHub Python SDK model reference and the metadata model documentation.

The emitter also no longer stops at the first rejection: it reports which
aspects were refused and continues, because a half-written graph is worse than a
failed run — the assets exist, nothing looks broken, and the investigation
degrades silently instead.

## Fourth finding: the catalog's own activity is not evidence

Seeding a live DataHub writes schema changes dated *now*. Against a scenario
dated months earlier, those arrived as a dozen `SCHEMA_CHANGE` signals, pushed
`SCHEMA_DRIFT` above the correct `SOURCE_DATA_ANOMALY`, and produced a root
cause naming a field that had merely been added.

Two gates now stand between the timeline and a causal claim:

- **A change after the incident is dropped.** It cannot have caused something
  that already happened.
- **A change must be able to break a consumer** to support schema drift:
  `modificationCategory` RENAME or TYPE_CHANGE, a REMOVE operation, or a MAJOR
  semantic version bump. An added field is compatible by construction; it stays
  in the record as context, at LOW relevance, carrying no hypothesis.

The timeline also identifies a changed field by its `schemaField` URN. Passed
through raw it landed in the root-cause sentence and made the trust score report
that it could not find a field named after a URN. It is now reduced to the field
name.

## Not verified — and how the code protects itself

**`addLink` input fields.** The mutation is listed in DataHub's mutations index,
but the exact shape of `AddLinkInput` (`linkUrl`, `label`, `resourceUrn`) was not
confirmed from official documentation. The write-back therefore treats it as
**best effort**: success requires at least one `addTags` to have applied, and a
failing `addLink` is logged and reported as `link_attached: false` rather than
failing the whole operation. The tag is the durable reference.

**`assertions` / `runEvents` GraphQL selection.** Used for quality context. If
the selection is rejected, `get_quality_context` returns a failed `ToolResult`
and the investigation continues with the quality signals it does have — the
trust score's *quality signals* check then drops to PARTIAL or FAIL, which is
the honest outcome.

**`searchAcrossLineage` field selection.** The query name is standard; the
precise field set is not quoted in the docs pages consulted. A rejected
selection surfaces as an explicit lineage failure, and an investigation without
lineage is **blocked** rather than answered.

**Nothing has been run against a live DataHub instance.** Every behaviour above
is either exercised against the deterministic fixture provider or read from
documentation. The first live run is the real test, and the failure modes it
would produce are the ones listed in the deployment guide's troubleshooting
section.

## How the code degrades

The design point behind all of this: any DataHub call that fails returns an
explicit failed `ToolResult` with its error, never an empty list. A missing tool,
a renamed field or a rejected selection therefore shows up as a visible gap —
in the timeline, in the trust score, or as a blocked investigation — and never
as a confident answer built on nothing.
