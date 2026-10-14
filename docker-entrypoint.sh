#!/bin/sh
set -eu
cd /app
python -c 'from app.core.config import settings; settings.validate_process_environment()'
mkdir -p "$ENTRY_UPLOAD_DIR" "$ENTRY_SOURCE_DIR"
python -m alembic -c database/alembic.ini upgrade head
python -m database.operations.seed_data
export UVICORN_BIN=/usr/local/bin/uvicorn
export ENTRY_HOST=0.0.0.0
export ENTRY_PORT=8125
exec ./run.sh
