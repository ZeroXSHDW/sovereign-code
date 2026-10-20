#!/bin/bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
exec "$ROOT/bin/sovereign" install-login "$@"
