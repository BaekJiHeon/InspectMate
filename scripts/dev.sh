#!/usr/bin/env bash
set -euo pipefail
INSPECTMATE_PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$INSPECTMATE_PROJECT"
if [ ! -d .venv ] || [ ! -d frontend/node_modules ]; then
  echo '먼저 uv sync --locked 및 (cd frontend && npm ci)를 실행하세요.'
  exit 1
fi
uv run --no-sync uvicorn inspectmate.api:app --host 127.0.0.1 --port 8740 &
INSPECTMATE_API_PID=$!
trap 'kill "$INSPECTMATE_API_PID" 2>/dev/null || true' EXIT INT TERM
cd frontend
npm run dev
