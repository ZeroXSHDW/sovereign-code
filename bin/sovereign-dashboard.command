#!/bin/bash
# Opened by the login LaunchAgent. Keeps the live dashboard in one Terminal tab.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"

export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
if [ -x "$ROOT/.venv/bin/python" ]; then
  exec "$ROOT/.venv/bin/python" -m sovereign_code dashboard
fi
exec /usr/bin/env python3 -m sovereign_code dashboard
