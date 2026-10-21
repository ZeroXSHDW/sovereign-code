---
name: sbecmd
version: 1.0.0
description: Parse and extract Windows ShellBags data from registry hives using Eric Zimmerman's SBECmd. Covers CLI flags, CSV output, deduplication, timezone support, and output field reference.
metadata:
  tool-name: SBECmd
  tool-vendor: Eric Zimmerman
---

# SBECmd Skill

SBECmd is Eric Zimmerman's command-line tool for parsing Windows ShellBags data from registry hives. It extracts folder access metadata from NTUSER.DAT and UsrClass.dat hives, including folder paths, timestamps, MFT references, and shell item types. Forensic interpretation of ShellBags data (folder access reconstruction, user activity analysis, etc.) belongs in a separate analysis skill.

## Command Syntax

```
SBECmd.exe -d <directory> --csv <dir> [other options]
SBECmd.exe -l --csv <dir> [other options]
```

Single-letter options use a single dash (`-`). Multi-character options use double dashes (`--`).

## Input (one required)

| Flag | Description |
|------|-------------|
| `-d` | Directory to search for registry hives |
| `-l` | Process the live system registry |

## Output Formats

| Flag | Description |
|------|-------------|
| `--csv` | Directory to write CSV output. Required. |

It's recommended to write results to a file. Forensic output can be very large and may consume the context window. SBECmd always outputs to CSV.

## Options

| Flag | Description | Default |
|------|-------------|---------|
| `--dedupe` | Deduplicate entries across all hives in `-d` directory | FALSE |
| `--dt` | Custom date/time format string | `yyyy-MM-dd HH:mm:ss` |
| `--tz` | Timezone for timestamp display (use `--tz list` for options) | UTC |
| `--nl` | Ignore transaction log files for dirty hives | FALSE |
| `--debug` | Show debug information | FALSE |
| `--trace` | Show trace information | FALSE |

## Common Output Fields (CSV)

Output columns depend on tool version. When `--dedupe` is used, output is written to `Deduplicated.csv`.

| Column | Description |
|--------|-------------|
| **BagPath** | Registry path to the ShellBag entry |
| **Slot** | Bag slot number |
| **NodeSlot** | Node slot number |
| **MRUPosition** | Most Recently Used position |
| **AbsolutePath** | Full reconstructed folder path |
| **ShellType** | Shell item type identifier |
| **Value** | Shell item value data |
| **ChildBags** | Number of child bag entries |
| **CreatedOn** | Target folder creation timestamp |
| **ModifiedOn** | Target folder last modified timestamp |
| **AccessedOn** | Target folder last accessed timestamp |
| **LastWriteTime** | Registry key last write timestamp |
| **MFTEntry** | MFT entry number of the target folder |
| **MFTSequenceNumber** | MFT sequence number of the target folder |
| **ExtensionBlockCount** | Number of extension blocks in the shell item |
| **FirstInteracted** | First interaction timestamp |
| **LastInteracted** | Last interaction timestamp |
| **Miscellaneous** | Additional shell item properties |

## Workflow Examples

### Parse a directory of hives to CSV

```
SBECmd.exe -d "C:\Cases\Evidence\Registry" --csv "C:\Cases\Output"
```

### Parse with deduplication

```
SBECmd.exe -d "C:\Cases\Evidence\Registry" --csv "C:\Cases\Output" --dedupe
```

### Parse with a specific timezone

```
SBECmd.exe -d "C:\Cases\Evidence\Registry" --csv "C:\Cases\Output" --tz "US Eastern Standard Time"
```

### Parse the live system registry

```
SBECmd.exe -l --csv "C:\Cases\Output"
```

### Parse dirty hives without transaction logs

```
SBECmd.exe -d "C:\Cases\Evidence\Registry" --csv "C:\Cases\Output" --nl
```
