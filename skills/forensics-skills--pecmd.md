---
name: pecmd
version: 1.0.0
description: Parse and extract Windows Prefetch (.pf) files using Eric Zimmerman's PECmd. Covers CLI flags, output formats (CSV/JSON/HTML), keyword highlighting, and output field reference.
metadata:
  tool-name: PECmd
  tool-vendor: Eric Zimmerman
---

# PECmd Skill

PECmd is Eric Zimmerman's command-line tool for parsing Windows Prefetch (.pf) files. It extracts execution metadata including run counts, timestamps, loaded files, and volume information from individual prefetch files or directories. Forensic interpretation of prefetch data (execution analysis, program usage timelines, etc.) belongs in a separate analysis skill.

## Command Syntax

```
PECmd.exe -f <file> [--csv <dir> | --json <dir> | --html <dir>] [other options]
PECmd.exe -d <directory> ...
```

Single-letter options use a single dash (`-`). Multi-character options use double dashes (`--`).

## Input (one required)

| Flag | Description |
|------|-------------|
| `-f` | Single .pf file to process |
| `-d` | Directory to recursively process for .pf files |

## Output Formats

| Flag | Description |
|------|-------------|
| `--csv` | Directory to write CSV output |
| `--csvf` | Custom filename for CSV output (overrides default) |
| `--json` | Directory to write JSON output |
| `--jsonf` | Custom filename for JSON output (overrides default) |
| `--html` | Directory to write XHTML output |

It's recommended to specify at least one output format to write results to a file. Forensic output can be very large and may consume the context window. CSV is the most common choice for analysis with Timeline Explorer or Excel.

## Options

| Flag | Description | Default |
|------|-------------|---------|
| `-k` | Comma-separated keywords to highlight in output. Adds to built-in defaults `temp` and `tmp`. | |
| `-o` | Path to save decompressed prefetch file bytes | |
| `-q` | Suppress full details per file; speeds up JSON/CSV operations | FALSE |
| `--dt` | Custom date/time format string | `yyyy-MM-dd HH:mm:ss` |
| `--mp` | Display higher precision timestamps | FALSE |
| `--vss` | Process Volume Shadow Copies on the drive | FALSE |
| `--dedupe` | Deduplicate files via SHA-1 | FALSE |
| `--debug` | Show debug information | FALSE |
| `--trace` | Show trace information | FALSE |

## Common Output Fields (CSV)

PECmd produces two CSV files: a main output and a timeline file.

### Main Output

| Column | Description |
|--------|-------------|
| **Note** | Keyword matches or other notes |
| **SourceFilename** | Path to the source .pf file |
| **SourceCreated** | .pf file creation timestamp |
| **SourceModified** | .pf file last modified timestamp |
| **SourceAccessed** | .pf file last accessed timestamp |
| **ExecutableName** | Name of the executable |
| **Hash** | Prefetch hash |
| **Size** | Prefetch file size |
| **Version** | Prefetch file format version (XP through Windows 10+) |
| **RunCount** | Number of times the executable was run |
| **LastRun** | Most recent execution timestamp |
| **PreviousRun0–6** | Up to 7 prior execution timestamps (Windows 8+ only) |
| **Volume0Name** | Volume device path for first volume |
| **Volume0Serial** | Volume serial number for first volume |
| **Volume0Created** | Volume creation timestamp for first volume |
| **Volume1Name** | Volume device path for second volume (if present) |
| **Volume1Serial** | Volume serial number for second volume (if present) |
| **Volume1Created** | Volume creation timestamp for second volume (if present) |
| **Directories** | Directories referenced by the executable |
| **FilesLoaded** | Files and DLLs loaded during execution |
| **ParsingError** | Error details if parsing failed |

### Timeline Output

A separate `_Timeline.csv` file with one row per execution timestamp:

| Column | Description |
|--------|-------------|
| **RunTime** | Execution timestamp |
| **ExecutableName** | Name of the executable |

## Workflow Examples

### Parse a single prefetch file to CSV

```
PECmd.exe -f "C:\Cases\Evidence\NOTEPAD.EXE-D4A77E42.pf" --csv "C:\Cases\Output"
```

### Parse a directory of prefetch files

```
PECmd.exe -d "C:\Cases\Evidence\Prefetch" --csv "C:\Cases\Output"
```

### Parse with keyword highlighting

```
PECmd.exe -d "C:\Cases\Evidence\Prefetch" --csv "C:\Cases\Output" -k "powershell,cmd,wscript"
```

### Parse with high precision timestamps

```
PECmd.exe -d "C:\Cases\Evidence\Prefetch" --csv "C:\Cases\Output" --mp
```

### Parse from a mounted forensic image with VSS

```
PECmd.exe -d "E:\Windows\Prefetch" --csv "C:\Cases\Output" --vss
```

### Quick parse (suppress per-file details)

```
PECmd.exe -d "C:\Cases\Evidence\Prefetch" --csv "C:\Cases\Output" -q
```
