# Improvements over the Local Bar projects

Both source projects are Swift menu-bar apps pinned to a particular Swift and
macOS SDK. They proved the product idea — one resident coder, memory-aware
context, loopback-only clients — but carried a lot of build and UI coupling.
Sovereign Code keeps the idea and changes the foundation.

## Build and runtime

- **No Swift/SDK pin.** Python 3.11+ and Textual; runs from source or a venv.
- **No `.app` bundle** required for the core experience.
- **One installer** (`sovereign install-login`) instead of a build + ditto +
  LaunchAgent sequence.
- **Runs headless** for status/doctor, so it is testable in CI.

## Architecture

- **Single settings model** (`Settings` dataclass + TOML + env overrides)
  instead of paths and preferences spread through Swift views.
- **Explicit model catalog** with roles and strengths; unknown installed tags are
  still displayed with their real size.
- **Pure selection function** (`router.choose`) — easy to unit test, shared by
  the dashboard, CLI, and Qwen launcher.
- **Concurrent status collection** with per-probe failure isolation; one dead
  service cannot freeze the UI.
- **Async streaming client** for Ollama, parsed from NDJSON with error events.
- **Append-only JSONL sessions** (mode 0600) instead of no history.
- **Suspend/resume** integration with Qwen Code, so the agent gets the real TTY.

## UX

- **Live terminal dashboard** with model list, loaded model/context, memory,
  gateway, and login state — no menu-bar window to find.
- **Streaming chat** with Markdown/code blocks and token/latency footer.
- **Mode commands** (`/code`, `/reason`, `/vision`, `/fast`) that re-route the
  model without editing config.
- **Doctor** with `PASS/WARN/FAIL`, a concrete fix for each row, and an exit code
  suitable for scripts.

## Safety

- **Loopback is checked**, not assumed; the doctor fails if either service is
  exposed.
- **No client auto-rewrite.** The old app aligned Codex/Claude/ChatGPT/etc. by
  editing their configs. Sovereign Code only writes its own
  `~/Documents/local-ai/config/codex/local.config.toml` and `*-local` wrappers
  under `~/Documents/local-ai/bin`; your cloud app settings
  are never touched, and `sovereign clients` reports what is installed.
- **Honest client capabilities.** Qwen Code and OpenCode are verified to edit
  files locally. Codex and Claude Code are wired to the loopback gateway for
  chat, but their streamed tool calls do not execute reliably through LiteLLM +
  Ollama, so the UI labels them chat-only instead of claiming parity.
- **Verified context ceilings.** The 14B coder runs at 32,768 tokens with
  flash attention and a q8_0 KV cache (12 GB resident); without those settings
  24k+ returns empty output. Agent models run with `think:false` so reasoning
  tokens cannot consume the whole reply budget.
- **Opt-in YOLO.** `sovereign code` uses Qwen's default approval mode unless
  `--yolo` is passed.
- **Local-only prompts** are stated in the system prompt and no telemetry is
  implemented.
- **One visible root.** All local AI state lives in `~/Documents/local-ai`
  (gateway, profiles, sessions, models, Qwen state, wrappers). `~/.ollama/models`
  and `~/.qwen` are symlinks, so stock tools keep working. The gateway is
  Terminal-supervised because macOS TCC blocks launchd from reading Documents.
- **Recoverable migration.** The previous `~/.local/ai-stack` is archived under
  `~/Documents/local-ai/legacy/` rather than deleted.
- **Self-healing gateway.** A TCC-safe watchdog checks the gateway every five
  minutes and restarts the supervisor through Terminal if it disappeared. The
  supervisor rotates its log at 5 MB and uses the port as a singleton lock.
- **Configs are versioned.** `~/Documents/local-ai` is a small git repo covering
  gateway config, supervisors, launch agents, and client wrappers; weights,
  venvs, and chats are ignored.
- **Backups are intentional.** Time Machine excludes the 34 GB model store,
  legacy archive, and gateway venv, while keeping configs and sessions eligible.
- **Both services self-heal.** Every five minutes the watchdog checks Ollama as
  well as the gateway. If Ollama is gone it kickstarts `com.user.ollama.env`,
  which reapplies flash attention and q8 KV before reopening the app. The
  supervisor now takes LiteLLM down on TERM, so a restart cannot orphan the
  port or leave an unsupervised process behind.
- **Operations are one command away.** `sovereign logs` tails the gateway,
  watchdog, or dashboard log; `sovereign sessions` lists chats and prunes by
  age while always keeping the newest N; `sovereign gateway --restart` performs
  a real stop/start and waits for health.
- **Self-repair and housekeeping.** `sovereign doctor --fix` applies the safe
  fixes (config, login agent, wrappers, Codex profile, launcher, Qwen rules).
  `sovereign backup` archives configs and chat data to a tarball that excludes
  models, the venv, Codex caches, and the browser profile. Optional
  `session_retention_days` prunes old chats at dashboard startup.
- **Local summarization.** `sovereign summarize FILE` (or `--url`) reads a source
  and returns a concise local-model summary without sending anything off-device.
- **Semantic code search.** `sovereign index` embeds a directory with
  `nomic-embed-text` and `sovereign search` ranks chunks by cosine similarity,
  so you can ask "where is X handled?" and get file:line answers. The index is
  local, rebuildable, and excluded from backups and Time Machine.
- **Browser operator.** `sovereign browse` drives a visible Chromium through
  Playwright with one structured action per local-model step, confirmation gates
  for destructive actions, secret-field refusal, CAPTCHA handoff, a URL policy,
  and a masked audit log. No stealth, spoofing, or CAPTCHA solving.
- **The stack can prove itself.** `sovereign verify` sends one short completion
  through the four core aliases (or all nine with `--all`) and fails on HTTP
  errors, malformed bodies, or empty replies. The thinking alias gets a 512-token
  budget because hidden reasoning would otherwise consume all 8 tokens.

## Testing

- 77 pytest tests cover model merging, router context behaviour, config,
  sessions/retention, logs, backup, summarization, semantic search, browser
  policy/agent/executor, memory, gateway probes, client launch planning, and
  headless TUI boot.
- Textual `run_test` exercises the real widget tree without a network.
