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
    "$PY" build_education_db.py --list-only
    ;;
  build)
    "$PY" build_education_db.py --download --extract --embed
    "$PY" build_news_db.py --days 14 --embed
    "$PY" link_news_education.py
    ;;
  refresh-news)
    "$PY" build_news_db.py --days 14 --embed
    "$PY" link_news_education.py
    ;;
  *)
    echo "Usage: bash build_rag_data.sh [validate|build|refresh-news]"
    exit 2
    ;;
esac
