# Architecture

## Modules

| Module | Responsibility |
| --- | --- |
| `config.py` | XDG paths, TOML settings, project root, login paths |
| `models.py` | Model catalog, `/api/tags` + `/api/ps` merge, display views |
| `router.py` | Task→model priority, context fitting against free RAM, system prompts |
| `ollama.py` | Async Ollama client, NDJSON streaming, pull progress |
| `cloud.py` | Ollama Cloud readiness, enable/disable, alias rendering, provider routes, plan errors |
| `bridge.py` | Anthropic Messages → non-streaming gateway → Anthropic SSE, so Claude Code executes tools |
| `tier_gateway.py` | Latency-aware OpenAI gateway: fast/balanced/deep/ultra routing, correct streamed tool calls, fallback, cache, metrics |
| `mcp.py` | MCP stdio server: models, skills, project memory, checks, completions |
| `skills_install.py` | One curated skill library → Claude/Codex/Qwen/OpenCode/Continue + project index |
| `client_setup.py` | Codex/OpenCode/Continue/Claude config and MCP registration, forced-local app configs with reversible cloud copies, live provider probe |
| `gateway.py` | LiteLLM `/v1/models` probe |
| `system.py` | macOS memory, disk, ports, launch agent, client paths |
| `status.py` | Single `Snapshot` used by CLI and TUI |
| `sessions.py` | Append-only JSONL conversations, mode 0600 |
| `tui/app.py` | Textual dashboard, streaming chat, suspend-to-Qwen |
| `cli.py` | `sovereign` commands and login agent installer |

## Data flow

1. The dashboard calls `status.collect()` every 2.5 s.
2. `collect()` gathers Ollama version/tags/ps, gateway models, memory, disk,
   ports, and login-agent state concurrently.
3. `models.build_views()` merges installed tags with the catalog and marks the
   loaded model and its real context. Cloud entries carry `cloud=True`: they have
   no local size, are never chosen by the router, and are shown in a separate
   table.
4. `router.choose()` selects a model for the current task and the largest context
   that fits; the TUI and `sovereign code` share this logic.
5. Before a turn, `_make_room()` unloads any other resident model so the
   selected model gets a real context instead of a 2k fallback.
6. A prompt is sent to `/api/chat` with `stream: true`. The assistant Markdown
   widget is updated as tokens arrive, then the exchange is appended to a JSONL
   session.

## Context fitting

```text
estimated_kv_gb ≈ max(0.35, weights_gb × context/32768 × 0.22)
total_gb        = weights_gb + estimated_kv_gb
pick the largest context in (32768, 24576, 20480, 16384, 8192, 4096, 2048)
where total_gb ≤ free_gb × 0.85
```

This is deliberately conservative: the goal is to avoid paging the KV cache,
not to squeeze out the last token. Tested on 24 GB unified memory: the 14B
coder reaches 32,768 tokens with `OLLAMA_FLASH_ATTENTION=1` and
`OLLAMA_KV_CACHE_TYPE=q8_0` (12 GB resident), and returns empty output at 24k+
without them. Those variables are set by `com.user.ollama.env` before Ollama
launches, so the catalog ceiling is 32,768. Gemma 12B reaches 32k only with
`think:false`; under pressure the router drops to 16k or 8k.

## Local clients

`clients.py` is a pure planner: it detects commands, writes
`~/Documents/local-ai/config/codex/local.config.toml`, and builds argv/env for each client without
mutating the current process. The TUI and CLI share `plan_launch`.

- Agent clients (Qwen Code, OpenCode) get the verified tool-calling model.
- Chat clients (Codex, Claude Code) get loopback gateway settings only.
- Wrappers are written to `~/Documents/local-ai/bin` and symlinked into
  `~/.local/bin` so they stay on `PATH`.

The capability split is intentional. Ollama's streamed tool calls do not survive
the LiteLLM translation reliably enough for Codex or Claude Code to edit files,
so the project routes edits to Qwen Code rather than pretending otherwise.

## TUI event loop

- `on_mount` builds the shell, adds the welcome message, starts the 2.5 s refresh.
- `on_input_submitted` handles slash commands or starts a `run_worker` chat task.
- `_stream_reply` consumes `OllamaClient.chat_stream` and updates a `Markdown`
  widget in place; it never blocks the refresh timer.
- `sovereign free` and the TUI `/free` command unload residents on demand.
- `F2` / `F4` / `F6` use Textual's `suspend()` to hand the real terminal to
  Qwen Code, Codex, or Claude Code, then refresh on return.
- `/qwen`, `/codex`, and `/claude` do the same from the input line;
  `/clients` prints the capability matrix without leaving the dashboard.

## Login agent

The plist runs `open -a Terminal <bin/sovereign-dashboard.command>`. The command
uses the project venv (or `python3 -m sovereign_code`) and is independent of the
user's shell config. `install-login` is idempotent and `uninstall-login` removes
both the plist and the loaded job.

## The stack as services

`sovereign autostart --install` writes one `~/Library/LaunchAgents` plist per
service: the LiteLLM gateway, the tier gateway, the Anthropic bridge, the
ChatGPT Local web UI and the guardian. Each has `RunAtLoad` (it starts at
login, so it survives a reboot) and `KeepAlive` with `SuccessfulExit: false`
(launchd restarts it after a crash, but leaves it alone after a clean exit —
a clean exit means another instance already owns the port).

The guardian is the second line of defence. Every 30 seconds it checks the
ports and restarts what is missing, preferring `launchctl kickstart` when the
job is loaded so the job launchd supervises is the one that gets restarted. It
also republishes `CODEX_APP_SERVER_OPENAI_BASE_URL` and `SOVEREIGN_API_KEY`
with `launchctl setenv`, which is the only way to reach an app launched from
the Dock, and it puts the ChatGPT config and Claude's settings back on the
local path when they drift — but only while the local mode is the current
one, so `sovereign chatgpt --cloud` and `sovereign claude --cloud` are not
undone.

## Gateway supervisor and TCC

`~/Documents` is TCC-protected, and a `launchd` job is stricter than a shell.
Three rules decide what a job can do there, and they were all found by
watching a job fail:

- It may **read** a file by its full path, and it may **run a program** by its
  full path. `…/sovereign-code/.venv/bin/python -m sovereign_code router`
  works, even though the venv and the sources live in `~/Documents`.
- It may not **execute a script** there: `/bin/bash …/run_gateway.sh` fails
  with `Operation not permitted`. The gateway is therefore started through its
  interpreter (`venv/bin/python3 venv/bin/litellm`).
- It may not **list** a directory there (`ls` fails), and it may not open a
  **log file another app created**: such a file carries
  `com.apple.provenance`, and the job then fails to spawn with `EX_CONFIG`
  (78) instead of starting. Every service uses a log file of its own, created
  by launchd itself.

`com.user.sovereign.gateway` runs the gateway through its interpreter and
checks the port first, so a job that finds the gateway already serving exits
cleanly and launchd leaves it alone instead of restarting it into a fight.

The older `com.user.ailocalgateway` job used to run
`open -gj -a Terminal start_gateway.command`, which detached `run_gateway.sh`
with `nohup`. It is retired: the launchd services own the gateway now, and
the retired plists are kept as `.superseded` so the old way can be restored.

`com.user.ailocalgateway.watchdog` checked the gateway every five minutes
and asked Terminal to restart the supervisor. The guardian does that job
now, without a window: it checks the same ports, restarts a service through
launchd when the job is loaded, and repairs the client configs. The watchdog
is retired with the rest.

## Cloud path (opt-in)

Cloud models are ordinary Ollama tags with a `:cloud` suffix; the server
forwards them to ollama.com. Three things must be true: the app setting
`~/.ollama/server.json` (`disable_ollama_cloud`) must be false, the server env
must not contain `OLLAMA_NO_CLOUD`, and the account must be signed in
(`ollama signin`). `cloud.read_cloud_status()` reads the first two; `--probe`
sends one tiny completion to learn the third, plus whether the account's plan
includes the model.

`apply_cloud()` is the only writer: it updates `server.json`, `launchctl setenv`,
the login-agent plist (text edit, so its comments survive), the sourced
`~/.config/sovereign-ai-os/profile.env` (otherwise every new shell re-exports
`OLLAMA_NO_CLOUD=1`), then restarts the app. `open -a Ollama` inherits the
caller's environment, so the restart removes `OLLAMA_NO_CLOUD` from
`os.environ` first; otherwise a shell that has it set would immediately
re-disable cloud. The restart waits for both app processes to exit before
launching, because `open -a` is ignored while the old app is still shutting
down.

Gateway aliases are generated between marker comments and inserted before
`router_settings:` so the YAML stays valid; `merge_gateway_text()` is idempotent
and backs up the config. `route_for()` decides each alias's backend: a direct
provider key (DeepSeek, Z.ai, Moonshot, Alibaba), then OpenRouter, then Ollama
Cloud, unless `--route` forces one. Provider entries use
`openai/<vendor-model>` with an explicit `api_base` and
`api_key: os.environ/<ENV_VAR>`; keys live in `gateway/cloud.env` (mode 0600),
which the supervisor sources. A 402 from the Ollama plan is wrapped by LiteLLM
as a 500; `summarize.complete()` reads the body and re-attaches the upgrade
link.

## Tier gateway

`tier_gateway.py` listens on 4010 and is the default OpenAI endpoint. It
classifies using user/tool messages only (not the agent's system prompt), keeps
named aliases explicit, and talks to Ollama natively so streamed `tool_calls`
are valid OpenAI deltas. A single-model lock evicts other residents before a
tier switch; loading two 18 GB models on 24 GB otherwise triggers a Metal OOM
panic. Models that are resident with too small a context are reloaded. Short,
tool-free, low-temperature responses are cached; every request is logged to
`data/logs/tiers.jsonl`. Explicit `cloud-*`/provider aliases are proxied to
LiteLLM unchanged.

## Client compatibility layer

The clients disagree about how tools are streamed. LiteLLM's streamed Ollama
translation returns a tool call as `content` text; Codex 0.163 dropped
`wire_api = "chat"` and its Responses translation has the same defect;
OpenCode's built-in `ollama` provider does too. The working paths are:

- **Codex**: local profile points at the tier gateway's `/v1/responses` adapter,
  which translates to a non-streaming chat completion and emits Responses SSE
  with real `function_call` items. `--cloud` uses the ChatGPT login.
- **OpenCode**: a custom `local/` OpenAI-compatible provider pointing at
  `127.0.0.1:11434/v1`, not the built-in `ollama` provider.
- **Claude Code**: `bridge.py` accepts Anthropic `/v1/messages`, calls the
  gateway's `/v1/chat/completions` with `stream: false` (where LiteLLM's tool
  translation is correct), then emits Anthropic SSE with `tool_use` blocks.
  `message_start` is sent before the model runs so Claude's first-byte timeout
  does not close the connection during a long local prefill.
- **Qwen Code**: native Ollama model, no proxy.
- **Continue/VS Codium**: Ollama provider for chat/edit/autocomplete; prompts
  are installed under `~/.continue/prompts`.
- **ChatGPT / Claude Desktop**: MCP via `sovereign mcp`; Codex's config is
  shared by the ChatGPT app.

## Forced-local desktop apps

Both desktop apps read a config file that Sovereign Code can rewrite, and both
have a cloud default worth keeping:

| App | File | Local switch | Cloud copy |
| --- | --- | --- | --- |
| ChatGPT / Codex | `~/.codex/config.toml` | `model_provider = "sovereign-tier"`, `openai_base_url` on 4010 | `~/.codex/config.toml.sovereign-cloud` |
| Claude Code / Cowork | `~/.claude/settings.json` | `env.ANTHROPIC_BASE_URL` on 4001 | `~/.claude/settings.json.sovereign-cloud` |

Two rules make the switch safe:

- **The copy is taken before the first edit, and only when the file is not
  already local.** Saving an already-local config as the "cloud" copy would
  make `--cloud` hand back a local config as if it were the original.
- **The Codex provider takes its token from a command**
  (`[model_providers.sovereign-tier.auth]`), not from an environment variable.
  Codex refuses to combine `auth` with `env_key`, and an app launched from
  Finder or the Dock inherits no shell environment — with `env_key`, Codex
  aborts with "Missing environment variable" and the sign-in gate comes back.

`sovereign chatgpt --verify` proves the result end to end: the config, that no
OpenAI account is required, the running app-server's base URL, and a live turn
sent through the app's own provider config (same base URL, same token command).
`sovereign status --json` exposes the same state for scripts and the menu bar.

`install-clients` writes all of these. The paths and the MCP server are
idempotent; backups are written next to edited configs.

## Storage layout

All runtime state is in `~/Documents/local-ai`:

- `gateway/` — config, venv, supervisor, logs
- `config/{sovereign,codex}/` — app configs
- `data/{sessions,logs}/` — conversations
- `models/` — Ollama weights; `~/.ollama/models` is a symlink
- `qwen/` — Qwen Code state; `~/.qwen` is a symlink
- `bin/` — client wrappers (symlinked into `~/.local/bin`)

`~/.codex` still holds the cloud Codex app state; only the local profile and
`CODEX_HOME` for local launches live in Documents.

## Failure behaviour

- Ollama offline: the dashboard stays usable and shows `○ offline`; chat reports
  a clear error instead of crashing.
- Gateway offline: yellow status, chat still works (it talks to Ollama directly).
- Missing 14B: status/doctor show the 7B fallback and the exact pull command.
- Missing Qwen: `F2` reports it; `sovereign code` exits with the install hint.
- Missing Codex profile: `F4` prints the `sovereign install-clients` fix instead
  of launching, so Codex never falls back to a cloud account.
- Chat-only clients: `sovereign clients` and `doctor` label Codex and Claude
  Code as chat-only for local edits; edits are routed to Qwen Code.
