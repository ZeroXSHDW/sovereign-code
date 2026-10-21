---
name: appcompatcacheparser
version: 1.0.0
description: Parse and extract Windows Application Compatibility Cache (ShimCache) from SYSTEM registry hive using Eric Zimmerman's AppCompatCacheParser. Covers CLI flags, CSV output, ControlSet selection, and output field reference.
metadata:
  tool-name: AppCompatCacheParser
  tool-vendor: Eric Zimmerman
---

# AppCompatCacheParser Skill

AppCompatCacheParser is Eric Zimmerman's command-line tool for parsing the Windows Application Compatibility Cache (ShimCache) from the SYSTEM registry hive. It extracts execution metadata including file paths, last modified timestamps, and execution flags. Forensic interpretation of ShimCache data (execution timeline analysis, program existence verification, etc.) belongs in a separate analysis skill.

## Command Syntax

```
AppCompatCacheParser.exe --csv <dir> [-f <file>] [other options]
```

Single-letter options use a single dash (`-`). Multi-character options use double dashes (`--`).

## Input

| Flag | Description |
|------|-------------|
| `-f` | Full path to SYSTEM hive file to process. If not specified, the live Registry is used. |

## Output Formats

| Flag | Description |
|------|-------------|
| `--csv` | Directory to write CSV output. Required. |
| `--csvf` | Custom filename for CSV output (overrides default) |

It's recommended to write results to a file. Forensic output can be very large and may consume the context window. CSV is the most common choice for analysis with Timeline Explorer or Excel.

## Options

| Flag | Description | Default |
|------|-------------|---------|
| `--c` | ControlSet to parse. Default extracts all control sets. | all |
| `-t` | Sort last modified timestamps in descending order | FALSE |
| `--dt` | Custom date/time format string | `yyyy-MM-dd HH:mm:ss` |
| `--nl` | Ignore transaction log files for dirty hives | FALSE |
| `--debug` | Show debug information | FALSE |
| `--trace` | Show trace information | FALSE |

## Common Output Fields (CSV)

Output columns depend on tool version.

| Column | Description |
|--------|-------------|
| **ControlSet** | ControlSet the entry was extracted from |
| **CacheEntryPosition** | Position of the entry in the cache (execution order indicator) |
| **Path** | Full path to the executable |
| **LastModifiedTimeUTC** | Last modified timestamp of the file (UTC) |
| **Executed** | Execution flag (when available; not reliable on all OS versions) |
| **Duplicate** | Whether this entry is a duplicate across control sets |
| **SourceFile** | Path to the source SYSTEM hive file |

## Workflow Examples

### Parse a SYSTEM hive to CSV

```
AppCompatCacheParser.exe -f "C:\Cases\Evidence\SYSTEM" --csv "C:\Cases\Output"
```

### Parse with custom output filename

```
AppCompatCacheParser.exe -f "C:\Cases\Evidence\SYSTEM" --csv "C:\Cases\Output" --csvf ShimCache_parsed.csv
```

### Parse a specific ControlSet

```
AppCompatCacheParser.exe -f "C:\Cases\Evidence\SYSTEM" --csv "C:\Cases\Output" --c 1
```

### Parse with descending timestamp sort

```
AppCompatCacheParser.exe -f "C:\Cases\Evidence\SYSTEM" --csv "C:\Cases\Output" -t
```

### Parse the live system Registry

```
AppCompatCacheParser.exe --csv "C:\Cases\Output"
```

### Parse dirty hive without transaction logs

```
AppCompatCacheParser.exe -f "C:\Cases\Evidence\SYSTEM" --csv "C:\Cases\Output" --nl
```
