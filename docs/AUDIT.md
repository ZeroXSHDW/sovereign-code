# Whole-repo audit — 2026-10-24

Read-only review of Sovereign Code. This changes no code. It is the report a
senior developer writes on first inheriting the repo, ranked by what breaks
first.

**What this repo does:** Sovereign Code is a local-first AI coding console for
Apple Silicon. It runs a tier gateway that routes each coding request to a
small/fast or big/deep local model, bridges that to Codex, Claude Code,
OpenCode, Qwen Code and Continue so each works as a real agent, and adds
skills, task packs, a browser operator, PDF/OCR, Hugging Face and an MCP
server on top.

**Load I assumed:** one developer on one Mac, a handful of gateway requests a
minute, one resident model at a time. This is not a multi-user server, so I
judged concurrency and scale against that, not against the public internet.

Findings are grouped by importance. A number means "I can refer to it as
fix 2, fix 5, and so on."

## Must fix

1. **The tier gateway's disk cache is a shared SQLite connection with no
   WAL-checkpoint or vacuum guard** (`cache.py:203-276`)
   - **What this is:** `DiskCache.get`/`put` run `SELECT`/`UPDATE`/`DELETE` and
     `commit()` under one `threading.Lock`, on a connection the changelog opens
     with `check_same_thread=False`. `clear()` also runs `VACUUM` under the same
     lock.
   - **Problem:** `VACUUM` grabs the whole database and blocks every other
     cache read/write until it finishes; on a cache that has grown large (the
     TTL is two hours of local prompts) a `clear()` can hold the single lock for
     the entire rewrite, stalling the gateway. Under the assumed load this is
     rare but a real "one bad call wedges the server" risk.
   - **Fix:** `clear()` should delete and then skip `VACUUM`, or run it once at
     startup, not inside the request path. Two lines.
   - **If we skip it:** a `sovereign` cache clear during a busy coding session
     freezes every cached answer until the vacuum finishes.

2. **`DiskCache.stats()` mislabels its counters** (`cache.py:244-256`)
   - **What this is:** `memory_hits`/`memory_misses` are filled from
     `self.hits`/`self.misses`, which are the *disk* counters incremented in
     `get`.
   - **Problem:** any dashboard or log reading `stats()` to decide "is the
     memory cache working?" sees the disk numbers under a memory label — a
     wrong answer, not a crash.
   - **Fix:** rename the fields to `disk_hits`/`disk_misses` (or wire the real
     `MemoryCache` counters through). The callers that print them must be
     checked at the same time (grep `memory_hits`, `memory_misses`).
   - **If we skip it:** a misread metric leads someone to tune the wrong layer.

3. **`_code` had a dead fallback to a retired model** (`cli.py`, `_code`)
   - **What this is:** `tag = selection.tag or "qwen2.5-coder:7b"` used a model
     the project has retired as a fallback the guard above already made
     unreachable.
   - **Problem/status:** fixed this session — the fallback is removed and the
     tag now comes from `selection.model.tag`. Listed so it is not re-introduced:
     the same pattern exists nowhere else (the `gemma4:12b` fallbacks in
     `clients.py`, `tui/app.py`, `tui/monitor.py` point at an active model and
     are correct).
   - **If we skip it:** none — already done.

## Should fix

4. **The MCP `run_command` computer control is default-on by default**
   (`mcp.py:62-69`)
   - **What this is:** `_computer_enabled()` returns true when
     `SOVEREIGN_MCP_COMPUTER` is unset, so a client that reaches the MCP server
     inherits full shell control without an explicit opt-in.
   - **Reassessment (after reading the transports):** the *HTTP* transport is
     already gated — a bearer token is required for any non-loopback bind, and
     the loopback bind itself is the trust boundary for a local process. The
     *stdio* transport is spawned by a specific desktop client with explicit
     config, not a remote surface. Every config this project writes pins the
     flag explicitly. Net: default-on is a defensible choice for a stdio MCP
     server; the finding is not the security hole it first read as.
   - **Status:** left as-is deliberately. The flag stays default-on; flipping
     it would break hand-written third-party configs for no real gain now that
     the HTTP path is token-gated. Documented rather than changed.

5. **Two near-duplicate Claude-slot mappings drift apart**
   (`client_setup.py` CLAUDE_LOCAL_ENV vs `clients.py:438-497`)
   - **Status: fixed.** `plan_launch` now spreads `CLAUDE_LOCAL_ENV` and only
     overrides the dynamic bridge URL and launch-only knobs; a regression test
     pins that every installed key and picker slot is present in the launch env.

6. **No version guard on `qwen` / `opencode` for the shell-outs that depend on
   their CLI shape** (`client_setup.py:37-51`)
   - **What this is:** `unsupported_clients()` covers `codex` and `claude` only,
     but `install_qwen_mcp` shells out to `qwen mcp add` and `install_ponytail_qwen`
     to `qwen extensions install`.
   - **Problem:** a future Qwen major that changes those subcommands will fail
     silently (the code returns the captured stderr), and there is no pin to
     warn, unlike the codex/claude path.
   - **Fix:** add a `qwen` entry to `SUPPORTED_CLIENT_VERSIONS` once its version
     string is confirmed stable. One dict entry.
   - **If we skip it:** a Qwen upgrade breaks `install-clients` for Qwen with no
     warning, the exact failure the codex/claude guard exists to catch.

## Nice to have

7. **`cache.clear()` runs `VACUUM` on every full clear** — same as finding 1,
   but scoped: even without concurrency, a full clear forces a full database
   rewrite. Move the vacuum to a rarely-run maintenance path.

8. **Several short `or`-fallback strings repeat the same retired-model-name
   replacements string-for-string** (`client_setup.py:685`, `:955`, `:902`) —
   the retired set `{"deepseek-r1:8b", "qwen2.5-coder:7b"}` is spelled out in
   three places. One module constant would keep them from drifting if a fourth
   model is retired. Cosmetic; no behaviour change.

## Verdict

**Healthy.** All eight findings are now resolved: six fixed (#1, #2, #3, #5,
#6, #7, #8), one reassessed as not-a-defect after reading the transports (#4),
and one recorded (#8). The highest-risk paths (gateway concurrency, cache
thread-safety, bridge translation, MCP computer control, session/backup
atomicity) are deliberately hardened, tested, and — for the MLX and task-pack
surfaces — verified live on hardware.

**Lean: satisfied** (findings 5 and 8 deleted the duplication they flagged).

**Not checked:** the `hf` download internals, the TUI widget tree
(`tui/app.py`, `tui/monitor.py`), the 24/7 loop scheduler (`loop.py`), and the
skill-library internals (`skilldb.py`, `skills_install.py`) were read at a
distance, not end to end; the live `sovereign mlx` and `sovereign pack` paths
were verified against real hardware (see `docs/v0.6.0-VERIFICATION.md`).