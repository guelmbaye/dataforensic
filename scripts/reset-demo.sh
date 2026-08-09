#!/usr/bin/env bash
# Put the demo back to its initial state. Run before every rehearsal.
#
# The reset endpoint is deliberately unreachable from the internet — the
# deployment vhost answers it with 403, because a visitor able to wipe the
# incidents mid-judging is not a risk worth taking. So this script talks to the
# API container directly when Docker is in front of it, and falls back to a
# plain HTTP call for local development.
set -euo pipefail
cd "$(dirname "$0")/.."

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
API="${API_URL:-http://localhost:8000/api/v1}"
SERVICE="${API_SERVICE:-api}"

call_api() {
  local method="$1" path="$2"
  if [ "${FORCE_HTTP:-false}" != "true" ] \
     && docker compose -f "$COMPOSE_FILE" ps "$SERVICE" >/dev/null 2>&1; then
    docker compose -f "$COMPOSE_FILE" exec -T "$SERVICE" python -c "
import sys, urllib.error, urllib.request

request = urllib.request.Request('http://localhost:8000/api/v1$path', method='$method')
try:
    print(urllib.request.urlopen(request).read().decode())
except urllib.error.HTTPError as error:
    # The API answers with a structured error; a stack trace hides it.
    body = error.read().decode(errors='replace')
    print(f'HTTP {error.code} from $path: {body}', file=sys.stderr)
    sys.exit(1)
"
  else
    curl -sf -X "$method" "$API$path"
  fi
}

echo "==> Resetting incidents, investigations, knowledge patterns and scenario state"
call_api POST /demo/reset | python3 -m json.tool

echo
echo "==> Pre-demo checklist"
call_api GET /health | python3 -c "
import json, sys

health = json.load(sys.stdin)
datahub = health['datahub']
checks = [
    ('API healthy',        health['status'] == 'ok'),
    ('Database reachable', health['database'] == 'ok'),
    ('DataHub reachable',  datahub['connected']),
]
for label, ok in checks:
    print(f'    [{\"x\" if ok else \" \"}] {label}')

print(f'    ->  context source: {datahub[\"source_mode\"]}')
mcp = datahub.get('mcp', {})
if mcp.get('configured'):
    state = 'ready' if mcp.get('ready') else 'NOT ready - ' + str(mcp.get('error'))
    print(f'    ->  MCP: {state} ({len(mcp.get(\"tools\", []))} tools)')

if not all(ok for _, ok in checks):
    raise SystemExit('environment is not demo ready')
"

echo
echo "==> Ready. Run ./scripts/seed-demo.sh to create the incident."
echo "    DataHub metadata is left untouched: the tags written by past"
echo "    investigations are the proof of write-back, and re-running upserts them."
echo "    To wipe DataHub itself, see docs/DEPLOY-DIGITALOCEAN.md section 12."
