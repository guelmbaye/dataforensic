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

# shellcheck source=lib/api.sh
. "$(dirname "$0")/lib/api.sh"

call_api() { api_call "$1" "$2"; }

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
