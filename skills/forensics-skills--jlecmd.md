---
name: jlecmd
version: 1.0.0
description: Parse and extract Windows Jump List files (AutomaticDestinations and CustomDestinations) using Eric Zimmerman's JLECmd. Covers CLI flags, output formats (CSV/JSON/HTML), AppID mappings, and output field reference.
metadata:
  tool-name: JLECmd
  tool-vendor: Eric Zimmerman
---

# JLECmd Skill

JLECmd is Eric Zimmerman's command-line tool for parsing Windows Jump List files. It processes both AutomaticDestinations and CustomDestinations jump lists, extracting linked file metadata, timestamps, interaction counts, and embedded LNK data. Forensic interpretation of jump list data (user activity reconstruction, application usage analysis, etc.) belongs in a separate analysis skill.

## Command Syntax

```
JLECmd.exe -f <file> [--csv <dir> | --json <dir> | --html <dir>] [other options]
JLECmd.exe -d <directory> ...
```

Single-letter options use a single dash (`-`). Multi-character options use double dashes (`--`).

## Input (one required)

| Flag | Description |
|------|-------------|
| `-f` | Single jump list file to process |
| `-d` | Directory to recursively process for jump list files |

## Output Formats

| Flag | Description |
|------|-------------|
| `--csv` | Directory to write CSV output |
| `--csvf` | Custom filename for CSV output (overrides default) |
| `--json` | Directory to write JSON output |
| `--html` | Directory to write XHTML output |

It's recommended to specify at least one output format to write results to a file. Forensic output can be very large and may consume the context window. CSV is the most common choice for analysis with Timeline Explorer or Excel.

## Options

| Flag | Description | Default |
|------|-------------|---------|
| `--all` | Process all files in directory, not just jump list patterns | FALSE |
| `-q` | Suppress per-file output; show only filename being processed | FALSE |
| `--ld` | Include more information about linked files | FALSE |
| `--fd` | Include full information about linked files | FALSE |
| `--withDir` | Show directory contents not represented in DestList entries | FALSE |
| `--appIds` | Path to file with AppID mappings (format: `appid\|description`) | |
| `--dumpTo` | Directory to export embedded linked files to | |
| `--pretty` | Use human-readable layout for JSON export | FALSE |
| `--dt` | Custom date/time format string | `yyyy-MM-dd HH:mm:ss` |
| `--mp` | Display higher precision timestamps | FALSE |
| `--cp` | Code page for string parsing | 1252 |
| `--debug` | Show debug information | FALSE |
| `--trace` | Show trace information | FALSE |

## Common Output Fields — AutomaticDestinations (CSV)

JLECmd produces separate CSV files for AutomaticDestinations and CustomDestinations. Output columns depend on tool version.

| Column | Description |
|--------|-------------|
| **SourceFile** | Path to the source jump list file |
| **SourceCreated** | Jump list file creation timestamp |
| **SourceModified** | Jump list file last modified timestamp |
| **SourceAccessed** | Jump list file last accessed timestamp |
| **AppId** | Application identifier hash |
| **AppIdDescription** | Resolved application name (from AppID mappings) |
| **HasSps** | Whether the entry has stored property sets |
| **DestListVersion** | DestList stream version |
| **MRU** | Most Recently Used position |
| **LastUsedEntryNumber** | Last used entry number in DestList |
| **EntryNumber** | Entry number in DestList |
| **CreationTime** | DestList entry creation timestamp |
| **LastModified** | DestList entry last modified timestamp |
| **Hostname** | Hostname from DestList entry |
| **MacAddress** | MAC address from DestList entry |
| **Path** | Path from DestList entry |
| **PinStatus** | Whether the entry is pinned |
| **FileBirthDroid** | File birth distributed link tracking GUID |
| **FileDroid** | File distributed link tracking GUID |
| **VolumeBirthDroid** | Volume birth distributed link tracking GUID |
| **VolumeDroid** | Volume distributed link tracking GUID |
| **TargetCreated** | Target file creation timestamp |
| **TargetModified** | Target file last modified timestamp |
| **TargetAccessed** | Target file last accessed timestamp |
| **InteractionCount** | Number of times the target was opened |
| **CommonPath** | Common path prefix |
| **VolumeLabel** | Volume label |
| **VolumeSerialNumber** | Volume serial number |
| **DriveType** | Drive type (Fixed, Removable, Network, etc.) |
| **FileAttributes** | Target file attributes |
| **FileSize** | Target file size in bytes |
| **HeaderFlags** | LNK header flags |
| **LocalPath** | Full local path to the target |
| **RelativePath** | Relative path to the target |
| **Arguments** | Command-line arguments |
| **WorkingDirectory** | Working directory for the target |
| **ExtraBlocksPresent** | Extra data blocks present in the LNK |
| **TargetIDAbsolutePath** | Absolute path from TargetID |
| **TargetMFTEntryNumber** | MFT entry number of the target file |
| **TargetMFTSequenceNumber** | MFT sequence number of the target file |
| **MachineID** | Machine ID from tracker data |
| **MachineMACAddress** | MAC address from tracker data |
| **TrackerCreatedOn** | Tracker data creation timestamp |
| **Notes** | Additional notes or keyword matches |

## Common Output Fields — CustomDestinations (CSV)

| Column | Description |
|--------|-------------|
| **SourceFile** | Path to the source jump list file |
| **SourceCreated** | Jump list file creation timestamp |
| **SourceModified** | Jump list file last modified timestamp |
| **SourceAccessed** | Jump list file last accessed timestamp |
| **AppId** | Application identifier hash |
| **AppIdDescription** | Resolved application name (from AppID mappings) |
| **EntryName** | Name of the custom entry |
| **TargetIDAbsolutePath** | Absolute path from TargetID |
| **Arguments** | Command-line arguments |
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
| **CommonPath** | Common path prefix |
| **TargetMFTEntryNumber** | MFT entry number of the target file |
| **TargetMFTSequenceNumber** | MFT sequence number of the target file |
| **MachineID** | Machine ID from tracker data |
| **MachineMACAddress** | MAC address from tracker data |
| **TrackerCreatedOn** | Tracker data creation timestamp |
| **ExtraBlocksPresent** | Extra data blocks present in the LNK |

## Workflow Examples

### Parse a single jump list file to CSV

```
JLECmd.exe -f "C:\Cases\Evidence\5f7b5f1e01b83767.automaticDestinations-ms" --csv "C:\Cases\Output"
```

### Parse a directory of jump list files

```
JLECmd.exe -d "C:\Cases\Evidence\Recent\AutomaticDestinations" --csv "C:\Cases\Output"
```

### Parse with custom AppID mappings

```
JLECmd.exe -d "C:\Cases\Evidence\Recent" --csv "C:\Cases\Output" --appIds "C:\Tools\AppIDs.txt"
```

### Parse with full linked file details

```
JLECmd.exe -d "C:\Cases\Evidence\Recent" --csv "C:\Cases\Output" --fd
```

### Export embedded linked files

```
JLECmd.exe -d "C:\Cases\Evidence\Recent" --csv "C:\Cases\Output" --dumpTo "C:\Cases\Output\LinkedFiles"
```

### Parse with high precision timestamps

```
JLECmd.exe -d "C:\Cases\Evidence\Recent" --csv "C:\Cases\Output" --mp
```
