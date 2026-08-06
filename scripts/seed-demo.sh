#!/usr/bin/env bash
# Load the demo context and validate that the golden scenario can run.
set -euo pipefail
cd "$(dirname "$0")/.."

API="${API_URL:-http://localhost:8000/api/v1}"
SCENARIO="${SCENARIO:-revenue-collapse}"

echo "==> DataHub status"
STATUS=$(curl -sf "$API/datahub/status")
echo "$STATUS" | python3 -m json.tool
MODE=$(echo "$STATUS" | python3 -c "import json,sys;print(json.load(sys.stdin)['source_mode'])")

if [ "$MODE" = "LIVE_DATAHUB" ]; then
  echo "==> Live DataHub detected."
  echo "    Load the official datapack in your DataHub instance if not done yet:"
  echo "      uvx --from acryl-datahub datahub init --username datahub --password datahub"
  echo "      uvx --from acryl-datahub datahub datapack load showcase-ecommerce"
else
  echo "==> Running on the deterministic context graph (DEMO_FIXTURE)."
  echo "    Every result produced in this mode is labelled DEMO_FIXTURE in the API and the UI."
fi

echo "==> Resetting demo state"
curl -sf -X POST "$API/demo/reset" | python3 -m json.tool

echo "==> Validating the scenario target asset and its lineage"
TARGET=$(python3 -c "
import json,sys
print(json.load(open('scenarios/$SCENARIO/scenario.json'))['target_asset_urn'])")
curl -sfG "$API/datahub/lineage" --data-urlencode "urn=$TARGET" --data-urlencode "depth=4" \
  | python3 -c "
import json,sys
data = json.load(sys.stdin)
nodes = data['nodes']
up = sum(1 for n in nodes if n['direction'] == 'UPSTREAM')
down = sum(1 for n in nodes if n['direction'] == 'DOWNSTREAM')
print(f'    lineage ok: {up} upstream / {down} downstream (source: {data[\"source_mode\"]})')
assert up and down, 'the scenario needs lineage on both sides'
"

echo "==> Creating the demo incident"
INCIDENT=$(python3 -c "
import json
payload = json.load(open('scenarios/$SCENARIO/incident.json'))
print(json.dumps(payload))")
curl -sf -X POST "$API/incidents" -H 'Content-Type: application/json' -d "$INCIDENT" \
  | python3 -m json.tool

echo
echo "==> Demo seeded. Open http://localhost:3000 and press Investigate."
