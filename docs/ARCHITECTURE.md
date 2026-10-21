# Architecture

## Modules

| Module | Responsibility |
| --- | --- |
| `config.py` | XDG paths, TOML settings, project root, login paths |
| `models.py` | Model catalog, `/api/tags` + `/api/ps` merge, display views |
| `router.py` | Task→model priority, context fitting against free RAM, system prompts |
| `ollama.py` | Async Ollama client, NDJSON streaming, pull progress |
| `cloud.py` | Ollama Cloud readiness, enable/disable, alias rendering, plan errors |
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

## Gateway supervisor and TCC

`~/Documents` is TCC-protected: a launchd job cannot read the gateway venv there
(`Operation not permitted`). `com.user.ailocalgateway` therefore runs
`open -gj -a Terminal start_gateway.command`, which detaches `run_gateway.sh`
with `nohup` and exits. Terminal holds the user's Documents consent, and a
detached child keeps that access after the window closes. The supervisor
restarts LiteLLM on crash, backs off 3 s, rotates the log at 5 MB, and treats
the listening port as its singleton lock, so duplicate starts exit instead of
racing. No Full Disk Access grant is needed.

`com.user.ailocalgateway.watchdog` checks `127.0.0.1:4000` every five minutes.
It is the only agent that could run entirely under launchd, because it invokes
only `/bin/bash`, `/usr/bin/curl`, and `/usr/bin/open`; the `.command` it opens
is still executed by Terminal. If the supervisor is gone, the watchdog recreates
it; if LiteLLM alone died, the existing supervisor handles the restart. The
gateway venv uses Homebrew Python 3.13 (LiteLLM 1.83.x supports 3.10–3.13).

## Cloud path (opt-in)

Cloud models are ordinary Ollama tags with a `:cloud` suffix; the server
forwards them to ollama.com. Three things must be true: the app setting
`~/.ollama/server.json` (`disable_ollama_cloud`) must be false, the server env
must not contain `OLLAMA_NO_CLOUD`, and the account must be signed in
(`ollama signin`). `cloud.read_cloud_status()` reads the first two; `--probe`
sends one tiny completion to learn the third, plus whether the account's plan
includes the model.

`apply_cloud()` is the only writer: it updates `server.json`, `launchctl setenv`,
the login-agent plist (text edit, so its comments survive), then restarts the
app. `open -a Ollama` inherits the caller's environment, so the restart removes
`OLLAMA_NO_CLOUD` from `os.environ` first; otherwise a shell that has it set
would immediately re-disable cloud.

Gateway aliases are generated between marker comments and inserted before
`router_settings:` so the YAML stays valid; `merge_gateway_text()` is idempotent
and backs up the config. Every cloud alias maps to an Ollama tag, so LiteLLM
needs no provider key. A 402 from the account's plan is wrapped by LiteLLM as a
500; `summarize.complete()` reads the body and re-attaches the upgrade link.

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
