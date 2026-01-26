#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [ -f "../../.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source ../../.env
  set +a
fi
if [ ! -d .venv ]; then
  python -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 9000
