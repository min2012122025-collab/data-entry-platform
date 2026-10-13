#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

require_env() {
  eval "value=\${$1:-}"
  if [ -z "$value" ]; then
    echo "缺少环境变量：$1" >&2
    exit 1
  fi
}

require_env ENTRY_DATABASE_URL
require_env ENTRY_EXPECTED_DATABASE
require_env ENTRY_DATA_DIR
require_env ENTRY_UPLOAD_DIR
require_env ENTRY_SOURCE_DIR
if { [ -n "${ENTRY_SECRET_KEY:-}" ] && [ -n "${ENTRY_SECRET_KEY_FILE:-}" ]; } || { [ -z "${ENTRY_SECRET_KEY:-}" ] && [ -z "${ENTRY_SECRET_KEY_FILE:-}" ]; }; then
  echo "ENTRY_SECRET_KEY 与 ENTRY_SECRET_KEY_FILE 必须且只能配置一个" >&2
  exit 1
fi
if [ "${ENTRY_ENV:-}" != "production" ]; then
  echo "ENTRY_ENV 必须设置为 production" >&2
  exit 1
fi
if [ "${ENTRY_ALLOW_SQLITE:-0}" = "1" ] || echo "$ENTRY_DATABASE_URL" | grep -q '^sqlite'; then
  echo "production 环境禁止使用 SQLite" >&2
  exit 1
fi
if [ "${ENTRY_COOKIE_SECURE:-0}" != "1" ]; then
  echo "production 环境必须设置 ENTRY_COOKIE_SECURE=1" >&2
  exit 1
fi

if [ ! -f "$ROOT/frontend/dist/index.html" ]; then
  echo "缺少前端生产构建，请检查 frontend/dist/index.html" >&2
  exit 1
fi

export PYTHONPATH="$ROOT/backend"
if [ -n "${UVICORN_BIN:-}" ]; then
  exec "$UVICORN_BIN" app.main:app --host "${ENTRY_HOST:-127.0.0.1}" --port "${ENTRY_PORT:-8125}" --workers 1 --proxy-headers --forwarded-allow-ips "${ENTRY_FORWARDED_ALLOW_IPS:-127.0.0.1}"
elif [ -x "$ROOT/.venv/bin/python" ]; then
  PYTHON="$ROOT/.venv/bin/python"
else
  echo "缺少 .venv，请先创建虚拟环境并安装 backend/requirements.txt" >&2
  exit 1
fi

exec "$PYTHON" -m uvicorn app.main:app --host "${ENTRY_HOST:-127.0.0.1}" --port "${ENTRY_PORT:-8125}" --workers 1 --proxy-headers --forwarded-allow-ips "${ENTRY_FORWARDED_ALLOW_IPS:-127.0.0.1}"
