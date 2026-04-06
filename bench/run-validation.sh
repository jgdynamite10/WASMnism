#!/usr/bin/env bash
set -euo pipefail

# Run the moderation validation suite against a single platform.
# Usage: ./run-validation.sh <platform> <gateway_url>
# Examples:
#   ./run-validation.sh fermyon https://wasm-prompt-firewall-imjy4pe0.fermyon.app
#   ./run-validation.sh akamai  https://0ae93a16-62c9-44cc-8a2b-23f7c6b9bae1.fwf.app

PLATFORM="${1:?Usage: $0 <platform> <gateway_url>}"
GATEWAY_URL="${2:?Usage: $0 <platform> <gateway_url>}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Moderation Validation Suite ==="
echo "Platform:  ${PLATFORM}"
echo "Gateway:   ${GATEWAY_URL}"
echo ""

# Pre-flight health check
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${GATEWAY_URL}/gateway/health")
if [ "${HTTP_CODE}" != "200" ]; then
    echo "FAIL: Health check returned ${HTTP_CODE}"
    exit 1
fi
echo "Health check passed"
echo ""

# Fastly Compute has no filesystem access for the ML model
ML_ENABLED="true"
if [ "${PLATFORM}" = "fastly" ]; then
    ML_ENABLED="false"
    echo "Note: ML toxicity checks disabled (Fastly adapter has no filesystem for ML model)"
    echo ""
fi

k6 run \
    --env GATEWAY_URL="${GATEWAY_URL}" \
    --env ML_ENABLED="${ML_ENABLED}" \
    "${SCRIPT_DIR}/moderation-validation.js"

EXIT=$?

echo ""
if [ "${EXIT}" -eq 0 ]; then
    echo "=== ${PLATFORM}: ALL SCENARIOS PASSED ==="
else
    echo "=== ${PLATFORM}: VALIDATION FAILED (exit code ${EXIT}) ==="
fi

exit "${EXIT}"
