#!/usr/bin/env bash
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
export FS_MCP_ENABLED=${FS_MCP_ENABLED:-true}
if [ ! -d ".venv" ]; then
  python -m venv .venv
fi
. .venv/bin/activate
python -m pip install -r requirements.txt
export HOST_PORT=${HOST_PORT:-8080}
uvicorn app:app --host 0.0.0.0 --port "$HOST_PORT"
