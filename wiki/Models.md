# Models

Everything runs on Apple Silicon through Ollama, with an optional `mlx-lm`
server for native Metal execution.

## Selecting a model

```sh
sovereign model-use <tag>            # OpenCode, Codex and Claude
sovereign model-use --domain legal   # a specialist domain
sovereign model-use --list           # what each client is using now
sovereign run <model> "…"            # one prompt through one model
```

## Pulling

```sh
sovereign pull qwen3.8:27b           # any Ollama tag
sovereign pull-stack capable         # a curated offline stack
sovereign hf import org/repo --include "*Q4_K_M.gguf" --name mine
```

## The tiers

The gateway routes by request size and intent — you usually name `fast`,
`balanced`, `deep`, `ultra`, `best`, or `auto`, not a specific model, and the
router picks the strongest installed model that fits.

## MLX (Apple Silicon native)

```sh
sovereign mlx start --model mlx-qwen3-4b-4bit   # supervised, with a 0.6B draft
sovereign mlx status
sovereign mlx stop
```

`sovereign run` routes MLX tags to the MLX server automatically.

## Cloud (opt-in only)

```sh
sovereign cloud --set-key openrouter   # prompts then leave the Mac on that route
```

Local-first is the default; the router never picks a cloud model on its own.