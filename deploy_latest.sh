#!/usr/bin/env bash
set -euo pipefail
cd /opt/aioff
git pull --ff-only origin main
exec bash /opt/aioff/deploy.sh
