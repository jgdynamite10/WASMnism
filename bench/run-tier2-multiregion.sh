#!/usr/bin/env bash
# Tier 2 multi-region orchestrator (per docs/benchmark_contract_tier2.md v1.0).
#
# Runs the 5-scenario Tier 2 suite (bench/tier2-suite.sh) on each k6 runner in
# parallel, then collects the per-scenario JSON outputs back into:
#
#     results/<platform>/tier2_<timestamp>/<region>/<scenario>.json
#
# This shape is exactly what `bench/validate-results.py --deep-check` expects
# for a Tier 2 result directory.
#
# Usage:
#   ./bench/run-tier2-multiregion.sh <platform> <gateway-url> [OPTIONS]
#
# Required args:
#   platform      Tag/label (e.g. akamai-ml, lambda-ml). Used in result paths.
#   gateway-url   Base URL of the deployment under test.
#
# Options:
#   --provider linode|gcp        Runner infrastructure (default: gcp). Tier 2
#                                benchmarks should run from gcp only — neither
#                                Tier 2 platform is owned by Linode so the
#                                origin-bias rationale for dual-runner doesn't
#                                apply (see contract §8.6).
#   --cold-idle-seconds N        Override COLD_IDLE_SECONDS for cold-ml.js.
#                                Lambda needs ≥ 1200 for a true cold path; see
#                                contract §7.1. Default: 60.
#   --suite-flag '<flags>'       Pass arbitrary extra flags through to the
#                                runner-side tier2-suite.sh. Example:
#                                --suite-flag '--mixed-duration 2m'
#                                Quote the value as a single argument.
#
# Prerequisites:
#   - deploy/gcp-runners.env (or deploy/runners.env) populated by `make
#     gcp-runners-up` / `make runners-up`
#   - bench/* synced to runners via `make gcp-runners-sync` (copies *.js, *.sh,
#     *.py to /opt/bench)
#   - k6 installed on each runner (done by the provision step)
#
# Time budget per region (with default flags, sequential within a region):
#   cold-ml:           ~10 min  (10 iter × 60s idle, dominant component)
#   warm-ml:           ~1.5 min (30s warmup + 60s measure)
#   cache-hit:         ~30s     (~22 sequential requests)
#   mixed-load:        ~5 min   (5m @ 10 VUs)
#   clip-rules-only:   ~1 min   (60s @ 10 VUs)
#   ───────────────────────────
#   Total per region:  ~18 min (parallel across regions, so ≈ wall clock)
#
# With --cold-idle-seconds 1200 (Lambda true-cold path): per-region ≈ 3.5 hrs.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

PLATFORM="${1:?Usage: $0 <platform> <gateway-url> [--provider gcp|linode] [--cold-idle-seconds N] [--suite-flag '<flags>']}"
GATEWAY_URL="${2:?Usage: $0 <platform> <gateway-url> [--provider gcp|linode] [--cold-idle-seconds N] [--suite-flag '<flags>']}"

PROVIDER="gcp"
COLD_IDLE_SECONDS=""
SUITE_EXTRA_FLAGS=""

shift 2
while [ $# -gt 0 ]; do
    case "$1" in
        --provider)            PROVIDER="$2"; shift ;;
        --cold-idle-seconds)   COLD_IDLE_SECONDS="$2"; shift ;;
        --suite-flag)          SUITE_EXTRA_FLAGS="${SUITE_EXTRA_FLAGS} ${2}"; shift ;;
        *)
            echo "ERROR: unknown flag '$1'" >&2
            echo "       run with no args to see usage" >&2
            exit 1
            ;;
    esac
    shift
done

# ── Provider configuration ──────────────────────────────────────────────────
SSH_USER="root"
case "${PROVIDER}" in
    linode)
        RUNNERS_FILE="${REPO_ROOT}/deploy/runners.env"
        SSH_USER="root"
        ;;
    gcp)
        RUNNERS_FILE="${REPO_ROOT}/deploy/gcp-runners.env"
        SSH_USER="${GCP_SSH_USER:-$(whoami)}"
        ;;
    *)
        echo "ERROR: unknown provider '${PROVIDER}'. Use 'gcp' or 'linode'." >&2
        exit 1
        ;;
esac

if [ ! -f "${RUNNERS_FILE}" ]; then
    echo "ERROR: runners file not found: ${RUNNERS_FILE}" >&2
    echo "       Provision runners first: make ${PROVIDER}-runners-up" >&2
    exit 1
fi

# Single timestamp shared across all regions for this run.
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
RESULTS_DIR="${REPO_ROOT}/results/${PLATFORM}/tier2_${TIMESTAMP}"
mkdir -p "${RESULTS_DIR}"

# Build the suite command (sent verbatim over SSH).
# Defensive: assume nothing about the runner-side $PATH or cwd.
SUITE_FLAGS=""
if [ -n "${COLD_IDLE_SECONDS}" ]; then
    SUITE_FLAGS="${SUITE_FLAGS} --cold-idle-seconds ${COLD_IDLE_SECONDS}"
fi
SUITE_FLAGS="${SUITE_FLAGS}${SUITE_EXTRA_FLAGS}"

echo "============================================"
echo "  WASMnism Tier 2 Multi-Region Benchmark"
echo "  Platform:   ${PLATFORM}"
echo "  Gateway:    ${GATEWAY_URL}"
echo "  Provider:   ${PROVIDER}"
echo "  Timestamp:  ${TIMESTAMP}"
echo "  Results:    ${RESULTS_DIR}"
echo "  Suite flags:${SUITE_FLAGS:- (defaults)}"
echo "  Date:       $(date)"
echo "============================================"
echo ""

# ── Read runners (label=ip per line) ────────────────────────────────────────
RUNNER_LABELS=()
RUNNER_IPS=()
while IFS='=' read -r label ip; do
    [ -z "${label}" ] && continue
    case "${label}" in \#*) continue ;; esac
    RUNNER_LABELS+=("${label}")
    RUNNER_IPS+=("${ip}")
done < "${RUNNERS_FILE}"

if [ "${#RUNNER_LABELS[@]}" -eq 0 ]; then
    echo "ERROR: no runners listed in ${RUNNERS_FILE}" >&2
    exit 1
fi

echo "Runners:"
for i in "${!RUNNER_LABELS[@]}"; do
    echo "  ${RUNNER_LABELS[$i]}: ${RUNNER_IPS[$i]}"
done
echo ""

# Standard label → region mapping ("k6-gcp-us-east" → "gcp-us-east").
region_from_label() { echo "$1" | sed 's/^k6-//'; }

# ── Launch suite on each runner in parallel ─────────────────────────────────
PIDS=()
REGIONS=()
for i in "${!RUNNER_LABELS[@]}"; do
    label="${RUNNER_LABELS[$i]}"
    ip="${RUNNER_IPS[$i]}"
    region=$(region_from_label "${label}")
    log="${RESULTS_DIR}/${region}.launch.log"
    REGIONS+=("${region}")

    echo "=== Launching on ${label} (${ip}, region=${region}) ==="

    # The runner-side suite writes JSON outputs into
    # /opt/results/<platform>/tier2_<timestamp>_<region>/. We pull from there.
    REMOTE_CMD="cd /opt/bench && ./tier2-suite.sh ${PLATFORM} ${GATEWAY_URL} ${region} ${TIMESTAMP}${SUITE_FLAGS}"

    ssh -o StrictHostKeyChecking=no "${SSH_USER}@${ip}" \
        "${REMOTE_CMD}" \
        > "${log}" 2>&1 &

    PIDS+=($!)
    echo "  PID: $!  log: ${log}"
done

echo ""
echo "=== Waiting for runners to finish ==="
echo "  (estimate: ~18 min with default --cold-idle-seconds 60;"
echo "   ~3.5 hrs with --cold-idle-seconds 1200 for Lambda true-cold)"
echo ""

FAILED=0
SUITE_EXIT_CODES=()
for i in "${!PIDS[@]}"; do
    pid="${PIDS[$i]}"
    if wait "${pid}"; then
        SUITE_EXIT_CODES+=("0")
        echo "  ${RUNNER_LABELS[$i]} (PID ${pid}): SUCCESS (all 5 scenarios passed)"
    else
        rc=$?
        SUITE_EXIT_CODES+=("${rc}")
        echo "  ${RUNNER_LABELS[$i]} (PID ${pid}): FAILED (suite exit=${rc} — k6 may have failed in 1 or more scenarios; check launch log)"
        FAILED=$((FAILED + 1))
    fi
done

if [ "${FAILED}" -gt 0 ]; then
    echo ""
    echo "WARNING: ${FAILED}/${#PIDS[@]} runner(s) reported failures."
    echo "Pulling whatever results landed anyway — partial data is still useful."
fi

# ── Collect per-scenario JSON + log files from each runner ──────────────────
echo ""
echo "=== Collecting results from runners ==="

EXPECTED_SCENARIOS=(cold-ml warm-ml cache-hit mixed-load clip-rules-only)
COLLECTION_ERRORS=0

for i in "${!RUNNER_LABELS[@]}"; do
    ip="${RUNNER_IPS[$i]}"
    region="${REGIONS[$i]}"
    region_dir="${RESULTS_DIR}/${region}"
    mkdir -p "${region_dir}"

    remote_dir="/opt/results/${PLATFORM}/tier2_${TIMESTAMP}_${region}"
    echo "  ${region}: pulling from ${ip}:${remote_dir}/"

    # scp -r recursively grabs *.json and *.log; keep loose (some scenarios may
    # be missing on a partial failure) and let validate-results.py flag gaps.
    if ! scp -o StrictHostKeyChecking=no -r \
            "${SSH_USER}@${ip}:${remote_dir}/." \
            "${region_dir}/" 2>"${RESULTS_DIR}/${region}.scp.err"; then
        echo "    scp returned non-zero — check ${RESULTS_DIR}/${region}.scp.err"
        COLLECTION_ERRORS=$((COLLECTION_ERRORS + 1))
    fi

    # Quick local sanity report — list what landed.
    landed=()
    missing=()
    for s in "${EXPECTED_SCENARIOS[@]}"; do
        if [ -s "${region_dir}/${s}.json" ]; then
            landed+=("${s}")
        else
            missing+=("${s}")
        fi
    done
    echo "    landed: ${landed[*]:-none}"
    if [ "${#missing[@]}" -gt 0 ]; then
        echo "    MISSING: ${missing[*]}"
    fi
done

# ── Summary + validation hint ────────────────────────────────────────────────
echo ""
echo "============================================"
echo "  Tier 2 multi-region run complete"
echo "============================================"
echo ""
echo "  Results: ${RESULTS_DIR}/"
echo ""
echo "  Per-region:"
for i in "${!REGIONS[@]}"; do
    echo "    ${REGIONS[$i]}: ${RESULTS_DIR}/${REGIONS[$i]}/"
done

echo ""
echo "  Suite exit codes (one per region):"
for i in "${!REGIONS[@]}"; do
    echo "    ${REGIONS[$i]}: ${SUITE_EXIT_CODES[$i]}"
done

echo ""
echo "  Validate:"
echo "    python3 bench/validate-results.py --deep-check ${RESULTS_DIR}"
echo ""
echo "  Next:"
echo "    1. Review per-region JSON outputs"
echo "    2. Build Tier 2 scorecard (T2R6 — pending) once data validates"
echo ""

# Exit code reflects the most serious problem: any suite failure or scp error.
if [ "${FAILED}" -gt 0 ] || [ "${COLLECTION_ERRORS}" -gt 0 ]; then
    exit 1
fi
exit 0
