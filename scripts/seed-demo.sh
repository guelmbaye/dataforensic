#!/usr/bin/env bash
# Load the demo context and validate that the golden scenario can run.
#
# Every call reports what it got. The previous version used `curl -sf`, which
# under `set -e` aborts the script with no output at all: a 503 from the API
# looked exactly like success followed by nothing.
set -uo pipefail
cd "$(dirname "$0")/.."

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
API="${API_URL:-http://localhost:8000/api/v1}"
SCENARIO="${SCENARIO:-revenue-collapse}"

fail() { echo "ERROR: $*" >&2; exit 1; }

get() {
  local path="$1" body status
  body="$(curl -sS -w '\n%{http_code}' "$API$path" 2>&1)" || fail "cannot reach $API$path"
  status="$(printf '%s' "$body" | tail -1)"
  printf '%s' "$body" | sed '$d'
  [ "$status" = "200" ] || fail "$path returned HTTP $status (see the body above)"
}

echo "==> API health"
HEALTH="$(get /health)" || exit 1
printf '%s' "$HEALTH" | python3 -c "
import json, sys
health = json.load(sys.stdin)
datahub = health['datahub']
print(f\"    api={health['status']} db={health['database']} \"
      f\"context={datahub['source_mode']} connected={datahub['connected']}\")
mcp = datahub.get('mcp', {})
if mcp.get('configured'):
    print(f\"    mcp: {'ready' if mcp.get('ready') else 'NOT ready'} \"
          f\"({len(mcp.get('tools', []))} tools) {mcp.get('error') or ''}\")
if not datahub['connected']:
    print('    -> DataHub is not reachable. Investigations will be BLOCKED in live mode.')
"

echo
echo "==> DataHub status"
STATUS="$(get /datahub/status)" || exit 1
MODE="$(printf '%s' "$STATUS" | python3 -c "import json,sys;print(json.load(sys.stdin)['source_mode'])")"

if [ "$MODE" = "LIVE_DATAHUB" ]; then
  echo "    Live DataHub. If the demo assets are missing, seed them:"
  echo "      python3 datahub/seed/emit_demo_graph.py"
else
  echo "    Deterministic context graph (DEMO_FIXTURE)."
  echo "    Every result produced in this mode is labelled DEMO_FIXTURE in the API and UI."
fi

echo
echo "==> Validating the scenario target asset and its lineage"
TARGET="$(python3 -c "
import json
print(json.load(open('scenarios/$SCENARIO/scenario.json'))['target_asset_urn'])")"

curl -sS -G "$API/datahub/lineage" --data-urlencode "urn=$TARGET" --data-urlencode "depth=4" \
  | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
except json.JSONDecodeError:
    raise SystemExit('    lineage call returned no JSON — is DataHub reachable?')
if 'error' in data:
    raise SystemExit(f\"    lineage unavailable: {data['error'].get('message')}\")
nodes = data.get('nodes', [])
up = sum(1 for n in nodes if n['direction'] == 'UPSTREAM')
down = sum(1 for n in nodes if n['direction'] == 'DOWNSTREAM')
print(f'    {up} upstream / {down} downstream (source: {data[\"source_mode\"]})')
if not up and not down:
    print('    -> No lineage. Impact analysis will be empty; run emit_demo_graph.py.')
"

echo
echo "==> Creating the demo incident"
curl -sS -X POST "$API/incidents" -H 'Content-Type: application/json' \
  -d @"scenarios/$SCENARIO/incident.json" \
  | python3 -c "
import json, sys
body = json.load(sys.stdin)
if 'error' in body:
    raise SystemExit(f\"    refused: {body['error'].get('message')}\")
print(f\"    incident {body['id']} — {body['title']}\")
"

echo
echo "==> Seeded. Open the UI and press Investigate."
