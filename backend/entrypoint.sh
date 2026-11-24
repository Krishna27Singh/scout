#!/bin/sh
set -eu

if [ "${RUN_MIGRATIONS_ON_START:-true}" = "true" ]; then
  alembic -c backend/alembic.ini upgrade head
fi

exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-10000}" \
  --workers "${WEB_CONCURRENCY:-1}"
