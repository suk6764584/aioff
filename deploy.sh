#!/usr/bin/env bash
set -euo pipefail

cd /opt/aioff

echo "[1/6] Pull latest code"
git pull --ff-only origin main

echo "[2/6] Install/update dependencies"
.venv/bin/pip install -r requirements.txt

# Prototype mode: keep secret keys, but pin the free-tier models.
if [ -f .env ]; then
  if grep -q '^GEMINI_MODEL=' .env; then
    sed -i 's/^GEMINI_MODEL=.*/GEMINI_MODEL=gemini-3.5-flash-lite/' .env
  else
    printf '\nGEMINI_MODEL=gemini-3.5-flash-lite\n' >> .env
  fi

  if grep -q '^GROQ_MODEL=' .env; then
    sed -i 's#^GROQ_MODEL=.*#GROQ_MODEL=openai/gpt-oss-20b#' .env
  else
    printf 'GROQ_MODEL=openai/gpt-oss-20b\n' >> .env
  fi
fi

echo "[3/6] Syntax check"
.venv/bin/python -m py_compile app.py literacy_app.py literacy_cases.py literacy_cases_2.py literacy_cases_3.py literacy_cases_4.py literacy_cases_5.py literacy_media_app.py literacy_media_app_2.py literacy_media_app_3.py literacy_media_app_4.py literacy_media_app_5.py literacy_media_app_6.py migrate_db.py

echo "[4/6] Database migration"
.venv/bin/python migrate_db.py

echo "[5/6] Install/reload service"
if systemctl is-active --quiet aioff 2>/dev/null; then
  systemctl stop aioff
else
  pkill -f 'uvicorn .*:app --host 0.0.0.0 --port 3000' 2>/dev/null || true
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
