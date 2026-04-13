#!/usr/bin/env bash
set -uo pipefail

# Extended benchmark suite: base tests + expanded ladder + soak + spike.
# Designed for GCP e2-standard-4 runners (4 vCPU, 16 GB).
#
# Usage:
#   ./bench/run-full-suite.sh <platform> <gateway-url> [OPTIONS]
#
# Options:
#   --cold              Include cold start test (~20 min extra)
#   --skip-base         Skip base suite (warm-light, warm-policy, original ladder)
#   --skip-extended     Skip extended tests (full ladder, soak, spike)
#   --spike-vus N       Override spike VU target (default: 667 per runner; 3 runners = 2,000)
#
# Time estimates:
#   Base only:     ~12 min
#   Extended only: ~20 min (7 min ladder + 10 min soak + 1.5 min spike)
#   Full:          ~32 min
#   Full + cold:   ~52 min

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLATFORM="${1:?Usage: $0 <platform> <gateway-url> [--cold] [--skip-base] [--skip-extended] [--spike-vus N]}"
GATEWAY_URL="${2:?Usage: $0 <platform> <gateway-url> [--cold] [--skip-base] [--skip-extended] [--spike-vus N]}"

RUN_COLD=false
SKIP_BASE=false
SKIP_EXTENDED=false
SPIKE_VUS=667

shift 2
while [ $# -gt 0 ]; do
    case "$1" in
        --cold)           RUN_COLD=true ;;
        --skip-base)      SKIP_BASE=true ;;
        --skip-extended)  SKIP_EXTENDED=true ;;
        --spike-vus)      SPIKE_VUS="$2"; shift ;;
        *)                echo "Unknown flag: $1"; exit 1 ;;
    esac
    shift
done

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
RESULTS_DIR="${SCRIPT_DIR}/../results/${PLATFORM}/full_${TIMESTAMP}"
mkdir -p "${RESULTS_DIR}"

echo "============================================"
echo "  WASMnism Full Benchmark Suite (rules-only)"
echo "  Platform:       ${PLATFORM}"
echo "  Gateway:        ${GATEWAY_URL}"
echo "  Results:        ${RESULTS_DIR}"
echo "  Cold start:     ${RUN_COLD}"
echo "  Base suite:     $( $SKIP_BASE && echo SKIP || echo YES )"
echo "  Extended suite: $( $SKIP_EXTENDED && echo SKIP || echo YES )"
echo "  Spike VUs:      ${SPIKE_VUS}"
echo "  Date:           $(date)"
echo "============================================"
echo ""

# ── Pre-flight ──────────────────────────────────────────────
echo "=== Pre-flight health check ==="
CODE=$(curl -s -o /dev/null -w "%{http_code}" "${GATEWAY_URL}/gateway/health")
if [ "${CODE}" != "200" ]; then
    echo "FAIL: Health check returned ${CODE}"
    exit 1
fi
echo "  OK (HTTP ${CODE})"
echo ""

echo "=== Warm-up request ==="
curl -sf -X POST "${GATEWAY_URL}/gateway/moderate" \
    -H "Content-Type: application/json" \
    -d '{"labels":["safe","unsafe"],"nonce":"warmup","text":"warm up request"}' \
    -o /dev/null -w "  HTTP %{http_code} in %{time_total}s\n"
sleep 3
echo ""

TEST_NUM=0

# ── Base Suite ──────────────────────────────────────────────
if ! $SKIP_BASE; then
    echo "=========================================="
    echo "  BASE SUITE (same as reproduce pipeline)"
    echo "=========================================="
    echo ""

    TEST_NUM=$((TEST_NUM + 1))
    echo "=== Test ${TEST_NUM}: Warm Light (10 VUs, 60s) ==="
    k6 run \
        --env GATEWAY_URL="${GATEWAY_URL}" \
        --summary-export="${RESULTS_DIR}/warm-light.json" \
        --quiet \
        "${SCRIPT_DIR}/warm-light.js"
    echo ""

    TEST_NUM=$((TEST_NUM + 1))
    echo "=== Test ${TEST_NUM}: Warm Policy (10 VUs, 60s) ==="
    k6 run \
        --env GATEWAY_URL="${GATEWAY_URL}" \
        --summary-export="${RESULTS_DIR}/warm-policy.json" \
        --quiet \
        "${SCRIPT_DIR}/warm-policy.js"
    echo ""

    TEST_NUM=$((TEST_NUM + 1))
    echo "=== Test ${TEST_NUM}: Concurrency Ladder — Standard (1→50 VUs, 150s) ==="
    k6 run \
        --env GATEWAY_URL="${GATEWAY_URL}" \
        --summary-export="${RESULTS_DIR}/concurrency-ladder.json" \
        --quiet \
        "${SCRIPT_DIR}/concurrency-ladder.js"
    echo ""

    TEST_NUM=$((TEST_NUM + 1))
    echo "=== Test ${TEST_NUM}: Sustained Peak (50 VUs, 60s) ==="
    k6 run \
        --env GATEWAY_URL="${GATEWAY_URL}" \
        --summary-export="${RESULTS_DIR}/constant-50vu.json" \
        --quiet \
        "${SCRIPT_DIR}/constant-50vu.js"
    echo ""
fi

# ── Extended Suite ──────────────────────────────────────────
if ! $SKIP_EXTENDED; then
    echo "=========================================="
    echo "  EXTENDED SUITE (higher concurrency)"
    echo "=========================================="
    echo ""

    TEST_NUM=$((TEST_NUM + 1))
    echo "=== Test ${TEST_NUM}: Full Ladder (1→1,000 VUs, 420s) ==="
    k6 run \
        --env GATEWAY_URL="${GATEWAY_URL}" \
        --summary-export="${RESULTS_DIR}/concurrency-ladder-full.json" \
        --quiet \
        "${SCRIPT_DIR}/concurrency-ladder-full.js"
    echo ""

    TEST_NUM=$((TEST_NUM + 1))
    echo "=== Test ${TEST_NUM}: Soak (500 VUs, 10 min) ==="
    k6 run \
        --env GATEWAY_URL="${GATEWAY_URL}" \
        --summary-export="${RESULTS_DIR}/soak-500vu.json" \
        --quiet \
        "${SCRIPT_DIR}/soak-500vu.js"
    echo ""

    TEST_NUM=$((TEST_NUM + 1))
    echo "=== Test ${TEST_NUM}: Spike (0→${SPIKE_VUS} VUs, ramp+hold+ramp) ==="
    k6 run \
        --env GATEWAY_URL="${GATEWAY_URL}" \
        --env SPIKE_VUS="${SPIKE_VUS}" \
        --summary-export="${RESULTS_DIR}/spike.json" \
        --quiet \
        "${SCRIPT_DIR}/spike-2000vu.js"
    echo ""
fi

# ── Cold Start ──────────────────────────────────────────────
if $RUN_COLD; then
    echo "=========================================="
    echo "  COLD START TEST (~20 min)"
    echo "=========================================="
    echo ""

    TEST_NUM=$((TEST_NUM + 1))
    echo "=== Test ${TEST_NUM}: Cold Start — Rules Only ==="
    k6 run \
        --env GATEWAY_URL="${GATEWAY_URL}" \
        --summary-export="${RESULTS_DIR}/cold-start-rules.json" \
        "${SCRIPT_DIR}/cold-start.js"
    echo ""
fi

echo "============================================"
echo "  Full Suite Complete (${TEST_NUM} tests)"
echo "============================================"
echo ""
echo "  Results: ${RESULTS_DIR}/"
ls -la "${RESULTS_DIR}/"
echo ""
