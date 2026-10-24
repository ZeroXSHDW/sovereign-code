# Clients

Codex, Claude Code, OpenCode, Qwen Code and Continue all run on-Mac as real
agents against the local models.

```sh
sovereign launch opencode [path]
sovereign launch codex   [path]
sovereign launch claude  [path]
sovereign launch qwen    [path]
sovereign launch codium  [path]
```

`--cloud` is the explicit escape hatch for Codex/Claude and requires a login;
the local path never changes without you asking for it.

`sovereign verify --clients` proves a real turn through Codex, Claude Code and
OpenCode — the difference between "configured" and "working".

Each client gets the `sovereign` MCP server, which exposes models, skills, the
policy-checked browser, file edits, and (pinned explicitly) full computer
control via `run_command`.