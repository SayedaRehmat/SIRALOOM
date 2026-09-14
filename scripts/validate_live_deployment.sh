#!/usr/bin/env bash
set -euo pipefail

API_BASE="${1:?Usage: $0 https://api.example.org}"
API_BASE="${API_BASE%/}"

echo "== SIRALOOM liveness =="
curl --fail --silent --show-error "$API_BASE/api/v1/health" | python -m json.tool

echo "== SIRALOOM readiness =="
curl --fail --silent --show-error "$API_BASE/api/v1/ready" | python -m json.tool

echo "Live infrastructure health checks passed."
