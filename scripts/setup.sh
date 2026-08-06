#!/usr/bin/env bash
# Bring up a working DATAFORENSIC AI environment from a clean checkout.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> Checking prerequisites"
command -v docker >/dev/null || { echo "docker is required"; exit 1; }
docker compose version >/dev/null || { echo "docker compose v2 is required"; exit 1; }

if [ ! -f .env ]; then
  echo "==> Creating .env from .env.example"
  cp .env.example .env
else
  echo "==> .env already exists, keeping it"
fi

echo "==> Rebuilding the deterministic context graph"
python3 datahub/seed/build_graph.py

echo "==> Starting services"
if [ "${WITH_DATAHUB:-false}" = "true" ]; then
  docker compose --profile datahub up -d --build
else
  docker compose up -d --build
fi

echo "==> Waiting for the API"
for _ in $(seq 1 60); do
  if curl -sf http://localhost:8000/api/v1/health >/dev/null; then break; fi
  sleep 2
done

curl -s http://localhost:8000/api/v1/health | python3 -m json.tool || true

cat <<'MSG'

==> Ready
    API   http://localhost:8000/docs
    UI    http://localhost:3000

    Next: ./scripts/seed-demo.sh
MSG
