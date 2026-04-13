#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLATFORM="${1:?Usage: $0 <platform-name> <gateway-url> [--cold]}"
GATEWAY_URL="${2:?Usage: $0 <platform-name> <gateway-url> [--cold]}"
RUN_COLD=false

for arg in "${@:3}"; do
    case "$arg" in
        --cold) RUN_COLD=true ;;
        *)      echo "Unknown flag: $arg"; exit 1 ;;
    esac
done

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
RESULTS_DIR="${SCRIPT_DIR}/../results/${PLATFORM}/${TIMESTAMP}"
mkdir -p "${RESULTS_DIR}"

echo "============================================"
echo "  WASMnism Benchmark Suite (rules-only)"
echo "  Platform: ${PLATFORM}"
echo "  Gateway:  ${GATEWAY_URL}"
echo "  Results:  ${RESULTS_DIR}"
echo "  Cold:     ${RUN_COLD}"
echo "  Date:     $(date)"
echo "============================================"
echo ""

echo "=== Pre-flight health check ==="
CODE=$(curl -s -o /dev/null -w "%{http_code}" "${GATEWAY_URL}/gateway/health")
if [ "${CODE}" != "200" ]; then
    echo "FAIL: Health check returned ${CODE}"
    exit 1
fi
echo "  OK"
echo ""

echo "=== Warm-up request ==="
curl -sf -X POST "${GATEWAY_URL}/gateway/moderate" \
    -H "Content-Type: application/json" \
    -d '{"labels":["safe","unsafe"],"nonce":"warmup","text":"warm up request"}' \
    -o /dev/null -w "  HTTP %{http_code} in %{time_total}s\n"
sleep 3
echo ""

echo "=========================================="
echo "  Rule-Based Pipeline Suite"
echo "=========================================="
echo ""

TEST_NUM=1
TOTAL_TESTS=3
if $RUN_COLD; then TOTAL_TESTS=$((TOTAL_TESTS + 1)); fi

echo "=== Test ${TEST_NUM}: Warm Light (GET /gateway/health, 10 VUs, 60s) ==="
k6 run \
    --env GATEWAY_URL="${GATEWAY_URL}" \
    --summary-export="${RESULTS_DIR}/warm-light.json" \
    --quiet \
    "${SCRIPT_DIR}/warm-light.js"
echo ""
TEST_NUM=$((TEST_NUM + 1))

echo "=== Test ${TEST_NUM}: Warm Policy (rules + text, 10 VUs, 60s) ==="
k6 run \
    --env GATEWAY_URL="${GATEWAY_URL}" \
    --summary-export="${RESULTS_DIR}/warm-policy.json" \
    --quiet \
    "${SCRIPT_DIR}/warm-policy.js"
echo ""
TEST_NUM=$((TEST_NUM + 1))

echo "=== Test ${TEST_NUM}: Concurrency Ladder (1→50 VUs, 150s) ==="
k6 run \
    --env GATEWAY_URL="${GATEWAY_URL}" \
    --summary-export="${RESULTS_DIR}/concurrency-ladder.json" \
    --quiet \
    "${SCRIPT_DIR}/concurrency-ladder.js"
echo ""
TEST_NUM=$((TEST_NUM + 1))

# =========================================================================
# COLD START (optional, long-running)
# =========================================================================

if $RUN_COLD; then
    echo "=========================================="
    echo "  COLD START TEST"
    echo "=========================================="
    echo ""

    echo "=== Test ${TEST_NUM}: Cold Start — Rules Only (~20 min) ==="
    k6 run \
        --env GATEWAY_URL="${GATEWAY_URL}" \
        --summary-export="${RESULTS_DIR}/cold-start-rules.json" \
        "${SCRIPT_DIR}/cold-start.js"
    echo ""
    TEST_NUM=$((TEST_NUM + 1))
fi

echo "============================================"
echo "  Suite complete! Results: ${RESULTS_DIR}/"
echo "============================================"
