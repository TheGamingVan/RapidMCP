#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_DIR="$ROOT_DIR/.run"

stop_by_pidfile() {
  local name="$1"
  local pidfile="$RUN_DIR/$name.pid"
  if [[ -f "$pidfile" ]]; then
    local pid
    pid="$(cat "$pidfile" | head -n 1)"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      echo "Stopped $name (PID $pid)"
    fi
    rm -f "$pidfile"
  fi
}

stop_by_port() {
  local port="$1"
  local name="$2"
  local pid
  pid="$(lsof -t -i tcp:"$port" -s tcp:listen 2>/dev/null | head -n 1 || true)"
  if [[ -n "$pid" ]]; then
    kill "$pid" 2>/dev/null || true
    echo "Stopped $name (Port $port, PID $pid)"
  fi
}

stop_by_pidfile "web"
stop_by_pidfile "host-service"
stop_by_pidfile "mcp-server"
stop_by_pidfile "dummy-api"

stop_by_port 3000 "web"
stop_by_port 8080 "host-service"
stop_by_port 8000 "mcp-server"
stop_by_port 9000 "dummy-api"
