#!/bin/bash
# One-command installer for Sovereign Code.
#
# By default this installs the Python environment, pre-commit hooks, the
# sovereign wrapper on PATH, and the optional system tools the project needs
# (Ollama, Node/npx, poppler, tesseract, and Chromium for Playwright).  Run
# with --skip-extras to skip the Homebrew/Playwright parts.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"

WITH_EXTRAS=1
INSTALL_CLIENTS=1
YES=0
PYTHON="${PYTHON:-python3}"

usage() {
  cat <<EOF
Usage: $(basename "$0") [options]

Install Sovereign Code and the tools it depends on.

Options:
  --skip-extras    Skip Homebrew system packages and Playwright Chromium
  --skip-clients   Skip client configuration and login agent
  -y, --yes        Answer yes to any prompts (useful for CI/automation)
  -h, --help       Show this help

Environment:
  PYTHON           Python interpreter to use (default: python3)
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-extras)
      WITH_EXTRAS=0
      shift
      ;;
    --skip-clients)
      INSTALL_CLIENTS=0
      shift
      ;;
    -y|--yes)
      YES=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

log() { echo "[sovereign-install] $*"; }

confirm() {
  local prompt="$1"
  if [[ "$YES" -eq 1 ]]; then
    return 0
  fi
  read -r -p "$prompt [Y/n] " answer
  case "${answer,,}" in
    ""|y|yes) return 0 ;;
    *) return 1 ;;
  esac
}

on_darwin() {
  [[ "$(uname -s)" == "Darwin" ]]
}

ensure_homebrew() {
  if command -v brew >/dev/null 2>&1; then
    return 0
  fi
  if ! on_darwin; then
    echo "Homebrew is only installed automatically on macOS. Please install the" >&2
    echo "equivalent system packages (poppler-utils, tesseract-ocr, node, ollama)" >&2
    echo "and re-run with --skip-extras." >&2
    return 1
  fi
  if ! confirm "Homebrew not found. Install it now?"; then
    echo "Please install Homebrew and re-run, or use --skip-extras." >&2
    return 1
  fi
  log "Installing Homebrew..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  if [[ -x /opt/homebrew/bin/brew ]]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  elif [[ -x /usr/local/bin/brew ]]; then
    eval "$(/usr/local/bin/brew shellenv)"
  fi
}

ensure_uv() {
  if command -v uv >/dev/null 2>&1; then
    return 0
  fi
  log "uv not found. Installing uv..."
  if command -v brew >/dev/null 2>&1; then
    brew install uv
  elif [[ "$YES" -eq 1 ]]; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    if [[ -x "$HOME/.local/bin/uv" ]]; then
      export PATH="$HOME/.local/bin:$PATH"
    elif [[ -x "$HOME/.cargo/bin/uv" ]]; then
      export PATH="$HOME/.cargo/bin:$PATH"
    fi
  else
    echo "Please install uv (https://docs.astral.sh/uv/) and re-run." >&2
    return 1
  fi
}

ensure_python() {
  if "$PYTHON" -c 'import sys; assert sys.version_info >= (3, 11)' 2>/dev/null; then
    return 0
  fi
  log "No Python 3.11+ found via $PYTHON; asking uv to provide one..."
  uv python install 3.11
  PYTHON="$(uv python find 3.11)"
  if ! "$PYTHON" -c 'import sys; assert sys.version_info >= (3, 11)' 2>/dev/null; then
    echo "Sovereign Code needs Python 3.11 or newer." >&2
    return 1
  fi
}

install_core() {
  log "Creating venv and installing Python dependencies..."
  uv sync --locked --all-extras --dev --python "$PYTHON"

  if [[ -d .git ]] && [[ -x .venv/bin/pre-commit ]]; then
    log "Installing pre-commit hooks..."
    .venv/bin/pre-commit install
  fi
}

install_extras() {
  if [[ "$WITH_EXTRAS" -eq 0 ]]; then
    return 0
  fi
  if ! on_darwin; then
    log "Skipping system extras on non-macOS. Install poppler-utils, tesseract-ocr," \
        "node and ollama via your package manager if you need them."
    return 0
  fi

  log "Installing system extras (Ollama, Node, poppler, tesseract)..."
  ensure_homebrew
  brew install --cask ollama || echo "warning: could not install Ollama; install it manually from https://ollama.com"
  brew install node poppler tesseract || echo "warning: one or more brew packages failed to install"

  log "Installing Chromium for Playwright..."
  uv run playwright install chromium
}

link_wrapper() {
  mkdir -p "$HOME/.local/bin"
  ln -sf "$ROOT/bin/sovereign" "$HOME/.local/bin/sovereign"
  chmod 755 "$ROOT/bin/sovereign" "$ROOT/bin/sovereign-dashboard.command" "$ROOT/bin/sovereign-start.command"
}

install_client_configs() {
  if [[ "$INSTALL_CLIENTS" -eq 0 ]]; then
    return 0
  fi
  log "Installing local client configurations..."
  # sovereign install-clients and install-login wire up the local editors.
  "$ROOT/bin/sovereign" install-clients
  "$ROOT/bin/sovereign" install-login
}

# --------------------------------------------------------------------------- main

if ! on_darwin; then
  log "Note: Sovereign Code is designed for macOS/Apple Silicon; continuing anyway."
fi

ensure_uv
ensure_python
install_core
install_extras
link_wrapper
install_client_configs

log "Done."
echo
echo "Sovereign Code is installed."
echo "  run:      sovereign"
echo "  status:   sovereign status"
echo "  code:     sovereign code [path]"
echo "  tests:    make check"
echo
echo "Make sure ~/.local/bin is on your PATH:"
echo '  export PATH="$HOME/.local/bin:$PATH"'
