#!/usr/bin/env bash
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

echo "=== Installing system dependencies ==="
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv libsndfile1 ffmpeg git

echo "=== Creating app directory ==="
mkdir -p /opt/clipclap
cd /opt/clipclap

echo "=== Setting up Python venv ==="
python3 -m venv venv
./venv/bin/pip install --upgrade pip setuptools wheel -q

echo "=== Installing Python dependencies ==="
./venv/bin/pip install -r /tmp/clipclap-backend/requirements.txt -q

echo "=== Copying application code ==="
cp -r /tmp/clipclap-backend/app /opt/clipclap/app

echo "=== Creating systemd service ==="
cat > /etc/systemd/system/clipclap.service << 'UNIT'
[Unit]
Description=ClipClap Inference Service
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/clipclap
ExecStart=/opt/clipclap/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable clipclap
systemctl start clipclap

echo "=== Configuring firewall ==="
apt-get install -y -qq ufw
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw allow 8000/tcp
ufw --force enable

echo "=== Setup complete ==="
echo "Inference service running on port 8000"
echo "It may take a minute for models to load on first request."
