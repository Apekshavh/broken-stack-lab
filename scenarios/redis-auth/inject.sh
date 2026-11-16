#!/usr/bin/env bash
# Scenario: redis-auth
# Injects a fault by restarting Redis with a password the app does not know.
# The override is written to a temp file so nothing on disk gives the answer away.
set -euo pipefail
cd "$(dirname "$0")/../.."

OVERRIDE="$(mktemp /tmp/fault-override.XXXXXX.yml)"
trap 'rm -f "$OVERRIDE"' EXIT

cat > "$OVERRIDE" <<'YAML'
services:
  redis:
    command: ["redis-server", "--maxmemory", "64mb", "--maxmemory-policy", "allkeys-lru", "--requirepass", "s3cr3t-rotated"]
YAML

docker compose -f docker-compose.yml -f "$OVERRIDE" up -d redis
echo
echo "Fault injected. Something is off with the stack. Investigate, fix, then run: python3 verify.py"
