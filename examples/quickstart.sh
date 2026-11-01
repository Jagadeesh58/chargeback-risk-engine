#!/usr/bin/env bash
set -euo pipefail

# Chargeback Risk Engine Quickstart Example
# Demonstrates authenticated decision evaluation with verified provenance

SERVER_URL="${CHARGEBACK_URL:-http://localhost:8000}"
API_KEY="${CHARGEBACK_API_KEY:-dev-secret-key-at-least-32-chars-long}"

echo "1. Checking engine liveness..."
curl -s -f "${SERVER_URL}/healthz"

echo -e "\n\n2. Submitting verified dispute with carrier API provenance..."
curl -s -X POST "${SERVER_URL}/decision" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ${API_KEY}" \
  -d @examples/request_verified.json

echo -e "\n\n3. Submitting unverified dispute (demonstrating fail-closed routing)..."
curl -s -X POST "${SERVER_URL}/decision" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ${API_KEY}" \
  -d @examples/request_unverified.json
echo ""
