---
name: rbcmd
version: 1.0.0
description: Parse and extract Windows Recycle Bin artifacts ($I files and INFO2) using Eric Zimmerman's RBCmd. Covers CLI flags, CSV output, and output field reference.
metadata:
  tool-name: RBCmd
  tool-vendor: Eric Zimmerman
---

# RBCmd Skill

RBCmd is Eric Zimmerman's command-line tool for parsing Windows Recycle Bin artifacts. It processes both modern `$I` files (Vista+) and legacy `INFO2` files (XP and earlier), extracting deleted file metadata including original paths, file sizes, and deletion timestamps. Forensic interpretation of Recycle Bin data (deleted file recovery workflows, anti-forensics detection, etc.) belongs in a separate analysis skill.

## Command Syntax

```
RBCmd.exe -f <file> [--csv <dir>] [other options]
RBCmd.exe -d <directory> ...
```

Single-letter options use a single dash (`-`). Multi-character options use double dashes (`--`).

## Input (one required)

| Flag | Description |
|------|-------------|
| `-f` | Single Recycle Bin file to process (`$I` file or `INFO2`) |
| `-d` | Directory to recursively process for Recycle Bin files |

## Output Formats

| Flag | Description |
|------|-------------|
| `--csv` | Directory to write CSV output |
| `--csvf` | Custom filename for CSV output (overrides default) |

It's recommended to specify at least one output format to write results to a file. Forensic output can be very large and may consume the context window. CSV is the most common choice for analysis with Timeline Explorer or Excel.

## Options

| Flag | Description | Default |
|------|-------------|---------|
| `-q` | Suppress per-file output; show only filename being processed | FALSE |
| `--dt` | Custom date/time format string | `yyyy-MM-dd HH:mm:ss` |
| `--debug` | Show debug information | FALSE |
| `--trace` | Show trace information | FALSE |

## Common Output Fields (CSV)

Output columns depend on tool version.

| Column | Description |
|--------|-------------|
| **FileSize** | Size of the deleted file in bytes |
| **FileName** | Original full path of the deleted file |
| **SourceName** | Name of the source Recycle Bin file (`$I` file or `INFO2`) |
| **DeletedOn** | Timestamp when the file was deleted (UTC) |
| **FileType** | Recycle Bin file format version |

## Workflow Examples

### Parse a single $I file to CSV

```
RBCmd.exe -f "C:\Cases\Evidence\$RECYCLE.BIN\S-1-5-21-...\$I3F0R2A.txt" --csv "C:\Cases\Output"
```

### Parse a Recycle Bin directory

```
RBCmd.exe -d "C:\Cases\Evidence\$RECYCLE.BIN" --csv "C:\Cases\Output"
```

### Parse with custom output filename

```
RBCmd.exe -d "C:\Cases\Evidence\$RECYCLE.BIN" --csv "C:\Cases\Output" --csvf RecycleBin_parsed.csv
```

### Quick parse (suppress per-file details)

```
RBCmd.exe -d "C:\Cases\Evidence\$RECYCLE.BIN" --csv "C:\Cases\Output" -q
```

### Parse from a mounted forensic image

```
RBCmd.exe -d "E:\$RECYCLE.BIN" --csv "C:\Cases\Output"
```
