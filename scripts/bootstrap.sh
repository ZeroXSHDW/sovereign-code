#!/bin/bash
# One-command setup: venv, editable install, PATH link, login terminal.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-python3}"
if ! "$PYTHON" -c 'import sys; assert sys.version_info >= (3, 11)' 2>/dev/null; then
  echo "Sovereign Code needs Python 3.11 or newer (found: $("$PYTHON" --version 2>&1))" >&2
  exit 1
fi

if [ ! -d .venv ]; then
  "$PYTHON" -m venv .venv
fi
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -e '.[dev]'

mkdir -p "$HOME/.local/bin"
ln -sf "$ROOT/bin/sovereign" "$HOME/.local/bin/sovereign"
chmod 755 "$ROOT/bin/sovereign" "$ROOT/bin/sovereign-dashboard.command"

echo "Sovereign Code is installed."
echo "  run:      sovereign"
echo "  status:   sovereign status"
echo "  code:     sovereign code [path]"
echo "  clients:  sovereign install-clients && sovereign clients"
echo "  tests:    .venv/bin/python -m pytest -q"
echo
"$ROOT/bin/sovereign" install-clients
echo
"$ROOT/bin/sovereign" install-login
echo
echo "Open the live terminal now: sovereign install-login --start-now"
