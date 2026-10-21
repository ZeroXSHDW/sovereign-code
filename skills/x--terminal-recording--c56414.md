---
name: terminal-recording
description: Record terminal demos as asciicasts. Use when the user wants to record a demo, capture a terminal session, create an asciicast, or produce a terminal recording. Manages recording via tmux so the main agent stays unblocked.
---

# terminal-recording

Record polished terminal demos as asciicast files using asciinema + tmux.

## Workflow Overview

1. **Setup** — prepare the demo scenario (stage files, break things, seed state)
2. **Record** — launch asciinema in a tmux session, run the demo command
3. **Compress** — use idle-time-limit to squash long waits (builds, API calls)
4. **Preview & Trim** — play back, inspect, and trim if needed

## Requirements

- [`asciinema`](https://asciinema.org/) — `brew install asciinema` / `pip install asciinema`
- `tmux` — so recording runs without blocking the agent
- `python3` — for the trim/compress post-processing snippets
- (optional) [`agg`](https://github.com/asciinema/agg) — to convert casts to GIF

## Recording Directory

Use `~/scratch/demos/` as the default output directory. Create it if missing.

```bash
mkdir -p ~/scratch/demos
```

## Core Commands

### 1. Setup a demo scenario

Before recording, prepare whatever state the demo needs:

```bash
# Example: create a broken file for a "fix this" demo
cat > /tmp/demo-broken.py << 'EOF'
def greet(name)
    print(f"Hello, {name}!")
EOF

# Example: seed a git repo with a specific state
cd /tmp && git init demo-repo && cd demo-repo && echo "hello" > README.md && git add . && git commit -m "init"
```

### 2. Record in a tmux session

Always record inside tmux so the main agent can monitor progress.

```bash
# -i 2 compresses idle time to max 2 seconds during recording
# --cols/--rows set consistent terminal size for clean playback
CAST_FILE=~/scratch/demos/my-demo-$(date +%Y%m%d-%H%M%S).cast
tmux new-session -d -s demo-rec \
  "asciinema rec '$CAST_FILE' \
    -i 2 \
    --cols 120 --rows 35 \
    -t 'My Demo Title' \
    --overwrite \
    -c 'bash /tmp/demo-script.sh'"
```

**Key flags:**
- `-i <seconds>` — idle time limit; compresses pauses (builds, API calls) to this max. Use `2` for snappy demos, `3-5` for breathing room.
- `--cols 120 --rows 35` — standardized terminal size for consistent playback.
- `-c '<command>'` — the command to record. Wrap in single quotes.
- `--overwrite` — replace existing file if re-recording.
- `-t '<title>'` — title embedded in the cast file.

### 3. Monitor the recording

```bash
tmux has-session -t demo-rec 2>/dev/null && echo "RECORDING" || echo "DONE"
tmux capture-pane -t demo-rec -p -S -30 2>/dev/null
```

### 4. Stop recording early (if needed)

```bash
# End the recorded shell/command gracefully
tmux send-keys -t demo-rec 'exit' Enter
# Or kill it hard
tmux kill-session -t demo-rec 2>/dev/null
```

### 5. Preview the recording

```bash
asciinema play ~/scratch/demos/my-demo.cast
asciinema play -s 2 ~/scratch/demos/my-demo.cast   # 2x speed

# Metadata / header
head -1 ~/scratch/demos/my-demo.cast | python3 -m json.tool

# Duration (last event timestamp)
tail -1 ~/scratch/demos/my-demo.cast | python3 -c "import sys,json; print(f'{json.loads(sys.stdin.read())[0]:.1f}s')"
```

### 6. Trim the recording

asciinema v2 cast files are newline-delimited JSON. First line is the header,
the rest are `[timestamp, type, data]` events.

```bash
CAST=~/scratch/demos/my-demo.cast

# Keep only the first 30 seconds
python3 -c "
import json
with open('$CAST') as f:
    header = f.readline()
    events = [json.loads(l) for l in f]
trimmed = [e for e in events if e[0] <= 30.0]
with open('${CAST%.cast}-trimmed.cast', 'w') as out:
    out.write(header)
    for e in trimmed:
        out.write(json.dumps(e) + '\n')
print(f'Kept {len(trimmed)}/{len(events)} events')
"

# Shift leading dead time so playback starts at the first output
python3 -c "
import json
with open('$CAST') as f:
    header = f.readline()
    events = [json.loads(l) for l in f]
if events:
    offset = events[0][0]
    for e in events:
        e[0] = round(e[0] - offset, 6)
with open('${CAST%.cast}-shifted.cast', 'w') as out:
    out.write(header)
    for e in events:
        out.write(json.dumps(e) + '\n')
print(f'Shifted {len(events)} events by {offset:.1f}s')
"

# Cap idle gaps post-recording (tighter than -i during capture)
python3 -c "
import json
MAX_GAP = 1.5
with open('$CAST') as f:
    header = f.readline()
    events = [json.loads(l) for l in f]
if len(events) > 1:
    new_time = events[0][0]
    for i in range(1, len(events)):
        gap = events[i][0] - events[i-1][0]
        new_time += min(gap, MAX_GAP)
        events[i][0] = round(new_time, 6)
with open('${CAST%.cast}-compressed.cast', 'w') as out:
    out.write(header)
    for e in events:
        out.write(json.dumps(e) + '\n')
print(f'Compressed {len(events)} events (max gap: {MAX_GAP}s)')
"
```

## Patterns

### Quick single-command demo

```bash
CAST_FILE=~/scratch/demos/quick-$(date +%Y%m%d-%H%M%S).cast
tmux new-session -d -s demo-rec \
  "asciinema rec '$CAST_FILE' -i 2 --cols 120 --rows 35 -t 'Quick Demo' --overwrite -c 'ls -la && git status'"
while tmux has-session -t demo-rec 2>/dev/null; do sleep 3; done
echo "Recording saved to $CAST_FILE"
```

### Multi-step scripted demo

```bash
cat > /tmp/demo-script.sh << 'SCRIPT'
#!/bin/bash
echo "=== Demo: Fixing a Python bug ==="
sleep 1
cat /tmp/demo-broken.py
sleep 2
echo ""
echo "Applying the fix..."
sleep 1
sed -i '' 's/def greet(name)/def greet(name):/' /tmp/demo-broken.py
python3 /tmp/demo-broken.py Ada
SCRIPT
chmod +x /tmp/demo-script.sh

CAST_FILE=~/scratch/demos/scripted-$(date +%Y%m%d-%H%M%S).cast
tmux new-session -d -s demo-rec \
  "asciinema rec '$CAST_FILE' -i 2 --cols 120 --rows 35 -t 'Bug Fix Demo' --overwrite -c '/tmp/demo-script.sh'"
```

### Interactive demo (user drives)

```bash
CAST_FILE=~/scratch/demos/interactive-$(date +%Y%m%d-%H%M%S).cast
tmux new-session -d -s demo-rec \
  "asciinema rec '$CAST_FILE' -i 3 --cols 120 --rows 35 -t 'Interactive Demo' --overwrite"
echo "Attach with: tmux attach -t demo-rec"
echo "Type 'exit' when done recording."
```

## Tips

- **Idle time limit (`-i`)** is the single most important flag. Without it, API calls and builds create unwatchable dead time. Use `-i 2` for most demos.
- **Consistent terminal size** (`--cols 120 --rows 35`) makes playback look the same everywhere.
- **Post-recording compression** can further tighten gaps beyond what `-i` does during capture.
- **Session name `demo-rec`** is the convention. Kill it before re-recording: `tmux kill-session -t demo-rec 2>/dev/null`.
- **Preview before sharing** — always `asciinema play` to check pacing.
- Cast files are plain text (NDJSON) — easy to inspect, edit, and version control.
- For GIFs: `agg my-demo.cast my-demo.gif` (install with `cargo install --git https://github.com/asciinema/agg`).
