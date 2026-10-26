#!/bin/bash
# One-command setup: delegates to the full installer.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
exec "$ROOT/scripts/install.sh" "$@"
