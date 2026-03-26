#!/usr/bin/env bash
set -euo pipefail

# Run benchmarks against both Fermyon Cloud (WASM) and Linode Native, then
# summarize side-by-side.
#
# Usage: ./run-comparison.sh
#   or:  LINODE_URL=http://x.x.x.x:3000 FERMYON_URL=https://... ./run-comparison.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

FERMYON_URL="${FERMYON_URL:-https://wasm-prompt-firewall-imjy4pe0.fermyon.app}"
LINODE_URL="${LINODE_URL:?Set LINODE_URL=http://<your-linode-ip>:3000}"

echo "========================================"
echo "  WASMnism Platform Comparison Benchmark"
echo "========================================"
echo ""
echo "  Fermyon (WASM): ${FERMYON_URL}"
echo "  Linode (native): ${LINODE_URL}"
echo ""

echo "--- Validation: Fermyon Cloud (WASM/Spin) ---"
"${SCRIPT_DIR}/run-validation.sh" spin "${FERMYON_URL}" || true
echo ""

echo "--- Validation: Linode (Native/Axum) ---"
"${SCRIPT_DIR}/run-validation.sh" linode "${LINODE_URL}" || true
echo ""

echo "--- Benchmark: Fermyon Cloud (WASM/Spin) ---"
"${SCRIPT_DIR}/run-benchmark.sh" spin "${FERMYON_URL}" us-ord
echo ""

echo "--- Benchmark: Linode (Native/Axum) ---"
"${SCRIPT_DIR}/run-benchmark.sh" linode "${LINODE_URL}" us-ord
echo ""

echo "========================================"
echo "  Comparison complete!"
echo "  Results: results/spin/us-ord/ vs results/linode/us-ord/"
echo "========================================"
