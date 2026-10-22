---
name: sovereign-delegate
description: Use the local Sovereign stack from ChatGPT or Claude. Lists models and skills, asks the tier gateway, reads project context, and runs the project's own checks. Use when the user wants a local model, a second opinion, or verification on this Mac.
---

# Sovereign delegate

The `sovereign` MCP server exposes the local stack. Prefer it when the user asks
for a local model, a second opinion, code review, or project verification.

1. Call `list_models` to see what is installed and which tier gateway is live.
2. For a quick answer, call `ask` with `model: "fast"`.
3. For code, debugging, or design, call `ask` with `model: "deep"` and include
   the smallest relevant context.
4. Use `list_skills` / `get_skill` when a specialized workflow fits; pass the
   relevant code to `ask` as context rather than dumping the whole repository.
5. Use `project_context` for saved project memory and `run_checks` to run the
   project's tests. Report the check result, not just the model's opinion.

Do not claim a local model ran if the `ask` call failed. The gateway reports
missing models, provider keys, and Ollama Cloud plan errors explicitly.
