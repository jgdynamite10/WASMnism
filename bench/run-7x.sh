#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLATFORM="${1:?Usage: $0 <platform-name> <gateway-url>}"
GATEWAY_URL="${2:?Usage: $0 <platform-name> <gateway-url>}"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BASE_DIR="${SCRIPT_DIR}/../results/${PLATFORM}/7run_${TIMESTAMP}"
mkdir -p "${BASE_DIR}"

PRIMARY_TESTS=("warm-light" "warm-policy" "concurrency-ladder")

echo "============================================"
echo "  WASMnism 7-Run Benchmark (rules-only)"
echo "  Platform: ${PLATFORM}"
echo "  Gateway:  ${GATEWAY_URL}"
echo "  Results:  ${BASE_DIR}"
echo "============================================"
echo ""

for RUN in $(seq 1 7); do
    RUN_DIR="${BASE_DIR}/run_${RUN}"
    mkdir -p "${RUN_DIR}"

    echo "=== Run ${RUN}/7 — $(date) ==="

    # Warm-up request
    curl -sf -X POST "${GATEWAY_URL}/gateway/moderate" \
        -H "Content-Type: application/json" \
        -d '{"labels":["safe","unsafe"],"nonce":"warmup","text":"warm up request"}' \
        -o /dev/null -w "  Warm-up: HTTP %{http_code} in %{time_total}s\n"
    sleep 3

    for TEST in "${PRIMARY_TESTS[@]}"; do
        echo "  Running ${TEST}..."
        k6 run \
            --env GATEWAY_URL="${GATEWAY_URL}" \
            --summary-export="${RUN_DIR}/${TEST}.json" \
            --quiet \
            "${SCRIPT_DIR}/${TEST}.js"
    done

    echo "  Run ${RUN} complete."
    echo ""

    if [ "${RUN}" -lt 7 ]; then
        echo "  Cooling down 10s..."
        sleep 10
    fi
done

echo "============================================"
echo "  7 runs complete! Results: ${BASE_DIR}/"
echo "  Next: python3 bench/compute-medians.py ${BASE_DIR}/"
echo "============================================"
