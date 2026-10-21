---
name: lecmd
version: 1.0.0
description: Parse and extract Windows shortcut (.lnk) files using Eric Zimmerman's LECmd. Covers CLI flags, output formats (CSV/JSON/XML/HTML), removable drive filtering, and output field reference.
metadata:
  tool-name: LECmd
  tool-vendor: Eric Zimmerman
---

# LECmd Skill

LECmd is Eric Zimmerman's command-line tool for parsing Windows shortcut (.lnk) files. It extracts target file metadata, timestamps, volume information, network paths, and embedded tracker data into structured output. Forensic interpretation of LNK data (user activity reconstruction, file access analysis, etc.) belongs in a separate analysis skill.

## Command Syntax

```
LECmd.exe -f <file> [--csv <dir> | --json <dir> | --xml <dir> | --html <dir>] [other options]
LECmd.exe -d <directory> ...
```

Single-letter options use a single dash (`-`). Multi-character options use double dashes (`--`).

## Input (one required)

| Flag | Description |
|------|-------------|
| `-f` | Single .lnk file to process |
| `-d` | Directory to recursively process for .lnk files |

## Output Formats

| Flag | Description |
|------|-------------|
| `--csv` | Directory to write CSV output |
| `--csvf` | Custom filename for CSV output (overrides default) |
| `--json` | Directory to write JSON output |
| `--xml` | Directory to write XML output |
| `--html` | Directory to write XHTML output |

It's recommended to specify at least one output format to write results to a file. Forensic output can be very large and may consume the context window. CSV is the most common choice for analysis with Timeline Explorer or Excel.

## Options

| Flag | Description | Default |
|------|-------------|---------|
| `-r` | Only process .lnk files pointing to removable drives | FALSE |
| `-q` | Suppress per-file output; show only filename being processed | FALSE |
| `--all` | Process all files in directory, not just files matching *.lnk | FALSE |
| `--nid` | Suppress Target ID list details from being displayed | FALSE |
| `--neb` | Suppress Extra blocks information from being displayed | FALSE |
| `--pretty` | Use human-readable layout for JSON export | FALSE |
| `--dt` | Custom date/time format string | `yyyy-MM-dd HH:mm:ss` |
| `--mp` | Display higher precision timestamps | FALSE |
| `--cp` | Code page for string parsing | 1252 |
| `--debug` | Show debug information | FALSE |
| `--trace` | Show trace information | FALSE |

## Common Output Fields (CSV)

Output columns depend on tool version.

| Column | Description |
|--------|-------------|
| **SourceFile** | Path to the source .lnk file |
| **SourceCreated** | .lnk file creation timestamp |
| **SourceModified** | .lnk file last modified timestamp |
| **SourceAccessed** | .lnk file last accessed timestamp |
| **TargetCreated** | Target file creation timestamp |
| **TargetModified** | Target file last modified timestamp |
| **TargetAccessed** | Target file last accessed timestamp |
| **FileSize** | Target file size in bytes |
| **RelativePath** | Relative path to the target |
| **WorkingDirectory** | Working directory for the target |
| **FileAttributes** | Target file attributes |
| **HeaderFlags** | LNK header flags |
| **DriveType** | Drive type (Fixed, Removable, Network, etc.) |
| **VolumeSerialNumber** | Volume serial number |
| **VolumeLabel** | Volume label |
| **LocalPath** | Full local path to the target |
| **NetworkPath** | UNC or network path to the target |
| **CommonPath** | Common path prefix |
| **Arguments** | Command-line arguments embedded in the shortcut |
| **TargetIDAbsolutePath** | Absolute path from TargetID |
| **TargetMFTEntryNumber** | MFT entry number of the target file |
| **TargetMFTSequenceNumber** | MFT sequence number of the target file |
| **MachineID** | Machine ID from tracker data |
| **MachineMACAddress** | MAC address from tracker data |
| **MACVendor** | Resolved MAC address vendor |
| **TrackerCreatedOn** | Tracker data creation timestamp |
| **ExtraBlocksPresent** | Extra data blocks present in the LNK |

## Workflow Examples

### Parse a single .lnk file to CSV

```
LECmd.exe -f "C:\Cases\Evidence\document.lnk" --csv "C:\Cases\Output"
```

### Parse a directory of .lnk files

```
LECmd.exe -d "C:\Cases\Evidence\Recent" --csv "C:\Cases\Output"
```

### Parse all files in a directory (not just *.lnk)

```
LECmd.exe -d "C:\Cases\Evidence\Recent" --csv "C:\Cases\Output" --all
```

### Parse only .lnk files pointing to removable drives

```
LECmd.exe -d "C:\Cases\Evidence\Recent" --csv "C:\Cases\Output" -r
```

### Parse with high precision timestamps

```
LECmd.exe -d "C:\Cases\Evidence\Recent" --csv "C:\Cases\Output" --mp
```

### Export to JSON with pretty formatting

```
LECmd.exe -d "C:\Cases\Evidence\Recent" --json "C:\Cases\Output" --pretty
```
