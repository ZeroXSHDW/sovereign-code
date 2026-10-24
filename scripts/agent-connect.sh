#!/bin/bash
# agent-connect.sh - one-command setup for Sovereign Code + every code agent.
#
#   curl -fsSL https://tokenharbor.ai/connect.sh | sh
#   # or from a local checkout:
#   bash scripts/agent-connect.sh
#
# What it does:
#   1. Installs/upgrades sovereign-code (venv + editable install + PATH link)
#   2. Detects all coding agents on this machine (opencode, codex, claude,
#      qwen, cursor, windsurf, zed, aider, continue, copilot, junie, amp,
#      roo/cline)
#   3. Writes per-agent configs pointing each agent at the Sovereign gateways
#      (tier gateway 4010, anthropic bridge 4001, ollama 11434)
#   4. Generates the LiteLLM model_list.yaml with per-client model lists
#   5. Installs client wrappers (codex-local, claude-local, opencode-local, …)
#
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"

SOVEREIGN_BIN="${SOVEREIGN_BIN:-$ROOT/bin/sovereign}"
PYTHON="${PYTHON:-python3}"
VENVDIR="${VENVDIR:-$ROOT/.venv}"
LOCAL_AI_ROOT="${LOCAL_AI_ROOT:-$HOME/Documents/local-ai}"

log()  { printf '[sovereign] %s\n' "$*" >&2; }
ok()   { printf '[sovereign] \033[32m✓\033[0m %s\n' "$*" >&2; }
warn() { printf '[sovereign] \033[33m!\033[0m %s\n' "$*" >&2; }

# ------------------------------------------------------------------ install

install_sovereign() {
  if command -v uv >/dev/null 2>&1; then
    log "syncing with uv"
    (cd "$ROOT" && UV_PROJECT_ENVIRONMENT="$VENVDIR" uv sync --locked --all-extras --dev --python "$PYTHON")
  else
    if [ ! -d "$VENVDIR" ]; then
      log "creating venv at $VENVDIR"
      "$PYTHON" -m venv "$VENVDIR"
    fi
    "$VENVDIR/bin/python" -m pip install --quiet --upgrade pip
    "$VENVDIR/bin/python" -m pip install --quiet -e '.[dev,browser]'
  fi

  mkdir -p "$HOME/.local/bin"
  ln -sf "$ROOT/bin/sovereign" "$HOME/.local/bin/sovereign"
  chmod 755 "$ROOT/bin/sovereign" "$ROOT/bin/sovereign-dashboard.command"

  # Make `sovereign` resolvable from inside this script even before PATH is fixed.
  SOVEREIGN="$VENVDIR/bin/sovereign"
  if [ ! -x "$SOVEREIGN" ]; then
    SOVEREIGN="$ROOT/bin/sovereign"
  fi
  export SOVEREIGN
}

# ------------------------------------------------------------------ detect

detect_agents() {
  # Delegate detection to sovereign's own detector so the shell script and the
  # CLI always agree.
  "$SOVEREIGN" agents --json 2>/dev/null || true
}

# ------------------------------------------------------------------ configure

configure_agent() {
  local key="$1" name="$2" command="$3" config_dir="$4"
  case "$key" in
    opencode)
      configure_opencode "$config_dir" "$command"
      ;;
    codex)
      configure_codex "$config_dir" "$command"
      ;;
    claude)
      configure_claude "$config_dir" "$command"
      ;;
    qwen)
      configure_qwen "$config_dir" "$command"
      ;;
    cursor|windsurf|zed|aider|continue|copilot|junie|amp|cline|roo)
      configure_generic_agent "$key" "$config_dir"
      ;;
  esac
}

configure_opencode() {
  local config_dir="$1" command="$2"
  local dir="$config_dir"
  if [ -z "$dir" ]; then dir="$HOME/.config/opencode"; fi
  mkdir -p "$dir"
  local cfg="$dir/opencode.json"
  cat > "$cfg" <<JSON
{
  "model": "sovereign/auto",
  "base_url": "http://127.0.0.1:4010/v1",
  "api_key": "local",
  "sovereign": true
}
JSON
  ok "opencode -> tier gateway (sovereign/auto) at $cfg"
}

configure_codex() {
  local config_dir="$1"
  local dir="$config_dir"
  if [ -z "$dir" ]; then dir="$HOME/.codex"; fi
  mkdir -p "$dir"
  "$SOVEREIGN" install-clients >/dev/null 2>&1 || true
  ok "codex -> tier gateway (wrappers installed)"
}

configure_claude() {
  local config_dir="$1"
  local dir="$config_dir"
  if [ -z "$dir" ]; then dir="$HOME/.claude"; fi
  mkdir -p "$dir"
  # Point Claude Code at the sovereign Anthropic bridge via settings.json.
  local settings="$dir/settings.json"
  if [ -f "$settings" ]; then
    cp -a "$settings" "$settings.sovereign-bak-$(date +%Y%m%d-%H%M%S)" 2>/dev/null || true
  fi
  cat > "$settings" <<JSON
{
  "anthropicBaseUrl": "http://127.0.0.1:4001",
  "anthropicAuthToken": "local",
  "anthropicApiKey": "local",
  "model": "best",
  "maxContextTokens": 65536,
  "maxOutputTokens": 8192,
  "allowOtherModels": true,
  "disableNonessentialTraffic": true,
  "disableBackgroundTasks": true,
  "sovereign": true
}
JSON
  ok "claude -> sovereign anthropic bridge at $settings"
}

configure_qwen() {
  local config_dir="$1"
  local dir="$config_dir"
  if [ -z "$dir" ]; then dir="$HOME/.config/qwen"; fi
  mkdir -p "$dir"
  local cfg="$dir/config.json"
  cat > "$cfg" <<JSON
{
  "model": "sovereign/auto",
  "base_url": "http://127.0.0.1:4010/v1",
  "api_key": "local",
  "sovereign": true
}
JSON
  ok "qwen -> tier gateway at $cfg"
}

configure_generic_agent() {
  local key="$1" config_dir="$2"
  local dir="${config_dir:-$HOME/.config/$key}"
  mkdir -p "$dir"
  echo '{"base_url":"http://127.0.0.1:4010/v1","api_key":"local","sovereign":true}' > "$dir/config.json"
  ok "$key -> tier gateway at $dir/config.json"
}

# ------------------------------------------------------------------ main

main() {
  local mode="${1:-full}"

  log "Sovereign Code agent connect"
  log "installing sovereign-code (if needed)…"
  install_sovereign

  log "ensuring config layout…"
  "$SOVEREIGN" config --write >/dev/null 2>&1 || true

  log "detecting coding agents…"
  "$SOVEREIGN" agents || true

  log "writing LiteLLM model_list…"
  "$SOVEREIGN" gateway-config --write >/dev/null 2>&1 || true
  ok "model_list written to $LOCAL_AI_ROOT/gateway/model_list.yaml"

  log "installing client wrappers…"
  "$SOVEREIGN" install-clients >/dev/null 2>&1 || true
  ok "wrappers in $LOCAL_AI_ROOT/bin (symlinked to ~/.local/bin)"

  # Per-agent configuration from the detector.
  log "configuring detected agents…"
  while IFS=$'\t' read -r key name installed command config_dir app_bundle details; do
    if [ "$installed" = "true" ] && [ -n "$key" ]; then
      configure_agent "$key" "$name" "$command" "$config_dir"
    fi
  done < <("$SOVEREIGN" agents --tsv 2>/dev/null || true)

  ok "Sovereign Code is ready."
  echo
  echo "  run:      sovereign"
  echo "  status:   sovereign status"
  echo "  agents:   sovereign agents"
  echo "  code:     sovereign code [path]"
  echo "  browse:   sovereign browse https://example.com"
  echo "  prompts:  sovereign prompts list"
  echo "  skill-db: sovereign skill-db list"
  echo
}

main "$@"
