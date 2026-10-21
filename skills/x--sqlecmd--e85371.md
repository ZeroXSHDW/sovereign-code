---
name: sqlecmd
version: 1.0.0
description: Parse and extract data from SQLite databases using Eric Zimmerman's SQLECmd. Covers CLI flags, map-driven extraction, output formats (CSV/JSON), blob export, and map structure reference.
metadata:
  tool-name: SQLECmd
  tool-vendor: Eric Zimmerman
---

# SQLECmd Skill

SQLECmd is Eric Zimmerman's command-line tool for parsing SQLite database files using map definitions. It identifies SQLite databases by file header, matches them to maps that define SQL queries and column mappings, and outputs structured CSV or JSON. Any SQLite database can be parsed as long as a map (.smap) exists for its schema. Forensic interpretation of SQLite data (browser history analysis, application activity reconstruction, etc.) belongs in a separate analysis skill.

## Command Syntax

```
SQLECmd.exe -f <file> --csv <dir> [other options]
SQLECmd.exe -d <directory> --csv <dir> [other options]
```

Single-letter options use a single dash (`-`). Multi-character options use double dashes (`--`).

## Input (one required)

| Flag | Description |
|------|-------------|
| `-f` | Single SQLite file to process |
| `-d` | Directory to process containing SQLite files |

## Output Formats

| Flag | Description |
|------|-------------|
| `--csv` | Directory to write CSV output |
| `--json` | Directory to write JSON output |

It's recommended to specify at least one output format to write results to a file. Forensic output can be very large and may consume the context window. CSV is the most common choice for analysis with Timeline Explorer or Excel.

## Options

| Flag | Description | Default |
|------|-------------|---------|
| `--hunt` | Examine all files regardless of name; identify SQLite files by header | FALSE |
| `--maps` | Path to map (.smap) files | `Maps` folder next to the executable |
| `--sync` | Download latest maps from GitHub before processing. Requires network access. | FALSE |
| `--dedupe` | Deduplicate files via SHA-1 | TRUE |
| `--blobdir` | Directory to save extracted blob data to | |
| `--noblob` | Disable blob extraction from query results | FALSE |
| `--debug` | Show debug information | FALSE |
| `--trace` | Show trace information | FALSE |

## Output Structure

SQLECmd produces one CSV file per map query that matches the input. Output filenames follow the pattern `<CSVPrefix>_<BaseFileName>.csv` as defined in each map.

Every output file includes a **SourceFile** column appended to the query results, identifying which SQLite database the row came from.

CSV column names are defined by each map's SQL query aliases, not by the tool itself. Different databases produce different columns depending on their map definitions.

## Maps

Maps (.smap files) are YAML definitions that tell SQLECmd how to identify and extract data from specific SQLite databases. Each map defines:

| Field | Description |
|-------|-------------|
| **Description** | Human-readable description of the database |
| **CSVPrefix** | Prefix for output CSV filenames |
| **FileName** | Expected database filename (used for matching) |
| **IdentifyQuery** | SQL query to confirm database identity |
| **IdentifyValue** | Expected result of the identify query |
| **Queries** | Array of SQL queries with column aliases defining CSV output |

Maps are stored in the `Maps` directory (default: next to the executable). The `--hunt` flag bypasses filename matching and identifies SQLite files by their file header, allowing maps to match databases with renamed or unexpected filenames.

Common map categories include browsers (Chrome, Firefox, Edge), messaging apps, Windows artifacts (Notifications, Activities/Timeline), and mobile databases.

## Workflow Examples

### Parse a single SQLite database to CSV

```
SQLECmd.exe -f "C:\Cases\Evidence\History" --csv "C:\Cases\Output"
```

### Parse a directory of SQLite databases

```
SQLECmd.exe -d "C:\Cases\Evidence\AppData" --csv "C:\Cases\Output"
```

### Hunt for all SQLite files in a directory

```
SQLECmd.exe -d "C:\Cases\Evidence" --csv "C:\Cases\Output" --hunt
```

### Parse with blob extraction to a directory

```
SQLECmd.exe -d "C:\Cases\Evidence\AppData" --csv "C:\Cases\Output" --blobdir "C:\Cases\Output\Blobs"
```

### Parse without blob extraction

```
SQLECmd.exe -d "C:\Cases\Evidence\AppData" --csv "C:\Cases\Output" --noblob
```

### Parse from a mounted forensic image

```
SQLECmd.exe -d "E:\Users" --csv "C:\Cases\Output" --hunt
```
