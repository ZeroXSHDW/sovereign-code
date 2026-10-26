#!/bin/bash
# Compatibility entry point: keep every client on the maintained installer.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
exec "$ROOT/scripts/install.sh" --skip-extras "$@"
