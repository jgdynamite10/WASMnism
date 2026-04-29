#!/usr/bin/env bash
# Tier 2 suite — runner-side execution.
#
# Runs all 5 Tier 2 k6 scenarios sequentially on a single k6 runner (Linode/GCP)
# and writes one JSON output per scenario into a per-run directory.
#
# Designed to be invoked over SSH by bench/run-tier2-multiregion.sh, but is also
# usable standalone for runner-side debugging.
#
# Usage:
#   ./tier2-suite.sh <platform> <gateway-url> <region> <timestamp> [k6-flags ...]
#
# Args:
#   platform      Tag/label for the deployment under test (e.g. akamai-ml, lambda-ml).
#                 Becomes part of the output path AND the PLATFORM env var passed
#                 into each k6 script for tagging metrics.
#   gateway-url   Base URL of the deployment (e.g. https://f9318a6c-…fwf.app).
#   region        Logical region the runner represents (e.g. gcp-us-east). Becomes
#                 part of the output path so multiple regions don't clash on disk.
#   timestamp     YYYYMMDD_HHMMSS — set by the orchestrator so all regions in one
#                 multi-region run share the same root timestamp.
#
# Optional flags (forwarded as env vars to the matching k6 script):
#   --cold-iterations N     default 10  (cold-ml.js → COLD_ITERATIONS)
#   --cold-idle-seconds N   default 60  (cold-ml.js → COLD_IDLE_SECONDS)
#                           Lambda needs ≥ 1200 for true cold path; see
#                           docs/benchmark_contract_tier2.md §7.1
#   --warm-vus N            default 5   (warm-ml.js → WARM_VUS)
#   --warm-duration <dur>   default 60s (warm-ml.js → WARM_DURATION)
#   --warmup-duration <dur> default 30s (warm-ml.js → WARMUP_DURATION)
#   --n-prime N             default 2   (cache-hit.js → N_PRIME)
#   --n-hit N               default 20  (cache-hit.js → N_HIT)
#   --mixed-vus N           default 10  (mixed-load.js → MIXED_VUS)
#   --mixed-duration <dur>  default 5m  (mixed-load.js → MIXED_DURATION)
#   --clip-vus N            default 10  (clip-rules-only.js → CLIP_VUS)
#   --clip-duration <dur>   default 60s (clip-rules-only.js → CLIP_DURATION)
#
# Output:
#   /opt/results/<platform>/tier2_<timestamp>_<region>/<scenario>.json    (k6 JSON metrics)
#   /opt/results/<platform>/tier2_<timestamp>_<region>/<scenario>.log     (k6 stdout/stderr)
#
# Exit codes:
#   0   all 5 scenarios completed (k6 may have logged threshold breaches; check logs)
#   N>0 number of scenarios that failed to launch or wrote unreadable output
#
# Last line of stdout is always the absolute path of the output directory, so the
# orchestrator can capture it via `tail -1` regardless of intermediate logging.

set -euo pipefail

PLATFORM="${1:?Usage: $0 <platform> <gateway-url> <region> <timestamp> [flags]}"
GATEWAY_URL="${2:?Usage: $0 <platform> <gateway-url> <region> <timestamp> [flags]}"
REGION="${3:?Usage: $0 <platform> <gateway-url> <region> <timestamp> [flags]}"
TIMESTAMP="${4:?Usage: $0 <platform> <gateway-url> <region> <timestamp> [flags]}"
shift 4

# Defaults match docs/benchmark_contract_tier2.md SLO sections 7.1–7.4.
COLD_ITERATIONS="${COLD_ITERATIONS:-10}"
COLD_IDLE_SECONDS="${COLD_IDLE_SECONDS:-60}"
WARM_VUS="${WARM_VUS:-5}"
WARM_DURATION="${WARM_DURATION:-60s}"
WARMUP_DURATION="${WARMUP_DURATION:-30s}"
N_PRIME="${N_PRIME:-2}"
N_HIT="${N_HIT:-20}"
MIXED_VUS="${MIXED_VUS:-10}"
MIXED_DURATION="${MIXED_DURATION:-5m}"
CLIP_VUS="${CLIP_VUS:-10}"
CLIP_DURATION="${CLIP_DURATION:-60s}"

while [ $# -gt 0 ]; do
    case "$1" in
        --cold-iterations)    COLD_ITERATIONS="$2"; shift ;;
        --cold-idle-seconds)  COLD_IDLE_SECONDS="$2"; shift ;;
        --warm-vus)           WARM_VUS="$2"; shift ;;
        --warm-duration)      WARM_DURATION="$2"; shift ;;
        --warmup-duration)    WARMUP_DURATION="$2"; shift ;;
        --n-prime)            N_PRIME="$2"; shift ;;
        --n-hit)              N_HIT="$2"; shift ;;
        --mixed-vus)          MIXED_VUS="$2"; shift ;;
        --mixed-duration)     MIXED_DURATION="$2"; shift ;;
        --clip-vus)           CLIP_VUS="$2"; shift ;;
        --clip-duration)      CLIP_DURATION="$2"; shift ;;
        *)
            echo "ERROR: unknown flag: $1" >&2
            exit 2
            ;;
    esac
    shift
done

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Output directory shape mirrors the orchestrator's expected layout so its
# scp commands can be deterministic without parsing this script's stdout.
OUTDIR="/opt/results/${PLATFORM}/tier2_${TIMESTAMP}_${REGION}"
mkdir -p "${OUTDIR}"

echo "============================================"
echo "  Tier 2 suite (runner-side)"
echo "  Platform:   ${PLATFORM}"
echo "  Gateway:    ${GATEWAY_URL}"
echo "  Region:     ${REGION}"
echo "  Timestamp:  ${TIMESTAMP}"
echo "  Output:     ${OUTDIR}"
echo "  Started:    $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "  Defaults:"
echo "    COLD_ITERATIONS=${COLD_ITERATIONS} COLD_IDLE_SECONDS=${COLD_IDLE_SECONDS}"
echo "    WARM_VUS=${WARM_VUS} WARM_DURATION=${WARM_DURATION} WARMUP_DURATION=${WARMUP_DURATION}"
echo "    N_PRIME=${N_PRIME} N_HIT=${N_HIT}"
echo "    MIXED_VUS=${MIXED_VUS} MIXED_DURATION=${MIXED_DURATION}"
echo "    CLIP_VUS=${CLIP_VUS} CLIP_DURATION=${CLIP_DURATION}"
echo "============================================"

# Export everything k6 needs via __ENV.
export GATEWAY_URL PLATFORM
export COLD_ITERATIONS COLD_IDLE_SECONDS
export WARM_VUS WARM_DURATION WARMUP_DURATION
export N_PRIME N_HIT
export MIXED_VUS MIXED_DURATION
export CLIP_VUS CLIP_DURATION

# Scenario order is intentional:
#   1. cold-ml first   — measure true cold path before any warmup contaminates state
#   2. warm-ml next    — has its own internal warmup phase, but starts from a now-
#                        primed-by-cold-ml runtime which is realistic
#   3. cache-hit       — short, primes its own KV state
#   4. mixed-load      — longest, exercises real production shape
#   5. clip-rules-only — last; rules-only baseline; doesn't depend on prior state
SCENARIOS=(cold-ml warm-ml cache-hit mixed-load clip-rules-only)

FAILURES=0
for s in "${SCENARIOS[@]}"; do
    echo ""
    echo "── ${s} (started $(date -u +%H:%M:%SZ)) ──"
    if k6 run \
            --quiet \
            --out "json=${OUTDIR}/${s}.json" \
            "${SCRIPT_DIR}/${s}.js" \
            > "${OUTDIR}/${s}.log" 2>&1; then
        echo "   PASS — ${OUTDIR}/${s}.json"
    else
        rc=$?
        echo "   FAIL (k6 exit=${rc}) — see ${OUTDIR}/${s}.log"
        FAILURES=$((FAILURES + 1))
    fi
done

echo ""
echo "============================================"
echo "  Tier 2 suite complete"
echo "  Failures: ${FAILURES}/${#SCENARIOS[@]}"
echo "  Finished: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "============================================"

# Last line is always the output directory — orchestrator captures via tail -1.
echo "${OUTDIR}"

exit "${FAILURES}"
