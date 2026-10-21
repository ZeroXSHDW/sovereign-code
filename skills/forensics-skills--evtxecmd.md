---
name: evtxecmd
version: 1.0.0
description: Parse and extract Windows Event Log (.evtx) files using Eric Zimmerman's EvtxECmd. Covers CLI flags, output formats (CSV/JSON/XML), event filtering, Volume Shadow Copy support, and the map system.
metadata:
  tool-name: EvtxECmd
  tool-vendor: Eric Zimmerman
---

# EvtxECmd Skill

EvtxECmd is a Eric Zimmerman's tool that uses maps to extract and normalize many event types into structured output suitable for timeline analysis and forensic investigation. Forensic interpretation of event logs (Event ID meanings, investigation workflows, lateral movement analysis, etc.) belongs in a separate analysis skill.

## Command Syntax

```
EvtxECmd.exe -f <file> [--csv <dir> | --json <dir> | --xml <dir>] [other options]
EvtxECmd.exe -d <directory> ...
```

Single-letter options use a single dash (`-`). Multi-character options use double dashes (`--`).

## Input (one required)

| Flag | Description |
|------|-------------|
| `-f` | Single .evtx file to process |
| `-d` | Directory containing .evtx files to process |

## Output Formats

| Flag | Description |
|------|-------------|
| `--csv` | Directory to write CSV output |
| `--csvf` | Custom filename for CSV output (overrides default) |
| `--json` | Directory to write JSON output |
| `--jsonf` | Custom filename for JSON output (overrides default) |
| `--xml` | Directory to write XML output |
| `--xmlf` | Custom filename for XML output (overrides default) |

It's recommended to specify at least one output format to write results to a file. Forensic output can be very large and may consume the context window. CSV is the most common choice for analysis with Timeline Explorer or Excel.

## Filtering

Use UTC consistently when filtering and correlating logs; do not mix local-time assumptions with UTC filter values.

| Flag | Description |
|------|-------------|
| `--inc` | Include only these Event IDs (comma-separated) |
| `--exc` | Exclude these Event IDs (comma-separated) |
| `--sd` | Start date (UTC) -- drop events older than this |
| `--ed` | End date (UTC) -- drop events newer than this |

## Options

| Flag | Description | Default |
|------|-------------|---------|
| `--dt` | Custom date/time format string | `yyyy-MM-dd HH:mm:ss.fffffff` |
| `--maps` | Path to event map files | `Maps` folder next to the executable |
| `--vss` | Process Volume Shadow Copies on the drive | FALSE |
| `--dedupe` | Deduplicate across -f/-d and VSCs by SHA-1 | TRUE |
| `--sync` | Download latest maps from GitHub before processing | FALSE |
| `--fj` | Include full JSON payload in output | FALSE |
| `--tdt` | Time discrepancy threshold in seconds | 1 |
| `--met` | Show processing metrics | TRUE |
| `--debug` | Show debug information | FALSE |
| `--trace` | Show trace information | FALSE |

## Common Output Fields (CSV)

When EvtxECmd processes logs through its maps, it normalizes data into columns. A map can fail to match or only partially extract fields. Map updates can change output column population across runs, affecting reproducibility. Common output columns often include the following, though exact columns depend on tool version and map matches.

| Column | Description |
|--------|-------------|
| **TimeCreated** | UTC timestamp of the event |
| **EventId** | Windows Event ID |
| **Level** | Event severity (Information, Warning, Error, Critical) |
| **Provider** | Event log provider name |
| **Channel** | Log channel (Security, System, Application, etc.) |
| **Computer** | Hostname that generated the event |
| **UserId** | SID of the user associated with the event |
| **MapDescription** | Human-readable description from the matching map |
| **UserName** | Resolved username (when mapped) |
| **RemoteHost** | Source IP/hostname (when mapped) |
| **PayloadData1-6** | Mapped event-specific data fields |
| **ExecutableInfo** | Process or executable details (when mapped) |
| **EventRecordId** | Record ID within the log |
| **RecordNumber** | Sequential record number |
| **ProcessId** | PID of the logging process |
| **ThreadId** | Thread ID of the logging process |
| **Keywords** | Event keyword flags |
| **SourceFile** | Path to the source .evtx file |
| **ChunkNumber** | Internal chunk number |
| **ExtraDataOffset** | Offset for extra data |
| **HiddenRecord** | Whether the record was hidden |
| **Timestamp** | Additional timestamp field |
| **Payload** | Raw XML payload of the event |

## Maps

Maps are the core feature that makes EvtxECmd powerful. They define how raw event XML data is extracted and placed into the normalized output columns. Maps are stored as YAML files in the `Maps` directory. Updating maps during an investigation can change field extraction and output consistency.

- `--sync` downloads the latest community maps from GitHub. Requires network access.
- Custom maps can be added to the `Maps` directory for proprietary or uncommon event sources.
- If an event has no matching map, the raw XML payload is still included in the output.

## Workflow Examples

### Parse a single log to CSV

```
EvtxECmd.exe -f "C:\Cases\Evidence\Security.evtx" --csv "C:\Cases\Output" --csvf Security_parsed.csv
```

### Parse a directory of logs

```
EvtxECmd.exe -d "C:\Cases\Evidence\Logs" --csv "C:\Cases\Output"
```

### Parse from a mounted forensic image with VSS

```
EvtxECmd.exe -d "E:\Windows\System32\winevt\Logs" --csv "C:\Cases\Output" --vss
```

### Filter by Event ID

```
EvtxECmd.exe -d "C:\Cases\Evidence\Logs" --csv "C:\Cases\Output" --inc 4624,4625
```

### Filter by date range

```
EvtxECmd.exe -d "C:\Cases\Evidence\Logs" --csv "C:\Cases\Output" --sd "2025-03-01 00:00:00" --ed "2025-03-07 23:59:59"
```

### Export to JSON with full payload

```
EvtxECmd.exe -f "C:\Cases\Evidence\System.evtx" --json "C:\Cases\Output" --fj
```
