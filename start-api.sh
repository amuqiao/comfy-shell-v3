#!/usr/bin/env sh
set -eu

APP_MODULE="${APP_MODULE:-app.main:app}"
HOST="${API_HOST:-0.0.0.0}"
PORT="${API_PORT:-8100}"
WORKERS="${API_WORKERS:-1}"
LOG_LEVEL="$(printf '%s' "${OBSERVABILITY__LOG_LEVEL:-info}" | tr '[:upper:]' '[:lower:]')"

if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
  uv run alembic upgrade head
fi

exec uv run uvicorn "$APP_MODULE" \
  --host "$HOST" \
  --port "$PORT" \
  --workers "$WORKERS" \
  --log-level "$LOG_LEVEL"
