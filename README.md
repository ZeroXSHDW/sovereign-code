# Sovereign Code

**A terminal-first, local-first AI coding console for Apple Silicon.**

[![tests](https://github.com/ZeroXSHDW/sovereign-code/actions/workflows/ci.yml/badge.svg)](https://github.com/ZeroXSHDW/sovereign-code/actions/workflows/ci.yml)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue) ![License MIT](https://img.shields.io/badge/license-MIT-green) ![Platform](https://img.shields.io/badge/platform-Apple%20Silicon-silver) ![Local only](https://img.shields.io/badge/network-offline-purple)

![Sovereign Code dashboard](docs/assets/dashboard.png)

## Architecture

![Sovereign Code architecture](docs/assets/architecture.png)

The terminal configuration as a 3D stack:

![Sovereign Code 3D stack](docs/assets/architecture-3d.png)

(`docs/assets/social-preview.png` is the 1200×630 image to set as the repository's
social preview card.)

Sovereign Code replaces the Swift menu-bar approach of the earlier Local Bar
projects with a portable Python/Textual system. At login, Terminal opens a live
dashboard showing the local stack, the loaded model, free memory, the gateway,
and a streaming chat prompt. From the dashboard you can code with the best local
model or drop straight into Qwen Code in the current repository.

Nothing leaves the Mac. Both Ollama and the LiteLLM gateway are bound to
`127.0.0.1`, and the UI never calls a cloud API.

## Quick start

```sh
cd ~/Documents/sovereign-code
./scripts/bootstrap.sh           # venv, install, PATH link, login agent
sovereign                       # open the dashboard now
```

The first run uses `~/Documents/local-ai/config/sovereign/config.toml` and
`~/Documents/local-ai/data/` (sessions and logs).

Everything the system owns lives in `~/Documents/local-ai`:

```text
~/Documents/local-ai/
├── gateway/     LiteLLM config, venv, supervisor, logs
├── bin/         qwen-local, codex-local, claude-local
├── config/      sovereign/ and codex/ profiles
├── data/        sessions and logs
├── models/      Ollama weights (34 GB; ~/.ollama/models symlinks here)
├── qwen/        Qwen Code state (~/.qwen symlinks here)
└── legacy/      archived pre-migration ai-stack
```

### Dashboard keys

| Key | Action |
| --- | --- |
| `F2` | suspend the dashboard and open Qwen Code in your workspace (`~/Documents`) |
| `F3` | cycle installed models |
| `F4` | open the local ChatGPT / Codex profile in your workspace |
| `F5` | refresh system state |
| `F6` | open Claude Code against the local gateway |
| `Ctrl+N` | new conversation |
| `Ctrl+Q` | quit |

Input commands: `/model <tag>`, `/models`, `/chat`, `/code`, `/reason`,
`/vision`, `/fast`, `/status`, `/open [path]`, `/qwen`, `/codex`, `/claude`,
`/clients`, `/clear`, `/help`, `/quit`.

`workspace` lives in `~/Documents/local-ai/config/sovereign/config.toml` and defaults to
`~/Documents`; `/open /path/to/repo` overrides it for one session.

## Why this is better than the old Local Bar build

| Local Bar (Swift) | Sovereign Code |
| --- | --- |
| Pinned to a Swift 6.3 / macOS 26.5 SDK | Plain Python 3.11+; no app build step |
| Menu-bar window, mouse-first | Live terminal dashboard, keyboard-first |
| Hard-coded model/client paths in Swift | One TOML + env config; model catalog in Python |
| No automated tests in the repo | 26 unit/headless-TUI tests, `pytest` |
| Single model pinned at build time | Curated remote catalog with ~35 downloadable tags, model-info, and offline stacks |
| Context fitting spread across UI code | `router.py` estimates KV + weights against free RAM |
| Client setup mutates many apps | Detects clients, writes only its own profile and `*-local` wrappers |
| No session history | JSONL per conversation under `~/Documents/local-ai/data` |
| Session retention | optional: `session_retention_days` / `session_keep` in `config.toml` |

See [docs/IMPROVEMENTS.md](docs/IMPROVEMENTS.md) and
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Models (24 GB M5 Pro)

### Installed / recommended

| Model | Role | Notes |
| --- | --- | --- |
| `qwen2.5-coder:14b` | best coder | 9.0 GB; preferred for code; verified at **32k** with q8 KV |
| `qwen2.5-coder:7b` | coder fallback | 4.7 GB; 32k works but tool calls through agent clients are unreliable |
| `qwen3.5:4b` | chat / vision / tools | 4.0 GB; 65k with `think:false` |
| `gemma4:12b` | agent + deep reasoning / vision | 7.7 GB; 32k with `think:false`; verified tool calls |
| `llama3.1:8b` | reasoning fallback | 4.9 GB; 65k |

### Downloadable (any tag works with `sovereign pull` / `sovereign run`)

`OllamaClient` talks to Ollama directly, so **any** Ollama library tag can be
downloaded and run — not just the curated ones below. Use
`sovereign model-info <tag>` to check parameter size, quantization, family, and
context length before you pull, and `sovereign models --remote [query]` to
browse the curated catalog.

| Model | Rough size | Notes |
| --- | --- | --- |
| `qwen2.5-coder:1.5b` | ~0.9 GB | tiny coder; fast, low RAM |
| `qwen2.5-coder:3b` | ~1.9 GB | small coder; quick edits and iteration |
| `qwen2.5-coder:7b` | ~4.7 GB | solid coder |
| `qwen2.5-coder:14b` | ~9.0 GB | best coder that fits 24 GB |
| `qwen2.5-coder:32b` | ~20 GB | stronger coder; tight on 24 GB |
| `deepseek-coder-v2:16b` | ~9 GB | strong coding model |
| `deepseek-r1:7b` | ~4.4 GB | reasoning with visible chain-of-thought |
| `deepseek-r1:14b` | ~9 GB | reasoning with visible chain-of-thought |
| `deepseek-r1:32b` | ~20 GB | strong reasoning; tight on 24 GB |
| `qwen3:4b` | ~2.3 GB | current-gen general model |
| `qwen3:8b` | ~4.9 GB | current-gen general model with reasoning |
| `qwen3:14b` | ~9 GB | current-gen general model with reasoning |
| `llama3.2:3b` | ~2.0 GB | tiny fast general model |
| `llama3.1:8b` | ~4.9 GB | reasoning fallback with long context |
| `gemma3:12b` | ~7.7 GB | general model with strong reasoning |
| `phi4:14b` | ~9 GB | small reasoning model |
| `codestral:22b` | ~13 GB | Mistral coding model; tight on 24 GB |
| `nomic-embed-text` | ~0.3 GB | embeddings for semantic search |

### Honest note on specific models

GLM (Zhipu), "Deepseek v4.1 Flash," and Kimi K3 are **not published on
Ollama's library** as far as this project can verify, so they are not added as
one-click downloads. If you have a GGUF for one of them, you can still run it
through Ollama (`ollama create` / `ollama run`) and then `sovereign run <tag>`
it. Every `pull` prints an estimated size and warns when free disk is low, and
`sovereign rm <tag>` reclaims space.

### Offline model stacks

These are rough installed-size totals for a 24 GB Mac; models run one or two
at a time (Ollama swaps automatically).

| Stack | Models | Approx. total | Note |
| --- | --- | --- | --- |
| `lean` | qwen2.5-coder:3b, qwen2.5:0.5b, nomic-embed-text | ~4 GB | fast edits + tiny chat + embeddings |
| `balanced` | qwen2.5-coder:7b, qwen3:4b, deepseek-r1:8b, nomic-embed-text | ~14 GB | solid coder + chat + reasoning |
| `capable` | qwen2.5-coder:14b, gemma4:12b, deepseek-r1:14b, nomic-embed-text | ~29 GB | best local coder + reasoning; swap with `sovereign free` |
| `max` | qwen2.5-coder:32b, deepseek-r1:32b, codestral:22b | ~53 GB | maximum capability; pull only what you need |

Pull a stack one model at a time:

```sh
sovereign pull qwen2.5-coder:14b
sovereign pull gemma4:12b
sovereign pull deepseek-r1:14b
sovereign pull nomic-embed-text
```

The router picks the best **installed** model for the task, then chooses the
largest context that fits in ~85% of free memory. Agentic coding prefers a
model that is verified to call tools (`gemma4:12b`, then `qwen3.5:4b`) rather
than a code model that only chats. The 14B coder reaches 32,768 tokens because
Ollama runs with flash attention and a q8_0 KV cache; without those settings its
verified ceiling is 20,480. The context choices are
`32768, 24576, 20480, 16384, 8192, 4096, 2048`. `sovereign free` evicts resident
models before a turn so a 4B model is not squeezed into a 2k context by a
resident 12B. If the 14B coder is missing it falls back to 7B and says so;
`sovereign pull-recommended` installs it.

## Local coding clients

`sovereign install-clients` writes a Codex profile at
`~/Documents/local-ai/config/codex/local.config.toml` and three wrappers in
`~/Documents/local-ai/bin` (symlinked into `~/.local/bin` for `PATH`):
`qwen-local`, `codex-local`, and `claude-local`. It never edits the cloud
configuration of ChatGPT, Codex, or Claude Code.

| Client | Local inference | Can edit files locally? | How |
| --- | --- | --- | --- |
| Qwen Code | Yes | **Yes, verified** | `sovereign code [path]` / `qwen-local`; model `gemma4:12b` |
| OpenCode | Yes | **Yes, verified** | `opencode run -m ollama/gemma4:12b`; pick the model in its TUI |
| Codex CLI | Yes, chat only | No | `codex --profile local`; tool calls return raw JSON instead of executing |
| Claude Code | Yes, chat only | No | `claude-local`; the gateway answers, but streaming tool calls are unreliable |

The honest rule: **Qwen Code and OpenCode are the local agents.** Codex and
Claude Code are useful local chat clients, not reliable local editors. The
limitation is in how Ollama streams tool calls through LiteLLM, not in the
models themselves.

## Commands

```sh
sovereign                  # live dashboard
sovereign status           # one-shot status
sovereign models           # installed + recommended, with roles
sovereign doctor           # checks and concrete fixes
sovereign doctor --fix     # apply the safe fixes automatically
sovereign verify           # tiny completion per core alias (--all for nine)
sovereign bench            # tokens/sec for chosen aliases (--models a,b)
sovereign backup           # tarball of configs + chat data
sovereign summarize FILE   # or --url URL, via the local model
sovereign index .          # embed a directory for semantic search
sovereign search "query"   # find relevant chunks (--path DIR --top N)
sovereign config           # view settings; --get KEY, --set KEY=VALUE
sovereign stats            # disk usage across the stack
sovereign sessions --search "term"   # search chat history
sovereign pull <model>     # pull any Ollama model by tag
sovereign run <model> "…"  # download (if needed) and run any model on a prompt
sovereign model-info <tag> # inspect size/context/family before pulling
sovereign rm <model>       # remove an installed model
sovereign models --remote  # list downloadable models (--remote coder)
sovereign consult "…"      # run one prompt across several models
sovereign skills           # list saved prompt templates
sovereign skill <name> --prompt "…"
sovereign memory add "note" # per-project memory (show / clear)
sovereign clone <url>      # clone a GitHub repo into ~/Documents/projects
sovereign pipeline "…"     # plan -> implement -> review across models
sovereign free             # unload resident models
sovereign code [path]      # Qwen Code with the verified agent model
sovereign launch qwen|codex|claude [path]
sovereign clients          # installed clients and verified capabilities
sovereign gateway          # gateway status, paths, and restart command
sovereign gateway --restart # stop supervisor + LiteLLM, start, wait for health
sovereign logs [gateway|watchdog|dashboard] [-n 40] [-f]
sovereign sessions         # list stored chats; --prune --days 30 --keep 50
sovereign install-clients  # Codex profile + *-local wrappers
sovereign chat --model qwen3.5:4b
sovereign env              # exports for OpenAI-compatible local clients
sovereign pull-recommended # qwen2.5-coder:14b
sovereign browse URL --task "…" # local model drives a visible Chromium
sovereign install-login --start-now
sovereign uninstall-login
```

## Browser operator

```sh
sovereign browse https://example.com --task "find the pricing table and summarize it"
sovereign browse URL --allow-local --headless --max-steps 6
sovereign browse URL --task "…" --screenshots   # save a PNG at each terminal state
sovereign browse URL --task "…" --dry-run   # show the first planned action only
```

The local model drives a visible, persistent Chromium profile through Playwright,
reading the page and performing one structured action at a time (`navigate`,
`click`, `fill`, `select`, `press`, `scroll`, `extract`), then hands back control
when it needs you. In the dashboard, press `F8` (or `/browse <url> [task]`).

- **No CAPTCHA solving, bot-check bypass, user-agent spoofing, or fingerprint
  evasion.** The browser runs with its normal identity.
- **Passwords, OTPs, and payment fields are never filled by the model** — it
  hands off so you type them.
- **Destructive actions** (buy, delete, submit, unsubscribe, …) ask first unless
  you pass `--yes`.
- **Local/private addresses** need `--allow-local`; `--allow-domain` restricts
  navigation. Every step is recorded (fills are length-only) under
  `~/Documents/local-ai/data/browser/runs/`.

Install: `pip install -e '.[browser]' && playwright install chromium`.

## Skills, memory, and multi-model

Saved prompt templates live in `~/Documents/local-ai/config/skills/` as Markdown
files — `code-review`, `write-tests`, `refactor`, `explain`, `specify`,
`security-review`, `financial-analysis`, and `legal-review`. `sovereign skills`
lists them; `sovereign skill <name> --prompt "…"` runs one through the local
model. Add your own by dropping a Markdown file with a `{{prompt}}` placeholder.

```sh
sovereign consult "what is the best way to X?" --models local-chat,local-reasoning
sovereign skill code-review --prompt "$(cat src/app.py)"
```

`sovereign consult` runs one prompt through several models and prints each
answer.

`sovereign run <model> "…"` downloads the model on first use and runs a prompt
through it directly (any Ollama tag, with `--context`, `--temperature`, and
`--system`). `sovereign models --remote [query]` lists curated downloadable
models, and `sovereign rm <model>` removes one you no longer need.

### Multi-model pipeline

```sh
sovereign pipeline "build a CLI that greets a name" --dir ~/projects/demo --yes
sovereign pipeline "…" --plan-model local-reasoning --agent gemma4:12b --review-model local-agent
```

`sovereign pipeline` chains three models into one coding pass: a **planner**
writes an implementation plan, **Qwen Code** (with the agent model) writes the
files, and a **reviewer** critiques the result. `--yes` auto-approves the agent's
tool calls for unattended runs; `--no-review` skips the final stage. This is the
local version of end-to-end, multi-model coding — one or two models resident at
a time, swapped automatically by Ollama. `sovereign memory add "…"` stores a per-folder note that is injected
into every dashboard chat, so project preferences persist. If a project has an
`AGENTS.md` or `CLAUDE.md`, that too is injected into the dashboard chat, `sovereign
code`, and `sovereign pipeline` automatically. `sovereign clone
<url>` bootstraps a GitHub repo under `~/Documents/projects/` (then
`sovereign index` it for search).

Honest limits: this is a 24 GB Mac. Models run one or two at a time (Ollama
swaps automatically), MLX is already active for supported models, and "more
speed" comes from model and context choice — not from any of these commands.

## Semantic code search

```sh
sovereign index .                # embed the current directory
sovereign search "gateway restart" --top 5
sovereign search "query" --path ~/repo
```

`sovereign index` walks a directory (skipping `.git`, `node_modules`, venvs, and
binaries), chunks each text file, and stores local embeddings from Ollama's
`nomic-embed-text` (274 MB, pulled automatically via `ollama pull
nomic-embed-text`). `sovereign search` ranks chunks by cosine similarity against
the query. Everything stays on the machine; the index lives under
`~/Documents/local-ai/data/index/` and is excluded from backups and Time Machine
(it is cheap to rebuild).

## Login terminal

`sovereign install-login` writes
`~/Library/LaunchAgents/com.user.sovereign-code.plist`. At login it runs:

```sh
/usr/bin/open -a Terminal /Users/user/Documents/sovereign-code/bin/sovereign-dashboard.command
```

The `.command` starts the dashboard in the project venv. Install is idempotent;
`--start-now` loads the agent immediately so you can see the terminal before
logging out. `uninstall-login` removes it.

### Gateway autostart (macOS TCC)

macOS does not let a `launchd` job read `~/Documents`, so a plain
`ProgramArguments` agent cannot even open the gateway venv. Terminal is the
process that holds your Documents consent, so `com.user.ailocalgateway.plist`
runs:

```sh
/usr/bin/open -gj -a Terminal ~/Documents/local-ai/gateway/start_gateway.command
```

That hidden Terminal window detaches `run_gateway.sh` with `nohup` and exits;
the supervisor restarts LiteLLM on crash and keeps Documents access even after
the window closes. No Full Disk Access grant is required. Reload it with:

```sh
launchctl bootout gui/$(id -u)/com.user.ailocalgateway 2>/dev/null
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.user.ailocalgateway.plist
```

Check it with `sovereign gateway` (paths, aliases, supervisor state, restart
command). Closing the hidden window does not stop the gateway.

A second agent, `com.user.ailocalgateway.watchdog`, checks the gateway every five
minutes and asks Terminal to restart the supervisor if both the gateway and the
supervisor are gone. It runs only system binaries (`curl`, `open`), so launchd
never needs Documents access. Decisions are logged to
`/tmp/sovereign-gateway-watchdog.log`.

## Architecture

```text
Terminal / login agent
        │
        ▼
  Textual dashboard ───────────────┐
        │                          │
        ├── OllamaClient ──► 127.0.0.1:11434  (/api/tags, /api/ps, /api/chat)
        ├── Gateway check ─► 127.0.0.1:4000   (/v1/models)
        ├── Router ────────► model + context from free RAM
        ├── SessionStore ──► ~/Documents/local-ai/data/sessions/*.jsonl
        └── Clients ───────► Qwen Code / OpenCode (agent), Codex / Claude (chat)
```

## Development

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest -q
./bin/sovereign status
```

## Security

- Ollama and LiteLLM bind to loopback only; `sovereign doctor` fails if not.
- `OLLAMA_NO_CLOUD=1` comes from the profile environment.
- Session files are mode `0600`; no telemetry is sent anywhere.
- `sovereign code --yolo` is explicitly opt-in; the default asks before edits.

## Lineage

Built from the ideas in `~/Downloads/local-bar-main` and
`~/Downloads/local-bar-dev-main`: one resident coder, memory-aware context,
local-only clients, and a readiness check. This project keeps those ideas and
drops the Swift/SDK coupling and menu-bar-only workflow.
