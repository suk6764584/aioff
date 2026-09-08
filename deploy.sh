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
  literacy_kobaco_app_20.py literacy_kobaco_app_19.py literacy_kobaco_app_18.py \
  literacy_kobaco_app_17.py auth_proto.py education_db.py kobaco_db.py migrate_db.py

.venv/bin/python - <<'PY'
import literacy_kobaco_app_20 as m

assert m.app is not None

expected = {
    'news': 'kobaco_aisac_',
    'deepfake': 'education_',
    'ai': 'kobaco_ott_',
}
for lesson_id, prefix in expected.items():
    cases = m.flow.CASE_LIBRARY.get(lesson_id, [])
    ids = [str(c.get('id', '')) for c in cases]
    if len(ids) < 3:
        raise SystemExit(f"ERROR: {lesson_id} has fewer than 3 cases")
    if not all(x.startswith(prefix) for x in ids):
        raise SystemExit(f"ERROR: {lesson_id} contains unexpected case ids")
    print(f"{lesson_id}: {len(ids)} cases")

page = m._render_index_kobaco_v20()
for marker in (
    'AI가 읽은 광고',
    '리터러시 교육 안내서',
    '청소년·OTT 통계',
    'LOGIN OFF',
    'education_',
):
    if marker not in page:
        raise SystemExit(f"ERROR: root UI marker missing: {marker}")

route_paths = {getattr(route, 'path', '') for route in m.app.routes}
for path in (
    '/api/auth/me',
    '/api/auth/login',
    '/api/auth/register',
    '/api/auth/logout',
    '/api/auth/schools',
    '/api/education-learning/{case_id}',
    '/api/education-activity-pdf/{case_id}',
    '/api/chat-stream',
    '/api/analyze',
    '/api/off-test',
    '/api/off-submit',
):
    if path not in route_paths:
        raise SystemExit(f"ERROR: route missing: {path}")

print('IMPORT + ROUTE + ROOT CHECK OK')
PY

.venv/bin/python migrate_db.py

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

if ! grep -q 'literacy_kobaco_app_20:app' /etc/systemd/system/aioff.service; then
  echo "ERROR: service is not pointing to v20"
  exit 1
fi

echo "DEPLOY OK: literacy_kobaco_app_20"
