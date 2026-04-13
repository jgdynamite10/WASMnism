#!/usr/bin/env bash
set -euo pipefail

# Run the reproduce pipeline from all 3 k6 runners in parallel.
# Collects results back to local machine.
#
# Usage:
#   ./bench/run-multiregion.sh <platform> <gateway-url> [OPTIONS]
#
# Options:
#   --provider linode|gcp   Select runner infrastructure (default: linode)
#   --full                  Run the extended full suite instead of reproduce pipeline
#   --cold                  Include cold start tests
#   --spike-vus N           Override spike VU target for full suite (default: 667)
#
# Prerequisites:
#   - deploy/runners.env or deploy/gcp-runners.env exists
#   - Scripts synced to runners

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PLATFORM="${1:?Usage: $0 <platform> <gateway-url> [--provider linode|gcp] [--full] [--cold]}"
GATEWAY_URL="${2:?Usage: $0 <platform> <gateway-url> [--provider linode|gcp] [--full] [--cold]}"

PROVIDER="linode"
RUN_FULL=false
EXTRA_FLAGS=""
SSH_USER="root"

shift 2
while [ $# -gt 0 ]; do
    case "$1" in
        --provider)  PROVIDER="$2"; shift ;;
        --full)      RUN_FULL=true ;;
        *)           EXTRA_FLAGS="${EXTRA_FLAGS} ${1}" ;;
    esac
    shift
done

case "$PROVIDER" in
    linode)
        RUNNERS_FILE="${REPO_ROOT}/deploy/runners.env"
        SSH_USER="root"
        ;;
    gcp)
        RUNNERS_FILE="${REPO_ROOT}/deploy/gcp-runners.env"
        SSH_USER="${GCP_SSH_USER:-$(whoami)}"
        ;;
    *)
        echo "ERROR: Unknown provider '${PROVIDER}'. Use 'linode' or 'gcp'."
        exit 1
        ;;
esac

if [ ! -f "${RUNNERS_FILE}" ]; then
    echo "ERROR: No runners file at ${RUNNERS_FILE}"
    echo "Run: ./deploy/${PROVIDER/linode/k6}-runner-setup.sh provision"
    exit 1
fi

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
RESULTS_DIR="${REPO_ROOT}/results/${PLATFORM}/multiregion_${TIMESTAMP}"
mkdir -p "${RESULTS_DIR}"

SUITE_LABEL=$( $RUN_FULL && echo "Full Suite" || echo "Reproduce Pipeline" )

echo "============================================"
echo "  WASMnism Multi-Region Benchmark"
echo "  Platform: ${PLATFORM}"
echo "  Gateway:  ${GATEWAY_URL}"
echo "  Provider: ${PROVIDER}"
echo "  Suite:    ${SUITE_LABEL}"
echo "  Flags:    ${EXTRA_FLAGS}"
echo "  Results:  ${RESULTS_DIR}"
echo "  Date:     $(date)"
echo "============================================"
echo ""

# Read runner labels and IPs into parallel arrays
RUNNER_LABELS=()
RUNNER_IPS=()
while IFS='=' read -r label ip; do
    [ -z "$label" ] && continue
    RUNNER_LABELS+=("$label")
    RUNNER_IPS+=("$ip")
done < "${RUNNERS_FILE}"

echo "Runners:"
for i in "${!RUNNER_LABELS[@]}"; do
    echo "  ${RUNNER_LABELS[$i]}: ${RUNNER_IPS[$i]}"
done
echo ""

region_from_label() { echo "$1" | sed 's/^k6-//'; }

# Launch reproduce.sh on each runner in parallel
PIDS=()
REGIONS=()
for i in "${!RUNNER_LABELS[@]}"; do
    label="${RUNNER_LABELS[$i]}"
    ip="${RUNNER_IPS[$i]}"
    region=$(region_from_label "$label")
    log="${RESULTS_DIR}/${region}.log"
    REGIONS+=("$region")

    echo "=== Launching on ${label} (${ip}, region=${region}) ==="

    if $RUN_FULL; then
        REMOTE_CMD="cd /opt/bench && ./run-full-suite.sh ${PLATFORM} ${GATEWAY_URL} ${EXTRA_FLAGS}"
    else
        REMOTE_CMD="cd /opt/bench && ./reproduce.sh ${PLATFORM} ${GATEWAY_URL} --region ${region} ${EXTRA_FLAGS}"
    fi

    ssh -o StrictHostKeyChecking=no "${SSH_USER}@${ip}" \
        "${REMOTE_CMD}" \
        > "${log}" 2>&1 &

    PIDS+=($!)
    echo "  PID: $!, log: ${log}"
done

echo ""
echo "=== Waiting for all runners to complete ==="
if $RUN_FULL; then
    echo "  (Full suite: ~32 min, +20 min with --cold)"
else
    echo "  (Reproduce: ~40 min, +20 min with --cold)"
fi
echo ""

FAILED=0
for i in "${!PIDS[@]}"; do
    pid="${PIDS[$i]}"
    if wait "$pid"; then
        echo "  PID ${pid} (${RUNNER_LABELS[$i]}): SUCCESS"
    else
        echo "  PID ${pid} (${RUNNER_LABELS[$i]}): FAILED (check log)"
        FAILED=$((FAILED + 1))
    fi
done

if [ "$FAILED" -gt 0 ]; then
    echo ""
    echo "WARNING: ${FAILED} runner(s) failed. Check logs in ${RESULTS_DIR}/"
fi

echo ""
echo "=== Collecting results from runners ==="

for i in "${!RUNNER_LABELS[@]}"; do
    label="${RUNNER_LABELS[$i]}"
    ip="${RUNNER_IPS[$i]}"
    region="${REGIONS[$i]}"
    region_dir="${RESULTS_DIR}/${region}"
    mkdir -p "${region_dir}"

    echo "  Collecting from ${label} (${ip})..."

    if $RUN_FULL; then
        # Full suite: collect the latest full_* directory
        REMOTE_FULL=$(ssh -o StrictHostKeyChecking=no "${SSH_USER}@${ip}" \
            "ls -td /opt/results/${PLATFORM}/full_* 2>/dev/null | head -1" || true)
        if [ -n "${REMOTE_FULL}" ]; then
            scp -o StrictHostKeyChecking=no -r "${SSH_USER}@${ip}:${REMOTE_FULL}" "${region_dir}/full/" 2>/dev/null || true
        fi
    else
        # Reproduce pipeline: collect 7run + medians + cold
        REMOTE_LATEST=$(ssh -o StrictHostKeyChecking=no "${SSH_USER}@${ip}" \
            "ls -td /opt/results/${PLATFORM}/7run_* 2>/dev/null | head -1" || true)
        if [ -n "${REMOTE_LATEST}" ]; then
            scp -o StrictHostKeyChecking=no -r "${SSH_USER}@${ip}:${REMOTE_LATEST}" "${region_dir}/7run/" 2>/dev/null || true
        fi
        scp -o StrictHostKeyChecking=no "${SSH_USER}@${ip}:/opt/results/${PLATFORM}/medians_${region}_"*.md "${region_dir}/" 2>/dev/null || true
        scp -o StrictHostKeyChecking=no "${SSH_USER}@${ip}:/opt/results/${PLATFORM}/cold_start/"*"_${region}.json" "${region_dir}/" 2>/dev/null || true
    fi
done

echo ""
echo "============================================"
echo "  Multi-Region Benchmark Complete"
echo "============================================"
echo ""
echo "  Results: ${RESULTS_DIR}/"
echo ""
echo "  Per-region:"
for i in "${!REGIONS[@]}"; do
    echo "    ${REGIONS[$i]}: ${RESULTS_DIR}/${REGIONS[$i]}/"
done
echo ""
echo "  Next steps:"
echo "    1. Review per-region medians in each region dir"
echo "    2. Compare platforms:"
echo "       python3 bench/build-scorecard.py ${RESULTS_DIR}/<region>/7run/ results/<other>/<region>/7run/"
echo ""
