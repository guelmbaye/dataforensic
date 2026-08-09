#!/usr/bin/env bash
# Show exactly what the MCP bridge answers to an `initialize` handshake.
#
# The API reports the failure, but not the bytes. Everything about diagnosing an
# MCP bridge comes down to three facts: the HTTP status, the content-type, and
# the first bytes of the body — and whether the gateway's child process is still
# alive behind it.
set -uo pipefail
cd "$(dirname "$0")/.."

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
MCP_URL="${MCP_URL:-http://dataforensic-mcp:8000/mcp}"

echo "==> Bridge container"
docker compose -f "$COMPOSE_FILE" ps mcp

echo
echo "==> Image actually running (a pulled image cannot run mcp-server-datahub)"
docker compose -f "$COMPOSE_FILE" ps mcp --format '{{.Image}}' 2>/dev/null \
  || docker inspect dataforensic-mcp --format '{{.Config.Image}}'

echo
echo "==> Raw initialize handshake"
docker compose -f "$COMPOSE_FILE" exec -T api python - "$MCP_URL" <<'PY'
import json, sys, urllib.error, urllib.request

url = sys.argv[1]
payload = json.dumps({
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {"tools": {}},
        "clientInfo": {"name": "dataforensic-probe", "version": "1"},
    },
}).encode()

request = urllib.request.Request(
    url,
    data=payload,
    headers={
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": "2025-06-18",
    },
)
try:
    response = urllib.request.urlopen(request, timeout=20)
    body = response.read()
    print(f"    status       : {response.status}")
    print(f"    content-type : {response.headers.get('content-type')}")
    print(f"    session id   : {response.headers.get('mcp-session-id')}")
    print(f"    body bytes   : {len(body)}")
    print(f"    body         : {body[:400]!r}")
    if not body.strip():
        print("    -> empty body: either the reply comes on a separate GET stream,")
        print("       or the gateway's child process is dead. The logs below tell you which.")
except urllib.error.HTTPError as error:
    print(f"    HTTP {error.code}: {error.read()[:400]!r}")
except Exception as error:
    print(f"    {type(error).__name__}: {error}")
PY

echo
echo "==> Bridge logs since the probe (a dead child shows up here)"
docker compose -f "$COMPOSE_FILE" logs --tail 30 mcp
