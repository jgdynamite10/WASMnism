#!/usr/bin/env bash
set -euo pipefail

# Run the full benchmark suite for a single platform.
# Usage: ./run-benchmark.sh <platform> <gateway_url> [region]
# Example: ./run-benchmark.sh spin https://wasm-prompt-firewall-imjy4pe0.fermyon.app us-ord
#
# Runs 7 iterations of each mode and saves results to results/<platform>/<region>/

PLATFORM="${1:?Usage: $0 <platform> <gateway_url> [region]}"
GATEWAY_URL="${2:?Usage: $0 <platform> <gateway_url> [region]}"
REGION="${3:-local}"
RUNS="${RUNS:-7}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

RESULTS_DIR="${SCRIPT_DIR}/../results/${PLATFORM}/${REGION}"
mkdir -p "${RESULTS_DIR}"

echo "=== WASMnism Benchmark Suite ==="
echo "Platform:  ${PLATFORM}"
echo "Gateway:   ${GATEWAY_URL}"
echo "Region:    ${REGION}"
echo "Runs:      ${RUNS}"
echo "Results:   ${RESULTS_DIR}"
echo ""

# Pre-flight health check
echo "=== Pre-flight health check ==="
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${GATEWAY_URL}/gateway/health")
if [ "${HTTP_CODE}" != "200" ]; then
    echo "FAIL: Health check returned ${HTTP_CODE}"
    exit 1
fi
echo "OK: Health check passed"
echo ""

# Mode 1: Policy-Only
echo "=== Mode 1: Policy-Only (${RUNS} runs) ==="
for i in $(seq 1 "${RUNS}"); do
    echo "  Run ${i}/${RUNS}..."
    k6 run \
        --env GATEWAY_URL="${GATEWAY_URL}" \
        --out json="${RESULTS_DIR}/policy-only_run${i}.json" \
        --summary-export="${RESULTS_DIR}/policy-only_run${i}_summary.json" \
        --quiet \
        "${SCRIPT_DIR}/policy-only.js"
    echo "  Run ${i} complete."
    sleep 5
done
echo ""

# Mode 2: Cached Hit (seed cache first via full pipeline)
echo "=== Mode 2: Cached Hit (${RUNS} runs) ==="
for i in $(seq 1 "${RUNS}"); do
    echo "  Run ${i}/${RUNS}..."
    k6 run \
        --env GATEWAY_URL="${GATEWAY_URL}" \
        --env IMAGE_PATH="${SCRIPT_DIR}/fixtures/benchmark.jpg" \
        --out json="${RESULTS_DIR}/cached-hit_run${i}.json" \
        --summary-export="${RESULTS_DIR}/cached-hit_run${i}_summary.json" \
        --quiet \
        "${SCRIPT_DIR}/cached-hit.js"
    echo "  Run ${i} complete."
    sleep 5
done
echo ""

# Mode 3: Full Pipeline
echo "=== Mode 3: Full Pipeline (${RUNS} runs) ==="
for i in $(seq 1 "${RUNS}"); do
    echo "  Run ${i}/${RUNS}..."
    k6 run \
        --env GATEWAY_URL="${GATEWAY_URL}" \
        --env IMAGE_PATH="${SCRIPT_DIR}/fixtures/benchmark.jpg" \
        --out json="${RESULTS_DIR}/full-pipeline_run${i}.json" \
        --summary-export="${RESULTS_DIR}/full-pipeline_run${i}_summary.json" \
        --quiet \
        "${SCRIPT_DIR}/full-pipeline.js"
    echo "  Run ${i} complete."
    sleep 5
done
echo ""

echo "=== All runs complete. Results saved to ${RESULTS_DIR} ==="
