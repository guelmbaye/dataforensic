#!/usr/bin/env bash
# Load the demo context and validate that the golden scenario can run.
set -uo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=lib/api.sh
. "$(dirname "$0")/lib/api.sh"

SCENARIO="${SCENARIO:-revenue-collapse}"
fail() { echo "ERROR: $*" >&2; exit 1; }

echo "==> Transport: $(api_transport)"

echo
echo "==> API health"
HEALTH="$(api_call GET /health)" || fail "the API did not answer /health"
printf '%s' "$HEALTH" | python3 -c "
import json, sys

health = json.load(sys.stdin)
datahub = health['datahub']
print(f\"    api={health['status']} db={health['database']} \"
      f\"context={datahub['source_mode']} connected={datahub['connected']}\")
mcp = datahub.get('mcp', {})
if mcp.get('configured'):
    state = 'ready' if mcp.get('ready') else 'NOT ready'
    print(f\"    mcp: {state} ({len(mcp.get('tools', []))} tools) {mcp.get('error') or ''}\")
    if not mcp.get('ready'):
        print('    -> Reads fall back to GraphQL. Investigations still run.')
if not datahub['connected']:
    print('    -> DataHub is not reachable. Live-mode investigations will be BLOCKED.')
"

echo
echo "==> Scenario target and lineage"
TARGET="$(python3 -c "
import json
print(json.load(open('scenarios/$SCENARIO/scenario.json'))['target_asset_urn'])")"

LINEAGE="$(api_call GET "/datahub/lineage?urn=$(python3 -c "
import sys, urllib.parse
print(urllib.parse.quote(sys.argv[1], safe=''))" "$TARGET")&depth=4")" \
  || echo "    lineage unavailable — impact analysis will be empty"

if [ -n "${LINEAGE:-}" ]; then
  printf '%s' "$LINEAGE" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
except json.JSONDecodeError:
    raise SystemExit('    lineage call returned no JSON')
nodes = data.get('nodes', [])
up = sum(1 for n in nodes if n['direction'] == 'UPSTREAM')
down = sum(1 for n in nodes if n['direction'] == 'DOWNSTREAM')
print(f'    {up} upstream / {down} downstream (source: {data.get(\"source_mode\")})')
if not up and not down:
    print('    -> No lineage. Run: python3 datahub/seed/emit_demo_graph.py')
" || true
fi

echo
echo "==> Creating the demo incident"
CREATED="$(api_call POST /incidents "scenarios/$SCENARIO/incident.json")" \
  || fail "the incident could not be created"
printf '%s' "$CREATED" | python3 -c "
import json, sys
body = json.load(sys.stdin)
print(f\"    incident {body['id']} — {body['title']}\")
"

echo
echo "==> Seeded. Open the UI and press Investigate."
