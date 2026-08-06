# DataHub MCP bridge

`mcp-server-datahub` is a **stdio** server — the Streamable HTTP endpoint
documented by DataHub is a Cloud feature. This agent speaks HTTP, so
[supergateway](https://github.com/supercorp-ai/supergateway) runs the stdio
server and exposes it at `/mcp`.

```bash
docker compose --profile datahub up -d mcp
curl -s localhost:8001/healthz          # the bridge itself
curl -s localhost:8000/api/v1/datahub/status | python3 -m json.tool
```

The second command is the one that matters: `/healthz` only proves supergateway
is listening, not that the server behind it started. `datahub/status` reports the
handshake:

```json
"mcp": {
  "configured": true,
  "ready": true,
  "tools": ["search", "get_entities", "list_schema_fields", "get_lineage", "..."],
  "error": null
}
```

`ready: false` with an `error` is the honest failure. `ready: true` with an empty
tool list means the server answered but advertises nothing — check the pinned
version.

## Environment

| Variable | Purpose |
|---|---|
| `DATAHUB_GMS_URL` | GMS endpoint, e.g. `http://datahub-gms:8080` |
| `DATAHUB_GMS_TOKEN` | DataHub personal access token |
| `TOOLS_IS_MUTATION_ENABLED` | Leave `false`. Write-back goes through GraphQL, which needs no opt-in flag. |

## Why not the published `supercorp/supergateway:uvx` image

It is musl-based. `mcp-server-datahub` depends on `google-re2`, which publishes
manylinux wheels only, so pip falls back to a source build and fails on a
missing C++ toolchain. The failure is quiet: supergateway starts, `/healthz`
returns `ok`, and the child process exits on the first `initialize`.

The Dockerfile in this directory uses a Debian base and installs the server at
build time, which fixes both that and the cold-start download.
