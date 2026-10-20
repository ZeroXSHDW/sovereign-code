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
  `~/.codex/local.config.toml` and `*-local` wrappers; your cloud app settings
  are never touched, and `sovereign clients` reports what is installed.
- **Honest client capabilities.** Qwen Code and OpenCode are verified to edit
  files locally. Codex and Claude Code are wired to the loopback gateway for
  chat, but their streamed tool calls do not execute reliably through LiteLLM +
  Ollama, so the UI labels them chat-only instead of claiming parity.
- **Verified context ceilings.** The 14B coder is capped at 20,480 tokens
  (24k+ returns empty output); agent models run with `think:false` so reasoning
  tokens cannot consume the whole reply budget.
- **Opt-in YOLO.** `sovereign code` uses Qwen's default approval mode unless
  `--yolo` is passed.
- **Local-only prompts** are stated in the system prompt and no telemetry is
  implemented.

## Testing

- 26 pytest tests cover model merging, router context behaviour, config,
  sessions, memory, client launch planning, and headless TUI boot.
- Textual `run_test` exercises the real widget tree without a network.
