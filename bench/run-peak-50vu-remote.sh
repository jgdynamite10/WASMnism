#!/bin/bash
set -euo pipefail

# Run constant-50VU benchmark for all 3 platforms from a single k6 runner.
#
# Usage:
#   ./run-peak-50vu-remote.sh <region> <akamai_url> <fastly_url> <workers_url>
#
# Example:
#   ./run-peak-50vu-remote.sh us-ord \
#     https://your-app.fwf.app \
#     https://your-app.edgecompute.app \
#     https://your-app.workers.dev

REGION="${1:?Usage: $0 <region> <akamai_url> <fastly_url> <workers_url>}"
AKAMAI_URL="${2:?Missing akamai_url}"
FASTLY_URL="${3:?Missing fastly_url}"
WORKERS_URL="${4:?Missing workers_url}"
OUTDIR="/opt/results/peak-50vu"
mkdir -p "$OUTDIR"

echo "=== Warm-up ==="
curl -sf "$AKAMAI_URL/gateway/health" -o /dev/null
curl -sf "$FASTLY_URL/gateway/health" -o /dev/null
curl -sf "$WORKERS_URL/gateway/health" -o /dev/null
sleep 2

echo "=== Akamai (${REGION}) ==="
k6 run --env GATEWAY_URL="$AKAMAI_URL" --summary-export="$OUTDIR/akamai_${REGION}.json" --quiet /opt/bench/constant-50vu.js
echo "  Done."
sleep 5

echo "=== Fastly (${REGION}) ==="
k6 run --env GATEWAY_URL="$FASTLY_URL" --summary-export="$OUTDIR/fastly_${REGION}.json" --quiet /opt/bench/constant-50vu.js
echo "  Done."
sleep 5

echo "=== Workers (${REGION}) ==="
k6 run --env GATEWAY_URL="$WORKERS_URL" --summary-export="$OUTDIR/workers_${REGION}.json" --quiet /opt/bench/constant-50vu.js
echo "  Done."

echo "=== All platforms complete for ${REGION} ==="
