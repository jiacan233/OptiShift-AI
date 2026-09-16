#!/bin/sh
set -eu

alembic upgrade head
python -m backend.app.scripts.seed_demo

exec uvicorn backend.app.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8080}" \
  --proxy-headers \
  --forwarded-allow-ips="*"
