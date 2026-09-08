#!/usr/bin/env bash
set -euo pipefail

cd /opt/aioff
PY=.venv/bin/python

if [ ! -x "$PY" ]; then
  echo "ERROR: $PY not found"
  exit 1
fi

MODE="${1:-validate}"
case "$MODE" in
  validate)
    "$PY" - <<'PY'
from pathlib import Path
from education_db import EducationDB

path = Path("data/education/education.db")
if not path.exists():
    raise SystemExit(f"ERROR: {path} not found")

db = EducationDB(path)
try:
    print(db.status())
finally:
    db.close()
PY
    ;;
  education-embed)
    exec "$PY" embed_education_db.py
    ;;
  *)
    echo "Usage: bash build_rag_data.sh [validate|education-embed]"
    echo "Source download/extraction are intentionally not bundled here; run their canonical scripts explicitly when a rebuild is actually required."
    exit 2
    ;;
esac
