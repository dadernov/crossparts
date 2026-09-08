#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
exec python3 -m uvicorn app.main:app --host "${CP_HOST:-0.0.0.0}" --port "${CP_PORT:-8000}" "$@"
