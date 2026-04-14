#!/usr/bin/env bash
set -euo pipefail

# Multi-region k6 benchmark runner infrastructure.
# Provisions 3 Linode Nanodes, installs k6 + Python 3, copies bench scripts.
#
# Usage:
#   ./deploy/k6-runner-setup.sh provision   # Create 3 runners, install k6, copy scripts
#   ./deploy/k6-runner-setup.sh status      # Show runner IPs and health
#   ./deploy/k6-runner-setup.sh sync        # Re-copy bench scripts to all runners
#   ./deploy/k6-runner-setup.sh teardown    # Destroy all runners
#
# Prerequisites: linode-cli configured with a valid token
# Runners file: deploy/runners.env (gitignored, created by provision)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
RUNNERS_FILE="${SCRIPT_DIR}/runners.env"
TAG="wasmnism-k6"
SSH_KEY="${HOME}/.ssh/id_ed25519"

# g6-dedicated-4: 4 dedicated vCPU, 8 GB — required for high-VU tests.
# g6-nanode-1 (1 shared vCPU) bottlenecks k6 before the platform, masking results.
# Override: LINODE_TYPE=g6-nanode-1 ./deploy/k6-runner-setup.sh provision
REGIONS=("us-ord" "eu-central" "ap-south")
LABELS=("k6-us-ord" "k6-eu-central" "k6-ap-south")

command_exists() { command -v "$1" &>/dev/null; }

check_prereqs() {
    local missing=()
    command_exists linode-cli || missing+=("linode-cli (pip install linode-cli)")
    command_exists ssh       || missing+=("ssh")
    command_exists scp       || missing+=("scp")
    if [ ${#missing[@]} -gt 0 ]; then
        echo "ERROR: Missing required tools:"
        for tool in "${missing[@]}"; do echo "  - $tool"; done
        exit 1
    fi
}

wait_for_running() {
    local id="$1"
    local label="$2"
    echo -n "  Waiting for ${label} to boot..."
    for i in $(seq 1 60); do
        local status
        status=$(linode-cli linodes view "$id" --json | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['status'])" 2>/dev/null || echo "unknown")
        if [ "$status" = "running" ]; then
            echo " running."
            return 0
        fi
        sleep 5
        echo -n "."
    done
    echo " TIMEOUT"
    return 1
}

get_ip() {
    local id="$1"
    linode-cli linodes view "$id" --json | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['ipv4'][0])"
}

install_k6_remote() {
    local ip="$1"
    local label="$2"
    echo "  Installing k6 + python3 on ${label} (${ip})..."
    # Wait for SSH to become available
    for i in $(seq 1 30); do
        if ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 "root@${ip}" "echo ok" &>/dev/null; then
            break
        fi
        sleep 5
    done

    ssh -o StrictHostKeyChecking=no "root@${ip}" bash -s << 'INSTALL'
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 curl gpg apt-transport-https
curl -fsSL https://dl.k6.io/key.gpg | gpg --dearmor -o /usr/share/keyrings/k6.gpg
echo 'deb [signed-by=/usr/share/keyrings/k6.gpg] https://dl.k6.io/deb stable main' > /etc/apt/sources.list.d/k6.list
apt-get update -qq
apt-get install -y -qq k6
mkdir -p /opt/bench/fixtures /opt/results
k6 version
echo "k6 install complete"
INSTALL
}

sync_scripts() {
    local ip="$1"
    local label="$2"
    echo "  Syncing bench scripts to ${label} (${ip})..."
    scp -o StrictHostKeyChecking=no \
        "${REPO_ROOT}/bench/"*.js \
        "${REPO_ROOT}/bench/"*.sh \
        "${REPO_ROOT}/bench/"*.py \
        "root@${ip}:/opt/bench/"
    # Make scripts executable
    ssh -o StrictHostKeyChecking=no "root@${ip}" "chmod +x /opt/bench/*.sh /opt/bench/*.py"
}

cmd_provision() {
    check_prereqs
    echo "=== Provisioning ${#REGIONS[@]} k6 runners ==="
    echo ""

    > "${RUNNERS_FILE}"

    for i in "${!REGIONS[@]}"; do
        region="${REGIONS[$i]}"
        label="${LABELS[$i]}"

        echo "--- Creating ${label} in ${region} ---"
        local result
        result=$(linode-cli linodes create \
            --type "${LINODE_TYPE:-g6-dedicated-4}" \
            --region "${region}" \
            --image linode/ubuntu24.04 \
            --root_pass "$(openssl rand -base64 24)" \
            --authorized_keys "$(cat "${SSH_KEY}.pub" 2>/dev/null || echo "")" \
            --label "${label}" \
            --tags "${TAG}" \
            --json)

        local id ip
        id=$(echo "$result" | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['id'])")
        echo "  Instance ID: ${id}"

        wait_for_running "$id" "$label"

        ip=$(get_ip "$id")
        echo "  IP: ${ip}"
        echo "${label}=${ip}" >> "${RUNNERS_FILE}"

        install_k6_remote "$ip" "$label"
        sync_scripts "$ip" "$label"

        echo "  ${label} ready."
        echo ""
    done

    echo "=== All runners provisioned ==="
    echo "Runner IPs saved to: ${RUNNERS_FILE}"
    cat "${RUNNERS_FILE}"
}

cmd_status() {
    if [ ! -f "${RUNNERS_FILE}" ]; then
        echo "No runners.env found. Run: $0 provision"
        exit 1
    fi

    echo "=== k6 Runner Status ==="
    while IFS='=' read -r label ip <&3; do
        [ -z "$label" ] && continue
        echo -n "  ${label} (${ip}): "
        if ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 "root@${ip}" "k6 version" 2>/dev/null; then
            echo "  OK"
        else
            echo "  UNREACHABLE"
        fi
    done 3< "${RUNNERS_FILE}"
}

cmd_sync() {
    if [ ! -f "${RUNNERS_FILE}" ]; then
        echo "No runners.env found. Run: $0 provision"
        exit 1
    fi

    echo "=== Syncing bench scripts to all runners ==="
    while IFS='=' read -r label ip <&3; do
        [ -z "$label" ] && continue
        sync_scripts "$ip" "$label"
    done 3< "${RUNNERS_FILE}"
    echo "=== Sync complete ==="
}

cmd_teardown() {
    check_prereqs
    echo "=== Tearing down k6 runners ==="

    local ids
    ids=$(linode-cli linodes list --tags "${TAG}" --json | python3 -c "
import sys, json
data = json.load(sys.stdin)
for d in data:
    print(d['id'], d['label'])
" 2>/dev/null || true)

    if [ -z "$ids" ]; then
        echo "No runners found with tag '${TAG}'."
    else
        while read -r id label; do
            echo "  Deleting ${label} (ID: ${id})..."
            linode-cli linodes delete "$id"
        done <<< "$ids"
    fi

    rm -f "${RUNNERS_FILE}"
    echo "=== Teardown complete ==="
}

case "${1:-help}" in
    provision) cmd_provision ;;
    status)    cmd_status ;;
    sync)      cmd_sync ;;
    teardown)  cmd_teardown ;;
    *)
        echo "Usage: $0 {provision|status|sync|teardown}"
        echo ""
        echo "  provision  Create 3 Linode k6 runners (us-ord, eu-central, ap-south)"
        echo "  status     Check runner health and k6 version"
        echo "  sync       Re-copy bench scripts to all runners"
        echo "  teardown   Destroy all runners"
        exit 1
        ;;
esac
