#!/usr/bin/env bash
# Put the demo back to its initial state. Run before every rehearsal.
set -euo pipefail
cd "$(dirname "$0")/.."

API="${API_URL:-http://localhost:8000/api/v1}"

echo "==> Resetting application state, scenario state and incident memory"
curl -sf -X POST "$API/demo/reset" | python3 -m json.tool

echo "==> Pre-demo checklist"
curl -sf "$API/health" | python3 -c "
import json,sys
health = json.load(sys.stdin)
checks = [
    ('API healthy',        health['status'] == 'ok'),
    ('Database reachable', health['database'] == 'ok'),
    ('DataHub reachable',  health['datahub']['connected']),
]
for label, ok in checks:
    print(f'    [{\"x\" if ok else \" \"}] {label}')
print(f'    ->  context source: {health[\"datahub\"][\"source_mode\"]}')
if not all(ok for _, ok in checks):
    raise SystemExit('environment is not demo ready')
"
echo "==> Ready. Run ./scripts/seed-demo.sh to create the incident."
