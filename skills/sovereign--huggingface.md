---
name: sovereign-huggingface
description: Search, inspect, authenticate, and download models from the Hugging Face Hub with `sovereign hf`. Use when the user wants a model that is not in the Ollama catalog, needs a GGUF quant, or asks where model files live.
---

# Sovereign Hugging Face

Use the Hub when a model is not available as an Ollama tag, or when the user
needs a specific GGUF quantization. Search and inspection are read-only.
Downloads are explicit and file-selective by default.

1. Check authentication and paths:

   ```sh
   sovereign hf status
   ```

2. Search, preferring GGUF for local Ollama use:

   ```sh
   sovereign hf search "qwen coder" --gguf --limit 10
   sovereign hf search "mlx llama" --sort likes
   ```

3. Inspect a repository before downloading. This shows gated status, storage,
   GGUF context length, and file sizes:

   ```sh
   sovereign hf info org/model-GGUF
   sovereign hf info org/model-GGUF --files
   sovereign hf info org/model-GGUF --json
   ```

4. Download only the files you need. A pattern is required unless `--all` is
   passed, because GGUF repositories often contain many quantizations and can
   be tens to hundreds of GB:

   ```sh
   sovereign hf download org/model-GGUF --include "*Q4_K_M.gguf"
   sovereign hf download org/model --include "*.safetensors" --include "*.json"
   sovereign hf download org/model-GGUF --include "*Q4_K_M.gguf" --dry-run
   ```

   The destination defaults to
   `~/Documents/local-ai/models/huggingface/<org>--<repo>`. Use
   `--local-dir PATH` to choose another folder, or `--cache-dir PATH` to
   override the Hub cache. Large downloads ask for confirmation; `--yes`
   skips the prompt for scripts.

5. Import a GGUF into Ollama when it is the single model file in the folder:

   ```sh
   ollama create my-model -f <(printf 'FROM %s\n' \
     "$HOME/Documents/local-ai/models/huggingface/org--repo/model-Q4_K_M.gguf")
   ```

   Then check it with `ollama list` and `sovereign models`.

## Authentication

Never put a token in a prompt, a repository file, or `config.toml`.

```sh
sovereign hf login          # hidden prompt; writes ~/.cache/huggingface/token (0600)
pbpaste | sovereign hf login --token-stdin
sovereign hf login --browser  # delegate to `hf auth login` OAuth flow
sovereign hf logout
```

The token is stored in the same file as `hf` and `huggingface_hub`, so it also
works for `transformers`, `vllm`, `mlx-lm`, and plain `hf download`. If
`HF_TOKEN` is exported, it takes precedence over the saved file. Gated models
still require accepting the licence on the model page.

## Locations

| What | Path |
| --- | --- |
| Hub token | `~/.cache/huggingface/token` (or `$HF_TOKEN_PATH`) |
| Hub cache | `~/.cache/huggingface/hub` (or `$HF_HOME`) |
| Sovereign downloads | `~/Documents/local-ai/models/huggingface` |
| Ollama weights | `~/.ollama/models` → `~/Documents/local-ai/models` |
| Repo skills | `~/Documents/sovereign-code/skills` |
| User prompt skills | `~/Documents/local-ai/config/skills` |
| Installed skills | `~/.claude/skills`, `~/.codex/skills`, `~/.qwen/skills`, `~/.config/opencode/skills`, `~/.continue/prompts` |

## Rules

- Search/inspect first; do not guess a repository id.
- Do not download `--all` unless the user explicitly wants every quantization.
- Prefer a GGUF quant that fits the machine's unified memory. On this 24 GB Mac,
  Q4_K_M at roughly 4-9 GB is usually the right balance for 7B-14B models.
- Report the exact destination and selected files after a download.
- Never echo a token, even partially. `sovereign hf status` shows only the
  source and the account name.
