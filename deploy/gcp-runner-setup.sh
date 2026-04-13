#!/usr/bin/env bash
set -euo pipefail

# Multi-region k6 benchmark runner infrastructure on GCP.
# Provisions 3 GCP e2-standard-4 instances, installs k6 + Python 3, copies bench scripts.
#
# Usage:
#   ./deploy/gcp-runner-setup.sh provision   # Create 3 runners, install k6, copy scripts
#   ./deploy/gcp-runner-setup.sh status      # Show runner IPs and health
#   ./deploy/gcp-runner-setup.sh sync        # Re-copy bench scripts to all runners
#   ./deploy/gcp-runner-setup.sh teardown    # Destroy all runners
#
# Prerequisites: gcloud CLI configured with a project and credentials
# Runners file: deploy/gcp-runners.env (gitignored, created by provision)
#
# Why GCP? Using a neutral cloud provider (not owned by any CDN vendor)
# eliminates backbone bias when benchmarking edge platforms.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
RUNNERS_FILE="${SCRIPT_DIR}/gcp-runners.env"
LABEL_TAG="wasmnism-k6"
SSH_KEY="${HOME}/.ssh/id_ed25519"
SSH_USER="${GCP_SSH_USER:-$(whoami)}"

# e2-standard-4: 4 vCPU, 16 GB — handles up to ~1,000 VUs per runner.
# For 2,000+ VU spike tests, the orchestrator fans out across all 3 runners.
MACHINE_TYPE="${GCP_MACHINE_TYPE:-e2-standard-4}"

# GCP zones chosen to approximate the same cities as the Linode runners:
#   us-central1-a  (Iowa)      ↔ Linode us-ord (Chicago)
#   europe-west1-b (Belgium)   ↔ Linode eu-central (Frankfurt)
#   asia-southeast1-a (Singapore) ↔ Linode ap-south (Singapore)
ZONES=("us-central1-a" "europe-west1-b" "asia-southeast1-a")
NAMES=("k6-gcp-us-central" "k6-gcp-eu-west" "k6-gcp-ap-southeast")

command_exists() { command -v "$1" &>/dev/null; }

check_prereqs() {
    local missing=()
    command_exists gcloud || missing+=("gcloud (https://cloud.google.com/sdk/docs/install)")
    command_exists ssh    || missing+=("ssh")
    command_exists scp    || missing+=("scp")
    if [ ${#missing[@]} -gt 0 ]; then
        echo "ERROR: Missing required tools:"
        for tool in "${missing[@]}"; do echo "  - $tool"; done
        exit 1
    fi

    local project
    project=$(gcloud config get-value project 2>/dev/null || true)
    if [ -z "$project" ] || [ "$project" = "(unset)" ]; then
        echo "ERROR: No GCP project set. Run: gcloud config set project <project-id>"
        exit 1
    fi
    echo "  GCP project: ${project}"
}

wait_for_running() {
    local name="$1" zone="$2"
    echo -n "  Waiting for ${name} to boot..."
    for _ in $(seq 1 60); do
        local status
        status=$(gcloud compute instances describe "$name" --zone="$zone" \
            --format="value(status)" 2>/dev/null || echo "UNKNOWN")
        if [ "$status" = "RUNNING" ]; then
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
    local name="$1" zone="$2"
    gcloud compute instances describe "$name" --zone="$zone" \
        --format="value(networkInterfaces[0].accessConfigs[0].natIP)"
}

install_k6_remote() {
    local ip="$1" name="$2"
    echo "  Installing k6 + python3 on ${name} (${ip})..."
    for _ in $(seq 1 30); do
        if ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 "${SSH_USER}@${ip}" "echo ok" &>/dev/null; then
            break
        fi
        sleep 5
    done

    ssh -o StrictHostKeyChecking=no "${SSH_USER}@${ip}" bash -s << 'INSTALL'
export DEBIAN_FRONTEND=noninteractive
sudo apt-get update -qq
sudo apt-get install -y -qq python3 curl gpg apt-transport-https
curl -fsSL https://dl.k6.io/key.gpg | sudo gpg --dearmor -o /usr/share/keyrings/k6.gpg
echo 'deb [signed-by=/usr/share/keyrings/k6.gpg] https://dl.k6.io/deb stable main' | sudo tee /etc/apt/sources.list.d/k6.list
sudo apt-get update -qq
sudo apt-get install -y -qq k6
sudo mkdir -p /opt/bench/fixtures
sudo chown -R $(whoami):$(whoami) /opt/bench
k6 version
echo "k6 install complete"
INSTALL
}

sync_scripts() {
    local ip="$1" name="$2"
    echo "  Syncing bench scripts to ${name} (${ip})..."
    scp -o StrictHostKeyChecking=no \
        "${REPO_ROOT}/bench/"*.js \
        "${REPO_ROOT}/bench/"*.sh \
        "${REPO_ROOT}/bench/"*.py \
        "${SSH_USER}@${ip}:/opt/bench/"
    ssh -o StrictHostKeyChecking=no "${SSH_USER}@${ip}" "chmod +x /opt/bench/*.sh /opt/bench/*.py"
}

cmd_provision() {
    check_prereqs
    echo ""
    echo "=== Provisioning ${#ZONES[@]} GCP k6 runners (${MACHINE_TYPE}) ==="
    echo ""

    > "${RUNNERS_FILE}"

    for i in "${!ZONES[@]}"; do
        zone="${ZONES[$i]}"
        name="${NAMES[$i]}"

        echo "--- Creating ${name} in ${zone} ---"
        gcloud compute instances create "$name" \
            --zone="$zone" \
            --machine-type="$MACHINE_TYPE" \
            --image-family=ubuntu-2404-lts-amd64 \
            --image-project=ubuntu-os-cloud \
            --boot-disk-size=20GB \
            --labels="purpose=${LABEL_TAG}" \
            --tags="${LABEL_TAG}" \
            --quiet

        wait_for_running "$name" "$zone"

        local ip
        ip=$(get_ip "$name" "$zone")
        echo "  IP: ${ip}"
        echo "${name}=${ip}" >> "${RUNNERS_FILE}"

        install_k6_remote "$ip" "$name"
        sync_scripts "$ip" "$name"

        echo "  ${name} ready."
        echo ""
    done

    echo "=== All GCP runners provisioned ==="
    echo "Runner IPs saved to: ${RUNNERS_FILE}"
    cat "${RUNNERS_FILE}"
}

cmd_status() {
    if [ ! -f "${RUNNERS_FILE}" ]; then
        echo "No gcp-runners.env found. Run: $0 provision"
        exit 1
    fi

    echo "=== GCP k6 Runner Status ==="
    while IFS='=' read -r name ip <&3; do
        [ -z "$name" ] && continue
        echo -n "  ${name} (${ip}): "
        if ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 "${SSH_USER}@${ip}" "k6 version" 2>/dev/null; then
            echo "  OK"
        else
            echo "  UNREACHABLE"
        fi
    done 3< "${RUNNERS_FILE}"
}

cmd_sync() {
    if [ ! -f "${RUNNERS_FILE}" ]; then
        echo "No gcp-runners.env found. Run: $0 provision"
        exit 1
    fi

    echo "=== Syncing bench scripts to all GCP runners ==="
    while IFS='=' read -r name ip <&3; do
        [ -z "$name" ] && continue
        sync_scripts "$ip" "$name"
    done 3< "${RUNNERS_FILE}"
    echo "=== Sync complete ==="
}

cmd_teardown() {
    check_prereqs
    echo "=== Tearing down GCP k6 runners ==="

    for i in "${!ZONES[@]}"; do
        zone="${ZONES[$i]}"
        name="${NAMES[$i]}"
        echo "  Deleting ${name} in ${zone}..."
        gcloud compute instances delete "$name" --zone="$zone" --quiet 2>/dev/null || true
    done

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
        echo "  provision  Create 3 GCP k6 runners (us-central1, europe-west1, asia-southeast1)"
        echo "  status     Check runner health and k6 version"
        echo "  sync       Re-copy bench scripts to all runners"
        echo "  teardown   Destroy all runners"
        echo ""
        echo "Environment variables:"
        echo "  GCP_SSH_USER      SSH username (default: current user)"
        echo "  GCP_MACHINE_TYPE  Instance type (default: e2-standard-4)"
        exit 1
        ;;
esac
