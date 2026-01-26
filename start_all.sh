#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_DIR="$ROOT_DIR/.run"
mkdir -p "$RUN_DIR"

start_tracked() {
  local name="$1"
  local workdir="$2"
  shift 2
  (
    cd "$workdir"
    "$@"
  ) &
  local pid=$!
  echo "$pid" > "$RUN_DIR/$name.pid"
  echo "Started $name (PID $pid)"
}

start_tracked "mcp-server" "$ROOT_DIR/services/mcp-server" bash -lc "LOG_TO_FILE=0 ./run_local.sh"
start_tracked "host-service" "$ROOT_DIR/services/host-service" bash -lc "LOG_TO_FILE=0 ./run_local.sh"
start_tracked "dummy-api" "$ROOT_DIR/services/dummy-api" bash -lc "LOG_TO_FILE=0 ./run_local.sh"
start_tracked "web" "$ROOT_DIR/apps/web" bash -lc "if [ ! -d node_modules ]; then npm install; fi; npm run dev"
