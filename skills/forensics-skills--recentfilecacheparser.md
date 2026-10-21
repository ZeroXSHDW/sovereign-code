---
name: recentfilecacheparser
version: 1.0.0
description: Parse and extract Windows RecentFileCache.bcf files using Eric Zimmerman's RecentFileCacheParser. Covers CLI flags, output formats (CSV/JSON), and output field reference.
metadata:
  tool-name: RecentFileCacheParser
  tool-vendor: Eric Zimmerman
---

# RecentFileCacheParser Skill

RecentFileCacheParser is Eric Zimmerman's command-line tool for parsing Windows RecentFileCache.bcf files. These files are found on Windows 7/Server 2008 R2 systems and record paths of recently executed programs, providing evidence of application execution. Forensic interpretation of RecentFileCache data (execution timeline analysis, etc.) belongs in a separate analysis skill.

## Command Syntax

```
RecentFileCacheParser.exe -f <file> [--csv <dir> | --json <dir>] [other options]
```

Single-letter options use a single dash (`-`). Multi-character options use double dashes (`--`).

## Input

| Flag | Description |
|------|-------------|
| `-f` | RecentFileCache.bcf file to process. Required. |

## Output Formats

| Flag | Description |
|------|-------------|
| `--csv` | Directory to write CSV output |
| `--csvf` | Custom filename for CSV output (overrides default) |
| `--json` | Directory to write JSON output |

It's recommended to specify at least one output format to write results to a file. Forensic output can be very large and may consume the context window. CSV is the most common choice for analysis with Timeline Explorer or Excel.

## Options

| Flag | Description | Default |
|------|-------------|---------|
| `-q` | Suppress per-file output; show only filename being processed | FALSE |
| `--pretty` | Use human-readable layout for JSON export | FALSE |

## Common Output Fields (CSV)

Output columns depend on tool version.

| Column | Description |
|--------|-------------|
| **SourceFile** | Path to the source RecentFileCache.bcf file |
| **SourceCreated** | .bcf file creation timestamp |
| **SourceModified** | .bcf file last modified timestamp |
| **SourceAccessed** | .bcf file last accessed timestamp |
| **Filename** | Full path of the recently executed file |

## Workflow Examples

### Parse RecentFileCache.bcf to CSV

```
RecentFileCacheParser.exe -f "C:\Cases\Evidence\RecentFileCache.bcf" --csv "C:\Cases\Output"
```

### Parse with custom output filename

```
RecentFileCacheParser.exe -f "C:\Cases\Evidence\RecentFileCache.bcf" --csv "C:\Cases\Output" --csvf RecentFileCache_parsed.csv
```

### Export to JSON with pretty formatting

```
RecentFileCacheParser.exe -f "C:\Cases\Evidence\RecentFileCache.bcf" --json "C:\Cases\Output" --pretty
```

### Parse from a mounted forensic image

```
RecentFileCacheParser.exe -f "E:\Windows\AppCompat\Programs\RecentFileCache.bcf" --csv "C:\Cases\Output"
```
