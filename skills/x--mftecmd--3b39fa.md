---
name: mftecmd
version: 1.0.0
description: Parse and extract NTFS artifacts ($MFT, $J USN Journal, $Boot, $SDS, $I30) using Eric Zimmerman's MFTECmd. Covers CLI flags, output formats (CSV/JSON/bodyfile), and output field reference.
metadata:
  tool-name: MFTECmd
  tool-vendor: Eric Zimmerman
---

# MFTECmd Skill

MFTECmd is Eric Zimmerman's command-line tool for parsing NTFS file system artifacts. It processes the Master File Table ($MFT), USN Journal ($J), boot sector ($Boot), security descriptors ($SDS), and directory indexes ($I30), producing structured output. Forensic interpretation of MFT data (timestomping analysis, deleted file recovery workflows, etc.) belongs in a separate analysis skill.

## Command Syntax

```
MFTECmd.exe -f <file> [--csv <dir> | --json <dir> | --body <dir>] [other options]
```

Single-letter options use a single dash (`-`). Multi-character options use double dashes (`--`).

## Input

| Flag | Description |
|------|-------------|
| `-f` | File to process (`$MFT`, `$J`, `$Boot`, `$SDS`, or `$I30`). Required. |
| `-m` | Path to `$MFT` file when `-f` points to `$J`. Resolves parent paths in USN Journal output. |

## Output Formats

| Flag | Description |
|------|-------------|
| `--csv` | Directory to write CSV output |
| `--csvf` | Custom filename for CSV output (overrides default) |
| `--json` | Directory to write JSON output |
| `--jsonf` | Custom filename for JSON output (overrides default) |
| `--body` | Directory to write bodyfile format output |
| `--bodyf` | Custom filename for bodyfile output (overrides default) |
| `--bdl` | Drive letter (e.g. `C`) for bodyfile. Required with `--body`. |

It's recommended to specify at least one output format to write results to a file. Forensic output can be very large and may consume the context window. CSV is the most common choice for analysis with Timeline Explorer or Excel.

## Options

| Flag | Description | Default |
|------|-------------|---------|
| `--dt` | Custom date/time format string | `yyyy-MM-dd HH:mm:ss.fffffff` |
| `--sn` | Include DOS (8.3) filename types in output | FALSE |
| `--fl` | Generate condensed file listing (requires `--csv`) | FALSE |
| `--at` | Include all 0x30 attribute timestamps, not just when they differ from 0x10 | FALSE |
| `--rs` | Recover slack space from FILE records | FALSE |
| `--ir` | Include resident data in JSON/CSV output | FALSE |
| `--re` | Extensions to include for resident data (e.g. `.txt,.ps1`) | all (when omitted) |
| `--rm` | Maximum resident data size in bytes | 1024 |
| `--blf` | Use LF instead of CRLF for newlines in output | FALSE |
| `--de` | Dump full details for a specific entry/sequence (e.g. `5` or `624-5`) | |
| `--dd` | Directory to export a raw $MFT FILE record to | |
| `--do` | Offset of $MFT FILE record to export (decimal or hex) | |
| `--dr` | Export resident files to a subdirectory | FALSE |
| `--fls` | Display directory contents from a $MFT entry | FALSE |
| `--ds` | Dump a specific Security ID from $SDS | |
| `--vss` | Process Volume Shadow Copies on the drive | FALSE |
| `--dedupe` | Deduplicate files via SHA-1 | FALSE |
| `--debug` | Show debug information | FALSE |
| `--trace` | Show trace information | FALSE |

## Common Output Fields — $MFT (CSV)

Output columns depend on tool version. Common columns when parsing $MFT:

| Column | Description |
|--------|-------------|
| **EntryNumber** | MFT entry number |
| **SequenceNumber** | Entry sequence number (increments on reuse) |
| **InUse** | Whether the MFT record is active or free |
| **ParentEntryNumber** | MFT entry number of the parent directory |
| **ParentSequenceNumber** | Sequence number of the parent directory |
| **ParentPath** | Full path to the parent directory |
| **FileName** | Name of the file or directory |
| **Extension** | File extension (empty for directories) |
| **FileSize** | File size in bytes |
| **ReferenceCount** | Number of unique parent MFT references |
| **ReparseTarget** | Target path for reparse points (symlinks, junctions) |
| **IsDirectory** | Whether the entry is a directory |
| **HasAds** | Whether the entry has alternate data streams |
| **IsAds** | Whether the entry itself is an alternate data stream |
| **Created0x10** | Created timestamp from Standard_Information attribute |
| **Created0x30** | Created timestamp from File_Name attribute |
| **LastModified0x10** | Last modified from Standard_Information |
| **LastModified0x30** | Last modified from File_Name |
| **LastRecordChange0x10** | MFT record change from Standard_Information |
| **LastRecordChange0x30** | MFT record change from File_Name |
| **LastAccess0x10** | Last access from Standard_Information |
| **LastAccess0x30** | Last access from File_Name |
| **UpdateSequenceNumber** | USN for this record |
| **LogfileSequenceNumber** | $LogFile sequence number |
| **SecurityId** | Security descriptor ID |
| **ObjectIdFileDroid** | Object ID GUID |
| **SiFlags** | Standard_Information attribute flags |
| **NameType** | Filename type (Win32, DOS, POSIX, Win32+DOS) |
| **SI<FN** | TRUE when a File_Name (0x30) timestamp is later than the corresponding Standard_Information (0x10) timestamp |
| **uSecZeros** | TRUE when a timestamp has subseconds zeroed out (`.0000000`) |
| **Copied** | TRUE when SI timestamps suggest the file was copied |
| **LoggedUtilStream** | Logged utility stream data |
| **ZoneIdContents** | Zone.Identifier ADS content (download origin) |

## Common Output Fields — $J USN Journal (CSV)

| Column | Description |
|--------|-------------|
| **UpdateTimestamp** | UTC timestamp of the journal entry |
| **EntryNumber** | MFT entry number of the affected file |
| **ParentEntryNumber** | MFT entry number of the parent directory |
| **ParentPath** | Full parent path (only populated when `-m` provides the $MFT) |
| **Name** | Filename |
| **UpdateReasons** | Pipe-separated list of change reasons (e.g. `FileCreate`, `DataExtend`, `RenameNewName`) |

## Workflow Examples

### Parse $MFT to CSV

```
MFTECmd.exe -f "C:\Cases\Evidence\$MFT" --csv "C:\Cases\Output" --csvf MFT_parsed.csv
```

### Parse $MFT with all timestamps

```
MFTECmd.exe -f "C:\Cases\Evidence\$MFT" --csv "C:\Cases\Output" --at
```

### Parse USN Journal with path resolution

```
MFTECmd.exe -f "C:\Cases\Evidence\$J" -m "C:\Cases\Evidence\$MFT" --csv "C:\Cases\Output"
```

### Parse USN Journal without $MFT (no parent paths)

```
MFTECmd.exe -f "C:\Cases\Evidence\$J" --csv "C:\Cases\Output"
```

### Generate bodyfile output

```
MFTECmd.exe -f "C:\Cases\Evidence\$MFT" --body "C:\Cases\Output" --bdl C
```

### Extract resident file data

```
MFTECmd.exe -f "C:\Cases\Evidence\$MFT" --csv "C:\Cases\Output" --ir --re ".txt,.ps1,.bat,.cmd"
```

### Parse $SDS

```
MFTECmd.exe -f "C:\Cases\Evidence\$SDS" --csv "C:\Cases\Output"
```

### Parse $I30 directory index

```
MFTECmd.exe -f "C:\Cases\Evidence\$I30" --csv "C:\Cases\Output"
```
