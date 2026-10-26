# Sovereign Code Wiki

**A terminal-first, local-first AI coding console for Apple Silicon.**

Nothing leaves your Mac by default. Ollama and every gateway bind to
`127.0.0.1`; cloud models are an explicit opt-in (`sovereign cloud`) that the
router never selects on its own.

## What it does

Sovereign Code puts a tier gateway in front of your local models and routes
each request to the right one:

| Tier | Model | Used for |
| --- | --- | --- |
| `fast` | `qwen3.5:4b` | short questions, one-line edits |
| `balanced` | `qwen3.5:9b` | tools, multi-turn, large prompts |
| `deep` | `qwen3-coder:30b` | code and analysis |
| `ultra` | `qwen3.8:27b` | hardest reasoning |

It makes Codex, Claude Code, OpenCode, Qwen Code and Continue work as **real
agents** — not chat wrappers — against those local models, with streamed tool
calls, a policy-checked browser, PDF/OCR, Hugging Face, task packs, skills, and
an MCP server for the desktop apps.

## Menu bar

The `Sovereign Local` menu bar controller puts the stack one click away:

![Sovereign Local menu bar](https://raw.githubusercontent.com/ZeroXSHDW/sovereign-code/main/docs/assets/menu-bar.png)

Live gateway and per-tier latency, the resident model and free memory, and
one-click local/cloud switches. Install it with:

```sh
sovereign local-bar --install --open
```

## Quick start

```sh
git clone https://github.com/ZeroXSHDW/sovereign-code
cd sovereign-code
./scripts/bootstrap.sh
sovereign                       # the live monitor
```

Verify and pull a starter stack:

```sh
sovereign doctor
sovereign setup-stack lean      # ~8 GB; `capable` for the best coder
sovereign verify --clients      # a real turn through Codex, Claude Code, OpenCode
```

## Everyday commands

```sh
sovereign status                # one-shot stack status
sovereign models                # installed + recommended
sovereign chat                  # streaming chat (with /resume, /model, /browse …)
sovereign do "fix the test"     # one-shot coding: plan → implement → verify → review
sovereign pull <tag>            # any Ollama model
sovereign hf import org/repo    # any Hugging Face GGUF
sovereign model-use <tag>       # select a model for OpenCode/Codex/Claude
sovereign summarize --dir .     # what does this codebase do
sovereign pack pentest brief    # task packs with guardrails + SCOPE gating
```

## Where things live

- `runtime/` — fresh-install state: gateway config, sessions, models, logs.
  Legacy installs use `~/Documents/local-ai`; `SOVEREIGN_HOME` overrides either.
- `docs/ARCHITECTURE.md` — modules, data flow, ports.
- `docs/ROADMAP.md` — current status and next work.
- `docs/v0.6.0-VERIFICATION.md` — the live-hardware verification checklist.

## Links

- [README](https://github.com/ZeroXSHDW/sovereign-code#readme)
- [Changelog](https://github.com/ZeroXSHDW/sovereign-code/blob/main/CHANGELOG.md)
- [Architecture](https://github.com/ZeroXSHDW/sovereign-code/blob/main/docs/ARCHITECTURE.md)