# DataHub API surface — what is verified, and what is not

Every DataHub-specific claim this project makes was checked against the official
documentation on **6 August 2026** (DataHub Core **1.6.0**). This file exists so
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
