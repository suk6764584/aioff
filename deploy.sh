#!/usr/bin/env bash
set -euo pipefail

cd /opt/aioff

echo "[1/5] Pull latest code"
git pull --ff-only origin main

echo "[2/5] Install/update dependencies"
.venv/bin/pip install -r requirements.txt

echo "[3/5] Syntax check"
.venv/bin/python -m py_compile app.py

echo "[4/5] Install/reload service"
if systemctl is-active --quiet aioff 2>/dev/null; then
  systemctl stop aioff
else
  pkill -f 'uvicorn app:app --host 0.0.0.0 --port 3000' 2>/dev/null || true
fi
cp -f aioff.service /etc/systemd/system/aioff.service
systemctl daemon-reload
systemctl enable aioff >/dev/null
systemctl restart aioff

sleep 2

echo "[5/5] Health check"
curl -fsS http://127.0.0.1:3000/health
echo
echo "DEPLOY OK"
