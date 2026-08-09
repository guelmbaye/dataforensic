#!/usr/bin/env bash
# Shared transport for the demo scripts.
#
# In production the API port is not published — Nginx reaches the container over
# the Docker network — so `http://localhost:8000` is either nothing or, worse,
# some other project answering 404. Talking to the container directly removes
# the guesswork; the HTTP path stays for local development.

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
API="${API_URL:-http://localhost:8000/api/v1}"
API_SERVICE="${API_SERVICE:-api}"

api_transport() {
  if [ "${FORCE_HTTP:-false}" != "true" ] \
     && docker compose -f "$COMPOSE_FILE" ps "$API_SERVICE" >/dev/null 2>&1; then
    echo "docker"
  else
    echo "http"
  fi
}

# api_call METHOD PATH [JSON_BODY_FILE]
# Prints the response body. Returns non-zero and prints the API's own error on
# failure, rather than a stack trace or nothing at all.
api_call() {
  local method="$1" path="$2" body_file="${3:-}"

  if [ "$(api_transport)" = "docker" ]; then
    local payload=""
    [ -n "$body_file" ] && payload="$(cat "$body_file")"
    printf '%s' "$payload" | docker compose -f "$COMPOSE_FILE" exec -T "$API_SERVICE" python -c "
import sys, urllib.error, urllib.request

payload = sys.stdin.read().encode() or None
request = urllib.request.Request(
    'http://localhost:8000/api/v1$path',
    method='$method',
    data=payload,
    headers={'Content-Type': 'application/json'} if payload else {},
)
try:
    print(urllib.request.urlopen(request).read().decode())
except urllib.error.HTTPError as error:
    print(f'HTTP {error.code}: {error.read().decode(errors=\"replace\")}', file=sys.stderr)
    sys.exit(1)
except Exception as error:
    print(f'{type(error).__name__}: {error}', file=sys.stderr)
    sys.exit(1)
"
    return $?
  fi

  local response status
  if [ -n "$body_file" ]; then
    response="$(curl -sS -w '\n%{http_code}' -X "$method" -H 'Content-Type: application/json' \
      -d @"$body_file" "$API$path" 2>&1)" || { echo "cannot reach $API$path" >&2; return 1; }
  else
    response="$(curl -sS -w '\n%{http_code}' -X "$method" "$API$path" 2>&1)" \
      || { echo "cannot reach $API$path" >&2; return 1; }
  fi
  status="$(printf '%s' "$response" | tail -1)"
  printf '%s' "$response" | sed '$d'
  [ "$status" = "200" ] || [ "$status" = "201" ] || [ "$status" = "202" ] || {
    echo "$path returned HTTP $status" >&2
    return 1
  }
}
