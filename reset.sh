#!/usr/bin/env bash
# Restores the healthy baseline: recreates services from docker-compose.yml only.
set -euo pipefail
cd "$(dirname "$0")"
docker compose up -d --build --force-recreate redis app nginx
echo "Baseline restored. Run: python3 verify.py"
