#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi
export ENTRY_ENV="${ENTRY_ENV:-development}"
if [ "$ENTRY_ENV" != development ]; then
  echo 'dev.sh 仅用于 development 环境' >&2
  exit 1
fi
export ENTRY_ALLOW_SQLITE=1
export ENTRY_DATA_DIR="${ENTRY_DATA_DIR:-$ROOT/business_files}"
export ENTRY_UPLOAD_DIR="${ENTRY_UPLOAD_DIR:-$ENTRY_DATA_DIR/uploads}"
export ENTRY_SOURCE_DIR="${ENTRY_SOURCE_DIR:-$ENTRY_DATA_DIR/templates}"
export ENTRY_DATABASE_URL="${ENTRY_DATABASE_URL:-sqlite:///$ENTRY_DATA_DIR/demo.db}"
export ENTRY_COOKIE_SECURE=0
export ENTRY_EXTERNAL_WRITES_ENABLED=0
export PYTHONPATH="$ROOT/backend"
mkdir -p "$ENTRY_DATA_DIR"
if [ -z "${ENTRY_SECRET_KEY:-}" ] && [ -z "${ENTRY_SECRET_KEY_FILE:-}" ]; then
  export ENTRY_SECRET_KEY_FILE="$ENTRY_DATA_DIR/secret.key"
  if [ ! -f "$ENTRY_SECRET_KEY_FILE" ]; then
    .venv/bin/python -c 'import os, secrets; p=os.environ["ENTRY_SECRET_KEY_FILE"]; fd=os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600); os.write(fd, secrets.token_urlsafe(48).encode()); os.close(fd)'
  fi
fi
.venv/bin/python scripts/build_branding.py
.venv/bin/python -m database.operations.init_development
exec .venv/bin/python -m uvicorn app.main:app --host "${ENTRY_HOST:-127.0.0.1}" --port "${ENTRY_PORT:-8125}"
