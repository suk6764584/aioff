#!/usr/bin/env bash
set -euo pipefail

cd /opt/aioff

echo "[1/7] Pull latest code"
git pull --ff-only origin main

echo "[2/7] Install/update dependencies"
.venv/bin/pip install -r requirements.txt

# KOBACO data is intentionally kept out of Git. If a snapshot zip was copied
# next to deploy.sh, unpack only parquet files into the local data directory.
echo "[3/7] Prepare KOBACO Parquet snapshot"
KOBACO_DIR="/opt/aioff/raw_data/parquet_db"
mkdir -p "$KOBACO_DIR"
if ! compgen -G "$KOBACO_DIR/*.parquet" >/dev/null; then
  KOBACO_ARCHIVE=""
  for candidate in raw_data.Zip raw_data.zip kobaco_data.zip KOBACO_data.zip; do
    if [ -f "/opt/aioff/$candidate" ]; then
      KOBACO_ARCHIVE="/opt/aioff/$candidate"
      break
    fi
  done

  if [ -n "$KOBACO_ARCHIVE" ]; then
    .venv/bin/python - "$KOBACO_ARCHIVE" "$KOBACO_DIR" <<'PY'
from pathlib import Path
import sys
import zipfile

archive = Path(sys.argv[1])
out_dir = Path(sys.argv[2])
out_dir.mkdir(parents=True, exist_ok=True)
count = 0
with zipfile.ZipFile(archive) as zf:
    for info in zf.infolist():
        name = info.filename.replace('\\', '/')
        if not name.lower().endswith('.parquet') or 'parquet_db/' not in name:
            continue
        target = out_dir / Path(name).name
        with zf.open(info) as src, target.open('wb') as dst:
            while True:
                chunk = src.read(1024 * 1024)
                if not chunk:
                    break
                dst.write(chunk)
        count += 1
print(f"Extracted {count} parquet files from {archive.name}")
PY
  else
    echo "WARN: KOBACO parquet snapshot not found. Copy raw_data.Zip to /opt/aioff to activate DB-backed lessons."
  fi
fi
KOBACO_COUNT=$(find "$KOBACO_DIR" -maxdepth 1 -type f -name '*.parquet' | wc -l | tr -d ' ')
echo "KOBACO parquet files: $KOBACO_COUNT"

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

echo "[4/7] Syntax check"
.venv/bin/python -m py_compile app.py literacy_app.py literacy_cases.py literacy_cases_2.py literacy_cases_3.py literacy_cases_4.py literacy_cases_5.py literacy_cases_6.py literacy_cases_7.py literacy_cases_8.py literacy_media_app.py literacy_media_app_2.py literacy_media_app_3.py literacy_media_app_4.py literacy_media_app_5.py literacy_media_app_6.py literacy_media_app_7.py literacy_media_app_8.py literacy_media_app_9.py literacy_media_app_10.py kobaco_db.py literacy_kobaco_app_1.py migrate_db.py

echo "[5/7] Database migration"
.venv/bin/python migrate_db.py

echo "[6/7] Install/reload service"
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

echo "[7/7] Health + KOBACO status check"
curl -fsS http://127.0.0.1:3000/health
echo
curl -fsS http://127.0.0.1:3000/api/kobaco-status || true
echo
echo "DEPLOY OK"
