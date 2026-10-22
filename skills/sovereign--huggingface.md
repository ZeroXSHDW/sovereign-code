---
name: sovereign-huggingface
description: Search, inspect, authenticate, download, and clean up models and datasets from the Hugging Face Hub with `sovereign hf`, including one-step import into Ollama. Use when the user wants a model or dataset that is not in the Ollama catalog, needs a specific GGUF quant, asks where Hub files live, or wants to free Hub disk space.
---

# Sovereign Hugging Face

Use the Hub when a model is not available as an Ollama tag, when the user needs
a specific GGUF quantization, or when a project needs a dataset. Search and
inspection are read-only. Downloads are explicit and file-selective by default.

1. Check authentication and paths:

   ```sh
   sovereign hf status
   ```

2. Search models, preferring GGUF for local Ollama use:

   ```sh
   sovereign hf search "qwen coder" --gguf --limit 10
   sovereign hf search "mlx llama" --sort likes
   sovereign hf search "coder" --gguf --license apache-2.0 --language en
   ```

   Search datasets with `--dataset`; add `--format`, `--license`, `--language`,
   `--filter TAG`, or `--pipeline` to narrow results:

   ```sh
   sovereign hf search "ultrachat" --dataset --format parquet --limit 5
   sovereign hf search "code instructions" --dataset --license mit
   ```

3. Inspect a repository before downloading. This shows gated status, storage,
   licence, languages, formats, base models, GGUF context length, and file
   sizes. Add `--readme` for the human-readable model or dataset card:

   ```sh
   sovereign hf info org/model-GGUF
   sovereign hf info org/model-GGUF --files --readme
   sovereign hf info HuggingFaceH4/ultrachat_200k --dataset --files
   sovereign hf info org/model-GGUF --json
   ```

4. Download only the files you need. A pattern is required unless `--all` is
   passed, because GGUF repositories often contain many quantizations and can
   be tens to hundreds of GB:

   ```sh
   sovereign hf download org/model-GGUF --include "*Q4_K_M.gguf"
   sovereign hf download org/model --include "*.safetensors" --include "*.json"
   sovereign hf download org/data --dataset --include "*.parquet"
   sovereign hf download org/model-GGUF --include "*Q4_K_M.gguf" --exclude "*.bin"
   sovereign hf download org/model-GGUF --include "*Q4_K_M.gguf" --dry-run
   ```

   The destination defaults to
   `~/Documents/local-ai/models/huggingface/<org>--<repo>` for models and
   `~/Documents/local-ai/datasets/huggingface/<org>--<repo>` for datasets. Use
   `--local-dir PATH` to choose another folder, `--cache-dir PATH` to override
   the Hub cache, and `--max-workers N` to tune parallelism. Large downloads ask
   for confirmation; `--yes` skips the prompt for scripts.

5. Import one GGUF into Ollama. `hf import` downloads the selected file first
   when it is not already present, then generates a temporary Modelfile:

   ```sh
   sovereign hf import org/model-GGUF --include "*Q4_K_M.gguf" --name qwen-coder:7b
   sovereign hf import org/model-GGUF --include "*Q8_0.gguf" --context 32768
   sovereign hf import /path/to/model.gguf --dry-run
   ```

   Split GGUFs (`*-00001-of-00004.gguf`) are rejected because Ollama needs a
   single file. Choose a single-file quantization or merge the parts first.
   After import, check it with `ollama list`, `sovereign models`, and
   `ollama run <name>`.

6. List or remove local copies. `hf list` covers model and dataset downloads
   plus the shared Hub cache. `hf remove` shows the size and deletes only the
   exact download/cache paths for that repository:

   ```sh
   sovereign hf list
   sovereign hf list --dataset
   sovereign hf remove org/model-GGUF --yes
   sovereign hf remove org/data --dataset --yes
   ```

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
and datasets still require accepting the licence on their Hub page.

## MCP

MCP exposes discovery and local inventory only; downloads stay in the CLI:

- `hf_status` — token source, mode, CLI, cache and download paths.
- `search_hf_models` / `hf_model_info` — model search and inspection.
- `search_hf_datasets` / `hf_dataset_info` — dataset search and inspection.
- `list_hf_local` — models, datasets, and Hub cache already on this Mac.

## Locations

| What | Path |
| --- | --- |
| Hub token | `~/.cache/huggingface/token` (or `$HF_TOKEN_PATH`) |
| Hub cache | `~/.cache/huggingface/hub` (or `$HF_HOME`) |
| Model downloads | `~/Documents/local-ai/models/huggingface` |
| Dataset downloads | `~/Documents/local-ai/datasets/huggingface` |
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
- For datasets, download the specific split or format files the project needs;
  do not pull a full multi-GB dataset by default.
- Use `hf import` rather than hand-writing a Modelfile, unless the user asks
  for custom parameters.
- Never echo a token, even partially. `sovereign hf status` shows only the
  source, file mode, and account name.
- `hf remove` is destructive but scoped to one repository; confirm the path and
  size before passing `--yes`.
