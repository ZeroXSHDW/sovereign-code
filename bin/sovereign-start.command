#!/bin/bash
# Double-click (or run) this file to start Sovereign Code's terminal view.
# It starts the local stack if needed and opens the live dashboard.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"

export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

PYTHON="$ROOT/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
  PYTHON="/usr/bin/env python3"
fi

# If the dashboard is already running, just say so instead of stacking copies.
if pgrep -f "sovereign_code (dashboard|monitor)" >/dev/null 2>&1; then
  echo "Sovereign Code is already running."
  exit 0
fi

exec "$PYTHON" -m sovereign_code dashboard "$@"
