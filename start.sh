#!/usr/bin/env bash
# Trip Share local starter (Linux / macOS / CloudStudio).
set -e
cd "$(dirname "$0")"

PORT="${PORT:-8765}"
export PORT

PYTHON="${PYTHON:-python3}"

echo "[setup] installing dependencies ..."
$PYTHON -m pip install -r requirements.txt

echo "[start] Trip Share on http://localhost:$PORT"
exec $PYTHON server.py
