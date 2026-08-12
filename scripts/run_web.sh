#!/usr/bin/env bash
# Launch the MARI · Voice front-end (sleek tap-to-speak UI).
# Runs in demo mode out of the box; wire server/app.py:bridge_to_s2s for the
# full speech-to-speech pipeline.
set -euo pipefail
cd "$(dirname "$0")/.."

HOST="${MARI_HOST:-127.0.0.1}"
PORT="${MARI_PORT:-8010}"

# Prefer a Python 3.12 venv with Kokoro (short path C:\mv312 avoids Windows path limit)
if   [ -n "${MARI_PYTHON:-}" ] && [ -x "${MARI_PYTHON}" ]; then PY="$MARI_PYTHON"
elif [ -x "/c/mv312/Scripts/python.exe" ]; then PY="/c/mv312/Scripts/python.exe"
elif [ -x ".venv312/Scripts/python.exe" ]; then PY=".venv312/Scripts/python.exe"
elif [ -x ".venv312/bin/python" ]; then PY=".venv312/bin/python"
else PY="python"; fi

echo "MARI · Voice  →  http://${HOST}:${PORT}   (python: $PY)"
exec "$PY" -m uvicorn server.app:app --host "$HOST" --port "$PORT"
