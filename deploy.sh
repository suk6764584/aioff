#!/usr/bin/env bash
set -euo pipefail

cd /opt/aioff

echo "[1/6] Pull latest code"
git pull --ff-only origin main

echo "[2/6] Install/update dependencies"
.venv/bin/pip install -r requirements.txt

echo "[3/6] Prepare KOBACO Parquet snapshot"
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
print(f"KOBACO parquet updated: {count}")
PY
else
  echo "WARN: KOBACO parquet snapshot archive not found; existing parquet files are kept."
fi

echo "[4/6] Validate current application"
.venv/bin/python -m py_compile \
  app.py literacy_app.py aioff_ui.py aioff_runtime.py news_learning.py aioff_entry.py \
  auth_proto.py education_db.py kobaco_db.py news_db.py \
  education_archive_parser.py download_education_sources.py extract_education_sources.py \
  embed_education_db.py build_news_db.py link_news_education.py

.venv/bin/python - <<'PY'
import education_archive_parser
import download_education_sources
import aioff_entry as entry
import aioff_ui as m

assert entry.app is m.app
assert education_archive_parser.LIST_URL
assert download_education_sources.DETAIL_URL

expected = {
    'news': 'kobaco_aisac_',
    'deepfake': 'education_',
}
for lesson_id, prefix in expected.items():
    ids = [str(c.get('id', '')) for c in m.flow.CASE_LIBRARY.get(lesson_id, [])]
    if len(ids) < 3:
        raise SystemExit(f"ERROR: {lesson_id} has fewer than 3 cases")
    if not all(x.startswith(prefix) for x in ids):
        raise SystemExit(f"ERROR: {lesson_id} contains unexpected case ids")
    print(f"{lesson_id}: {len(ids)} cases")

# aioff_runtime replaces the third topic with current news cases at import time.
import aioff_runtime as runtime
news_ids = [str(c.get('id', '')) for c in runtime.flow.CASE_LIBRARY.get('ai', [])]
if len(news_ids) < 3 or not all(x.startswith('news_') for x in news_ids):
    raise SystemExit('ERROR: latest-news cases are not loaded')
print(f"ai: {len(news_ids)} news cases")

page = runtime._render_runtime_index()
for marker in (
    'AI가 읽은 광고',
    '리터러시 교육 안내서',
    '최신 뉴스에서 사실과 해석 구분하기',
    'LOGIN OFF',
    'aioff-learning-columns',
    'aioff-composer-side',
):
    if marker not in page:
        raise SystemExit(f"ERROR: root UI marker missing: {marker}")
if '<section class="process" aria-label="이용 순서">' in page:
    raise SystemExit('ERROR: progress rail still rendered')
if '<aside class="study-side">' in page:
    raise SystemExit('ERROR: old right study sidebar still rendered')

route_paths = {getattr(route, 'path', '') for route in m.app.routes}
for path in (
    '/api/auth/me',
    '/api/auth/login',
    '/api/auth/register',
    '/api/auth/logout',
    '/api/auth/schools',
    '/api/case-start',
    '/api/aioff-education-cases',
    '/api/education-learning/{case_id}',
    '/api/education-file/{case_id}',
    '/api/chat-stream',
    '/api/analyze',
    '/api/off-test',
    '/api/off-submit',
):
    if path not in route_paths:
        raise SystemExit(f"ERROR: route missing: {path}")

print('FLATTENED ENTRY + ROUTE + LAYOUT CHECK OK')
PY

echo "[5/6] Install/restart service"
/bin/cp -f aioff.service /etc/systemd/system/aioff.service
systemctl daemon-reload
systemctl enable aioff >/dev/null
systemctl restart aioff

echo "[6/6] Health check"
ok=0
for _ in $(seq 1 20); do
  if curl -fsS --max-time 5 http://127.0.0.1:3000/health >/tmp/aioff_health.json 2>/dev/null; then
    ok=1
    break
  fi
  sleep 1
done

if [ "$ok" -ne 1 ]; then
  echo "ERROR: service did not become healthy"
  systemctl status aioff --no-pager -l || true
  exit 1
fi

cat /tmp/aioff_health.json
echo
curl -fsS --max-time 5 http://127.0.0.1:3000/api/auth/me
echo

if ! grep -q 'aioff_entry:app' /etc/systemd/system/aioff.service; then
  echo "ERROR: service is not pointing to aioff_entry"
  exit 1
fi

echo "DEPLOY OK: aioff_entry"
