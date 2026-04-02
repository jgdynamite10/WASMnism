#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLATFORM="${1:?Usage: $0 <platform-name> <gateway-url> [--ml]}"
GATEWAY_URL="${2:?Usage: $0 <platform-name> <gateway-url> [--ml]}"
RUN_ML=false

for arg in "${@:3}"; do
    case "$arg" in
        --ml) RUN_ML=true ;;
        *)    echo "Unknown flag: $arg"; exit 1 ;;
    esac
done

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BASE_DIR="${SCRIPT_DIR}/../results/${PLATFORM}/7run_${TIMESTAMP}"
mkdir -p "${BASE_DIR}"

PRIMARY_TESTS=("warm-light" "warm-policy" "concurrency-ladder")
STRETCH_TESTS=("warm-heavy" "consistency")

echo "============================================"
echo "  WASMnism 7-Run Benchmark"
echo "  Platform: ${PLATFORM}"
echo "  Gateway:  ${GATEWAY_URL}"
echo "  ML tests: ${RUN_ML}"
echo "  Results:  ${BASE_DIR}"
echo "============================================"
echo ""

for RUN in $(seq 1 7); do
    RUN_DIR="${BASE_DIR}/run_${RUN}"
    mkdir -p "${RUN_DIR}"

    echo "=== Run ${RUN}/7 — $(date) ==="

    # Warm-up request (rules only)
    curl -sf -X POST "${GATEWAY_URL}/gateway/moderate" \
        -H "Content-Type: application/json" \
        -d '{"labels":["safe","unsafe"],"nonce":"warmup","text":"warm up request","ml":false}' \
        -o /dev/null -w "  Warm-up: HTTP %{http_code} in %{time_total}s\n"
    sleep 3

    echo "  --- Primary suite ---"
    for TEST in "${PRIMARY_TESTS[@]}"; do
        EXTRA_ARGS=""
        if [ "${TEST}" = "concurrency-ladder" ]; then
            EXTRA_ARGS="--env SKIP_ML=true"
        fi
        echo "  Running ${TEST}..."
        k6 run \
            --env GATEWAY_URL="${GATEWAY_URL}" \
            ${EXTRA_ARGS} \
            --summary-export="${RUN_DIR}/${TEST}.json" \
            --quiet \
            "${SCRIPT_DIR}/${TEST}.js"
    done

    if $RUN_ML; then
        echo "  --- Stretch suite ---"
        for TEST in "${STRETCH_TESTS[@]}"; do
            echo "  Running ${TEST}..."
            k6 run \
                --env GATEWAY_URL="${GATEWAY_URL}" \
                --summary-export="${RUN_DIR}/${TEST}.json" \
                --quiet \
                "${SCRIPT_DIR}/${TEST}.js"
        done
    fi

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
