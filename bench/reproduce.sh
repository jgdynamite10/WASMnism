#!/usr/bin/env bash
set -euo pipefail

# End-to-end benchmark reproduction pipeline.
# Chains: prereq check → validate → 7-run suite → compute medians → results doc.
#
# Usage:
#   ./bench/reproduce.sh <platform> <gateway-url> [--ml] [--cold] [--region <name>]
#
# Examples:
#   ./bench/reproduce.sh akamai  https://0ae93a16-62c9-44cc-8a2b-23f7c6b9bae1.fwf.app
#   ./bench/reproduce.sh fastly  https://morally-civil-urchin.edgecompute.app --cold
#   ./bench/reproduce.sh akamai  https://your-gateway.fwf.app --region us-ord

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLATFORM="${1:?Usage: $0 <platform> <gateway-url> [--ml] [--cold] [--region <name>]}"
GATEWAY_URL="${2:?Usage: $0 <platform> <gateway-url> [--ml] [--cold] [--region <name>]}"
RUN_ML=false
RUN_COLD=false
REGION="local"

shift 2
while [ $# -gt 0 ]; do
    case "$1" in
        --ml)     RUN_ML=true ;;
        --cold)   RUN_COLD=true ;;
        --region) REGION="$2"; shift ;;
        *)        echo "Unknown flag: $1"; exit 1 ;;
    esac
    shift
done

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
RESULTS_BASE="${SCRIPT_DIR}/../results/${PLATFORM}"

echo "============================================"
echo "  WASMnism Reproduce Pipeline"
echo "  Platform: ${PLATFORM}"
echo "  Gateway:  ${GATEWAY_URL}"
echo "  Region:   ${REGION}"
echo "  ML:       ${RUN_ML}"
echo "  Cold:     ${RUN_COLD}"
echo "  Date:     $(date)"
echo "============================================"
echo ""

# ── Step 0: Prerequisite check ──────────────────────────────
echo "=== Step 0: Prerequisite check ==="
MISSING=()
command -v curl    &>/dev/null || MISSING+=("curl")
command -v k6      &>/dev/null || MISSING+=("k6 (https://k6.io/docs/get-started/installation/)")
command -v python3 &>/dev/null || MISSING+=("python3")

if [ ${#MISSING[@]} -gt 0 ]; then
    echo "ERROR: Missing required tools:"
    for tool in "${MISSING[@]}"; do echo "  - $tool"; done
    exit 1
fi

echo "  curl:    $(curl --version | head -1)"
echo "  k6:      $(k6 version)"
echo "  python3: $(python3 --version)"
echo "  OK"
echo ""

# ── Step 1: Health check ────────────────────────────────────
echo "=== Step 1: Health check ==="
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${GATEWAY_URL}/gateway/health")
if [ "${HTTP_CODE}" != "200" ]; then
    echo "FAIL: Health check returned ${HTTP_CODE}"
    echo "Gateway may not be deployed or URL is wrong."
    exit 1
fi
echo "  Health check: HTTP ${HTTP_CODE} — OK"
echo ""

# ── Step 2: Validation (8 rule scenarios, ML skipped) ──────
echo "=== Step 2: Validation suite (rules-only) ==="
if ! "${SCRIPT_DIR}/run-validation.sh" "${PLATFORM}" "${GATEWAY_URL}"; then
    echo ""
    echo "FAIL: Validation did not pass. Fix issues before benchmarking."
    exit 1
fi
echo ""
echo "  Validation: PASS"
echo ""

# ── Step 3: 7-run benchmark suite ───────────────────────────
echo "=== Step 3: 7-run benchmark suite ==="
ML_FLAG=""
if $RUN_ML; then ML_FLAG="--ml"; fi

"${SCRIPT_DIR}/run-7x.sh" "${PLATFORM}" "${GATEWAY_URL}" ${ML_FLAG} || true

# Find the latest 7run directory
LATEST_7RUN=$(ls -td "${RESULTS_BASE}/7run_"* 2>/dev/null | head -1)
if [ -z "${LATEST_7RUN}" ]; then
    echo "ERROR: No 7-run results found."
    exit 1
fi
echo ""

# ── Step 4: Compute medians ─────────────────────────────────
echo "=== Step 4: Compute medians ==="
MEDIANS_FILE="${RESULTS_BASE}/medians_${REGION}_${TIMESTAMP}.md"
python3 "${SCRIPT_DIR}/compute-medians.py" "${LATEST_7RUN}" "${MEDIANS_FILE}"
echo "  Medians written to: ${MEDIANS_FILE}"
echo ""

# ── Step 5: Cold start (optional) ───────────────────────────
if $RUN_COLD; then
    echo "=== Step 5: Cold start tests ==="
    COLD_DIR="${RESULTS_BASE}/cold_start"
    mkdir -p "${COLD_DIR}"

    echo "  Running cold start — rules only (~20 min)..."
    k6 run \
        --env GATEWAY_URL="${GATEWAY_URL}" \
        --env USE_ML=false \
        --summary-export="${COLD_DIR}/cold-start-rules_${REGION}.json" \
        "${SCRIPT_DIR}/cold-start.js"

    if $RUN_ML; then
        echo "  Running cold start — ML (~20 min)..."
        k6 run \
            --env GATEWAY_URL="${GATEWAY_URL}" \
            --env USE_ML=true \
            --summary-export="${COLD_DIR}/cold-start-ml_${REGION}.json" \
            "${SCRIPT_DIR}/cold-start.js"
    fi
    echo ""
fi

# ── Step 6: Summary ─────────────────────────────────────────
echo "============================================"
echo "  Reproduce Pipeline Complete"
echo "============================================"
echo ""
echo "  Platform:  ${PLATFORM}"
echo "  Region:    ${REGION}"
echo "  7-run dir: ${LATEST_7RUN}"
echo "  Medians:   ${MEDIANS_FILE}"
if $RUN_COLD; then
    echo "  Cold start: ${COLD_DIR}/"
fi
echo ""
echo "  To compare with another platform:"
echo "    python3 bench/build-scorecard.py <this_results_dir> <other_results_dir>"
echo ""
