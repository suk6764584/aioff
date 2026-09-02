#!/usr/bin/env bash
set -euo pipefail

cd /opt/aioff

echo "[1/7] Pull latest code"
git pull --ff-only origin main

echo "[2/7] Install/update dependencies"
.venv/bin/pip install -r requirements.txt

echo "[3/7] Prepare KOBACO Parquet snapshot"
KOBACO_DIR="/opt/aioff/raw_data/parquet_db"
mkdir -p "$KOBACO_DIR"
KOBACO_ARCHIVE=""
for candidate in kobaco_data.zip KOBACO_data.zip raw_data.Zip raw_data.zip; do
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
print(f"Extracted/updated {count} parquet files from {archive.name}")
PY
else
  echo "WARN: KOBACO parquet snapshot not found."
fi
KOBACO_COUNT=$(find "$KOBACO_DIR" -maxdepth 1 -type f -name '*.parquet' | wc -l | tr -d ' ')
echo "KOBACO parquet files: $KOBACO_COUNT"
if [ -f "$KOBACO_DIR/public_ad_master.parquet" ]; then
  echo "Official public-ad metadata: READY"
else
  echo "WARN: public_ad_master.parquet missing; individual archive/video matching will be limited."
fi

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

echo "[4/7] Syntax + topic + tutor integration check"
.venv/bin/python -m py_compile app.py literacy_app.py literacy_cases.py literacy_cases_2.py literacy_cases_3.py literacy_cases_4.py literacy_cases_5.py literacy_cases_6.py literacy_cases_7.py literacy_cases_8.py literacy_media_app.py literacy_media_app_2.py literacy_media_app_3.py literacy_media_app_4.py literacy_media_app_5.py literacy_media_app_6.py literacy_media_app_7.py literacy_media_app_8.py literacy_media_app_9.py literacy_media_app_10.py kobaco_db.py literacy_kobaco_app_1.py literacy_kobaco_app_2.py literacy_kobaco_app_3.py literacy_kobaco_app_4.py literacy_kobaco_app_5.py literacy_kobaco_app_6.py literacy_kobaco_app_7.py literacy_kobaco_app_8.py literacy_kobaco_app_9.py literacy_kobaco_app_10.py migrate_db.py
.venv/bin/python - <<'PY'
import literacy_kobaco_app_10 as m

expected = {
    'news': 'kobaco_aisac_',
    'deepfake': 'kobaco_publicad_',
    'ai': 'kobaco_ott_',
}
for lesson_id, prefix in expected.items():
    cases = m.flow.CASE_LIBRARY.get(lesson_id, [])
    ids = [str(c.get('id','')) for c in cases]
    print(f"{lesson_id}: {len(ids)} cases")
    if len(ids) < 3:
        raise SystemExit(f"ERROR: {lesson_id} has fewer than 3 cases")
    if not all(x.startswith(prefix) for x in ids):
        raise SystemExit(f"ERROR: {lesson_id} contains wrong case type: {ids}")

payload = m._topic_payload()
for lesson_id in expected:
    if len(payload.get(lesson_id, [])) < 3:
        raise SystemExit(f"ERROR: {lesson_id} payload missing")

page = m._render_index_kobaco_v10()
required_page_markers = (
    'fixedTopicCases',
    'AI가 읽은 광고',
    '청소년·OTT 통계',
    'kobaco_aisac_',
    'kobaco_publicad_',
    'kobaco_ott_',
    '실제 조사 원자료 항목 보기',
)
for marker in required_page_markers:
    if marker not in page:
        raise SystemExit(f"ERROR: root UI marker missing: {marker}")

if not hasattr(m, 'kobaco_ai_chat_stream'):
    raise SystemExit('ERROR: adaptive AI tutor route missing')
if hasattr(m, 'kobaco_instant_chat_stream'):
    raise SystemExit('ERROR: old canned instant tutor route is still exposed')

source = open('literacy_kobaco_app_10.py', encoding='utf-8').read()
if 'def _lesson_reply(' in source:
    raise SystemExit('ERROR: old canned lesson reply function still present')
if '첫 답변부터 퍼센트 숫자를 정답처럼 던지지 않는다' not in source:
    raise SystemExit('ERROR: public-ad pedagogy guard missing')

print('TOPIC MAPPING + UI + ADAPTIVE TUTOR OK')
PY

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

echo "[7/7] Health + live routing check"
curl -fsS http://127.0.0.1:3000/health
echo
curl -fsS http://127.0.0.1:3000/api/kobaco-status
echo
curl -fsS -o /tmp/aioff_root.html http://127.0.0.1:3000/
for marker in 'fixedTopicCases' 'AI가 읽은 광고' '청소년·OTT 통계' 'kobaco_aisac_' 'kobaco_publicad_' 'kobaco_ott_' '실제 조사 원자료 항목 보기'; do
  if ! grep -q "$marker" /tmp/aioff_root.html; then
    echo "ERROR: live root marker missing: $marker"
    exit 1
  fi
done
if grep -q 'kid-stat-grid' /tmp/aioff_root.html; then
  echo "ERROR: old forced typography/readability UI still active"
  exit 1
fi
if grep -q 'def _lesson_reply(' literacy_kobaco_app_10.py; then
  echo "ERROR: canned lesson reply still present"
  exit 1
fi
echo "ROOT PAGE + 3 TOPICS + ADAPTIVE AI TUTOR OK"
echo "DEPLOY OK"
