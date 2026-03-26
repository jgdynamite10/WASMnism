#!/usr/bin/env bash
set -euo pipefail

# Provision a Linode instance as a k6 benchmark runner.
# Usage: ./k6-runner-setup.sh <region> <label>
# Example: ./k6-runner-setup.sh us-ord k6-us-ord
#
# Regions used for multi-region testing:
#   us-ord    (Chicago, US Central)
#   eu-west   (London, Europe)
#   ap-south  (Singapore, Asia-Pacific)
#
# Prerequisites: linode-cli configured with valid token

REGION="${1:?Usage: $0 <region> <label>}"
LABEL="${2:?Usage: $0 <region> <label>}"

echo "=== Provisioning k6 runner: ${LABEL} in ${REGION} ==="

# Create a Linode (Nanode 1GB is sufficient for k6)
linode-cli linodes create \
  --type g6-nanode-1 \
  --region "${REGION}" \
  --image linode/ubuntu24.04 \
  --root_pass "$(openssl rand -base64 24)" \
  --label "${LABEL}" \
  --tags "wasmnism,k6-runner" \
  --json | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(f'Instance ID: {data[0][\"id\"]}')
print(f'IP: {data[0][\"ipv4\"][0]}')
print(f'Region: {data[0][\"region\"]}')
print(f'Status: {data[0][\"status\"]}')
"

echo ""
echo "=== After instance is running, SSH in and run: ==="
echo "ssh root@<IP>"
echo ""
echo "Then execute:"
echo "  curl -fsSL https://dl.k6.io/key.gpg | gpg --dearmor -o /usr/share/keyrings/k6.gpg"
echo "  echo 'deb [signed-by=/usr/share/keyrings/k6.gpg] https://dl.k6.io/deb stable main' > /etc/apt/sources.list.d/k6.list"
echo "  apt-get update && apt-get install -y k6"
echo "  mkdir -p /opt/bench/fixtures"
echo ""
echo "Then copy the benchmark files:"
echo "  scp bench/policy-only.js bench/cached-hit.js bench/full-pipeline.js root@<IP>:/opt/bench/"
echo "  scp bench/fixtures/benchmark.jpg root@<IP>:/opt/bench/fixtures/"
