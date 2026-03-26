#!/usr/bin/env bash
set -euo pipefail

# Usage: ./deploy.sh <linode-ip>
# Builds the native gateway in Docker, extracts the binary, deploys to Linode.

LINODE_IP="${1:?Usage: ./deploy.sh <linode-ip>}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "==> Building native gateway binary via Docker..."
docker build \
    -f "$PROJECT_ROOT/edge-gateway/adapters/native/Dockerfile" \
    -t gateway-native-builder \
    "$PROJECT_ROOT"

echo "==> Extracting binary from Docker image..."
CONTAINER_ID=$(docker create gateway-native-builder)
docker cp "$CONTAINER_ID:/usr/local/bin/gateway-native" /tmp/gateway-native
docker rm "$CONTAINER_ID" > /dev/null

echo "==> Uploading binary to $LINODE_IP..."
ssh "root@$LINODE_IP" "mkdir -p /opt/gateway-native"
scp /tmp/gateway-native "root@$LINODE_IP:/opt/gateway-native/gateway-native"
ssh "root@$LINODE_IP" "chmod +x /opt/gateway-native/gateway-native"

echo "==> Installing systemd service..."
scp "$SCRIPT_DIR/gateway-native.service" "root@$LINODE_IP:/etc/systemd/system/gateway-native.service"
ssh "root@$LINODE_IP" "systemctl daemon-reload && systemctl enable gateway-native && systemctl restart gateway-native"

echo "==> Waiting for service to start..."
sleep 2
ssh "root@$LINODE_IP" "systemctl status gateway-native --no-pager"

echo ""
echo "==> Smoke test..."
curl -sf "http://$LINODE_IP:3000/gateway/health" | python3 -m json.tool

echo ""
echo "==> Done! Native gateway running at http://$LINODE_IP:3000"
