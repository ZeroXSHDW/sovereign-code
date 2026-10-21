---
name: tmux-runner
description: Run background processes and parallel tasks in tmux sessions. Use when you need to run long-running processes (builds, dev servers, file watchers), kick off background work, run parallel tasks, or spawn parallel agent/CLI instances. The go-to skill for anything that should run without blocking the main agent.
---

# tmux-runner

Run background processes and parallel sub-tasks in tmux sessions. Use this for
anything that should run without blocking the main agent: builds, dev servers,
file watchers, test suites, parallel CLI/agent instances, etc.

## Key Concept: Session Lifetime

By default, a tmux session **dies when its command exits**. This matters:

| Mode | Behavior | Use when |
|------|----------|----------|
| **One-shot** | Session runs a command, then disappears | Builds, tests, single prompts — anything with a natural end |
| **Persistent** | Session stays open for interaction | Dev servers, interactive sessions, REPLs |
| **Remain-on-exit** | Command runs, session stays open for inspection | You need to read final output after a one-shot command completes |

## Core Commands

### Spawn a one-shot session

The session runs the command and exits when it finishes.

```bash
# Run a build in the background
tmux new-session -d -s build 'cd /path/to/project && make build'

# Run a CLI task non-interactively (write complex prompts to a file first)
echo "Analyze the error handling in src/handler.ts" > /tmp/task-prompt.md
tmux new-session -d -s analysis 'cd /path/to/project && my-agent -f /tmp/task-prompt.md'
```

**Capturing output from one-shot commands:** Since the session dies when the
command exits, redirect output to a file:

```bash
# Redirect stdout+stderr to a file (works for builds, scripts, etc.)
tmux new-session -d -s build 'make build > /tmp/build.log 2>&1'

# Check results after completion
tmux has-session -t build 2>/dev/null && echo "Still running" || cat /tmp/build.log
```

> ⚠️ **Do NOT pipe/redirect output of a TUI program** (interactive agents,
> `top`, `vim`, etc.) — it breaks their rendering. Use `tmux capture-pane`
> instead (see below).

### Spawn a persistent session

For interactive tools or long-running servers that don't have a natural exit.

```bash
# Interactive session the user can attach to
tmux new-session -d -s helper 'cd /path/to/project && my-repl'

# Dev server
tmux new-session -d -s devserver 'cd /path/to/project && npm run dev'

# File watcher
tmux new-session -d -s watcher 'cd /path/to/project && npx nodemon src/index.ts'
```

### Spawn with remain-on-exit (one-shot + inspectable)

When you need a one-shot command but want to read output after it finishes:

```bash
# Create session, set remain-on-exit, then run the command
tmux new-session -d -s build 'make build'
tmux set-option -t build remain-on-exit on

# After the command finishes, the session stays open — you can still capture-pane
tmux capture-pane -t build -p -S - 2>/dev/null
# Clean up manually when done
tmux kill-session -t build
```

> Note: `remain-on-exit` must be set *after* session creation or the session
> starts in a dead state.

## Monitoring & Interaction

### Check session status

```bash
# Is it still running?
tmux has-session -t <name> 2>/dev/null && echo "RUNNING" || echo "GONE"

# List all sessions
tmux list-sessions 2>/dev/null || echo "No active sessions"
```

### Capture output from a live session

Use `capture-pane` for interactive programs or anything where you didn't
redirect to a file:

```bash
# Last 50 lines
tmux capture-pane -t <name> -p -S -50 2>/dev/null

# Entire scrollback
tmux capture-pane -t <name> -p -S - 2>/dev/null
```

### Send input to a session

```bash
tmux send-keys -t <name> 'some text' Enter
```

### Kill sessions

```bash
# Kill one
tmux kill-session -t <name> 2>/dev/null

# Kill all
tmux kill-server 2>/dev/null
```

## Patterns

### Fan-out / Fan-in (parallel tasks)

Spawn multiple tasks, poll for completion, collect results.

```bash
# Write prompts
echo "Review file A for error handling" > /tmp/prompt1.md
echo "Review file B for error handling" > /tmp/prompt2.md

# Fan out — each instance writes to its own output file
tmux new-session -d -s task1 'my-agent -f /tmp/prompt1.md -o /tmp/result1.md'
tmux new-session -d -s task2 'my-agent -f /tmp/prompt2.md -o /tmp/result2.md'

# Poll until all done
while tmux has-session -t task1 2>/dev/null || \
      tmux has-session -t task2 2>/dev/null; do
  sleep 5
done

# Fan in
cat /tmp/result1.md /tmp/result2.md
```

### Fire-and-check (long-running background work)

Kick off a slow process, continue working, check back later.

```bash
# Fire — redirect to log file, and record the exit code on completion
tmux new-session -d -s slowbuild 'make build > /tmp/slowbuild.log 2>&1; echo "EXIT:$?" >> /tmp/slowbuild.log'

# ... do other work ...

# Check status
if tmux has-session -t slowbuild 2>/dev/null; then
  echo "Still running — last 10 lines:"
  tail -10 /tmp/slowbuild.log
else
  echo "Finished — exit status:"
  tail -1 /tmp/slowbuild.log
fi
```

### Background server with health check

```bash
# Start server
tmux new-session -d -s api 'cd /path/to/service && npm start'

# Wait for it to be ready
for i in $(seq 1 30); do
  curl -sf http://localhost:3000/health && break || sleep 1
done

# Now run tests against it
pytest tests/integration/

# Clean up
tmux kill-session -t api 2>/dev/null
```

## Tips

- **Use `/tmp/<name>.{log,out,md}` for output files** — they survive session exit and are easy to find.
- **Keep session names short and descriptive** — they're your task handles (`build`, `test`, `devserver`).
- **Always check `tmux has-session` before `capture-pane`** to avoid errors on dead sessions.
- **Clean up sessions when done** — resource leaks add up. Kill one-off sessions after reading results.
- **For interactive/TUI programs, never redirect stdout** — use `capture-pane` or the program's own output flag.
- **For non-interactive processes, always redirect to a log file** — scrollback is limited and lost when sessions die.
- **Capture exit codes** by appending `; echo "EXIT:$?"` to commands when you need to distinguish success from failure.
