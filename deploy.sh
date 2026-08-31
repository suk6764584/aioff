#!/usr/bin/env bash
set -euo pipefail

cd /opt/aioff

echo "[1/6] Pull latest code"
git pull --ff-only origin main

echo "[2/6] Install/update dependencies"
.venv/bin/pip install -r requirements.txt

# Prototype mode: keep the existing API key, but use the lower-quota-cost model.
if [ -f .env ]; then
  if grep -q '^GEMINI_MODEL=' .env; then
    sed -i 's/^GEMINI_MODEL=.*/GEMINI_MODEL=gemini-3.5-flash-lite/' .env
  else
    printf '\nGEMINI_MODEL=gemini-3.5-flash-lite\n' >> .env
  fi
fi

echo "[3/6] Syntax check"
.venv/bin/python -m py_compile app.py migrate_db.py

echo "[4/6] Database migration"
.venv/bin/python migrate_db.py

echo "[5/6] Install/reload service"
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

echo "[6/6] Health check"
curl -fsS http://127.0.0.1:3000/health
echo
echo "DEPLOY OK"
