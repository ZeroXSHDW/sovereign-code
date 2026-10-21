---
name: amcacheparser
version: 1.0.0
description: Parse and extract Windows Amcache.hve registry hive using Eric Zimmerman's AmcacheParser. Covers CLI flags, output formats (CSV), SHA-1 filtering, and output field reference for file entries, program entries, device data, and driver information.
metadata:
  tool-name: AmcacheParser
  tool-vendor: Eric Zimmerman
---

# AmcacheParser Skill

AmcacheParser version 1.0.

AmcacheParser is Eric Zimmerman's command-line tool for parsing the Windows Amcache.hve registry hive. It extracts application execution metadata, installed program records, device information, and driver data into structured CSV output. Forensic interpretation of Amcache data (execution timeline analysis, software inventory correlation, etc.) belongs in a separate analysis skill.

## Command Syntax

```
AmcacheParser.exe -f <file> --csv <dir> [other options]
```

Single-letter options use a single dash (`-`). Multi-character options use double dashes (`--`).

## Input

| Flag | Description |
|------|-------------|
| `-f` | Amcache.hve file to process. Required. |

## Output Formats

| Flag | Description |
|------|-------------|
| `--csv` | Directory to write CSV output. Required. |
| `--csvf` | Custom filename for CSV output (overrides default) |

It's recommended to write results to a file. Forensic output can be very large and may consume the context window. AmcacheParser produces multiple CSV files per run (one per data type).

## Options

| Flag | Description | Default |
|------|-------------|---------|
| `-i` | Include file entries for Programs entries | FALSE |
| `-b` | Path to file containing SHA-1 hashes to include (whitelist) | |
| `-w` | Path to file containing SHA-1 hashes to exclude (blacklist) | |
| `--dt` | Custom date/time format string | `yyyy-MM-dd HH:mm:ss` |
| `--mp` | Display higher precision timestamps | FALSE |
| `--nl` | Ignore transaction log files for dirty hives | FALSE |
| `--debug` | Show debug information | FALSE |
| `--trace` | Show trace information | FALSE |

When both `-b` and `-w` are provided, blacklist filtering takes precedence.

## Output Files

AmcacheParser produces multiple CSV files per run, one for each data type found in the hive. The hive format (new vs. old) determines which files are generated.

### New Format Hives

| File | Description |
|------|-------------|
| `*_UnassociatedFileEntries.csv` | File entries not linked to a program |
| `*_AssociatedFileEntries.csv` | File entries linked to a program |
| `*_ProgramEntries.csv` | Installed program records |
| `*_ShortCuts.csv` | Shortcut entries |
| `*_DeviceContainers.csv` | Device container records |
| `*_DevicePnps.csv` | Plug and Play device records |
| `*_DriveBinaries.csv` | Driver binary records |
| `*_DriverPackages.csv` | Driver package records |

### Old Format Hives

| File | Description |
|------|-------------|
| `*_UnassociatedFileEntries.csv` | File entries not linked to a program |
| `*_AssociatedFileEntries.csv` | File entries linked to a program |
| `*_ProgramEntries.csv` | Installed program records |

## Common Output Fields — UnassociatedFileEntries / AssociatedFileEntries (CSV, New Format)

Output columns depend on tool version and hive format.

| Column | Description |
|--------|-------------|
| **ApplicationName** | Associated application name |
| **ProgramId** | Program identifier |
| **FileKeyLastWriteTimestamp** | Registry key last write timestamp |
| **SHA1** | SHA-1 hash of the file |
| **IsOsComponent** | Whether the file is an OS component |
| **FullPath** | Full path to the file |
| **Name** | Filename |
| **FileExtension** | File extension |
| **LinkDate** | PE linker timestamp |
| **ProductName** | Product name from version info |
| **Size** | File size |
| **Version** | File version |
| **ProductVersion** | Product version |
| **LongPathHash** | Hash of the long path |
| **BinaryType** | Binary type (32-bit, 64-bit, etc.) |
| **IsPeFile** | Whether the file is a PE executable |
| **BinFileVersion** | Binary file version |
| **BinProductVersion** | Binary product version |
| **Language** | Language code |

## Common Output Fields — ProgramEntries (CSV, New Format)

| Column | Description |
|--------|-------------|
| **ProgramId** | Program identifier |
| **KeyLastWriteTimestamp** | Registry key last write timestamp |
| **Name** | Program name |
| **Version** | Program version |
| **Publisher** | Publisher name |
| **InstallDate** | Installation date |
| **OSVersionAtInstallTime** | OS version when installed |
| **BundleManifestPath** | Bundle manifest path |
| **HiddenArp** | Hidden from Add/Remove Programs |
| **InboxModernApp** | Whether it is an inbox modern app |
| **Language** | Language code |
| **ManifestPath** | Manifest path |
| **MsiPackageCode** | MSI package code |
| **MsiProductCode** | MSI product code |
| **PackageFullName** | Full package name |
| **ProgramInstanceId** | Program instance identifier |
| **RegistryKeyPath** | Source registry key path |
| **RootDirPath** | Root directory path |
| **Type** | Entry type |
| **Source** | Entry source |
| **StoreAppType** | Store app type |
| **UninstallString** | Uninstall command |

## Common Output Fields — ShortCuts (CSV)

| Column | Description |
|--------|-------------|
| **KeyName** | Registry key name |
| **LnkName** | Shortcut name |
| **KeyLastWriteTimestamp** | Registry key last write timestamp |

## Common Output Fields — DriveBinaries (CSV)

| Column | Description |
|--------|-------------|
| **KeyName** | Registry key name |
| **KeyLastWriteTimestamp** | Registry key last write timestamp |
| **DriverTimeStamp** | Driver timestamp |
| **DriverLastWriteTime** | Driver last write time |
| **DriverName** | Driver name |
| **DriverInBox** | Whether the driver is inbox |
| **DriverIsKernelMode** | Whether the driver is kernel mode |
| **DriverSigned** | Whether the driver is signed |
| **DriverCheckSum** | Driver checksum |
| **DriverCompany** | Driver company |
| **DriverId** | Driver identifier |
| **DriverPackageStrongName** | Driver package strong name |
| **DriverType** | Driver type |
| **DriverVersion** | Driver version |
| **ImageSize** | Image size |
| **Inf** | INF file name |
| **Product** | Product name |
| **ProductVersion** | Product version |
| **Service** | Service name |
| **WdfVersion** | WDF version |

## Workflow Examples

### Parse Amcache to CSV

```
AmcacheParser.exe -f "C:\Cases\Evidence\Amcache.hve" --csv "C:\Cases\Output"
```

### Parse with custom output filename

```
AmcacheParser.exe -f "C:\Cases\Evidence\Amcache.hve" --csv "C:\Cases\Output" --csvf Amcache_parsed.csv
```

### Parse with included file entries for programs

```
AmcacheParser.exe -f "C:\Cases\Evidence\Amcache.hve" --csv "C:\Cases\Output" -i
```

### Filter by SHA-1 whitelist

```
AmcacheParser.exe -f "C:\Cases\Evidence\Amcache.hve" --csv "C:\Cases\Output" -b "C:\Cases\known_hashes.txt"
```

### Filter by SHA-1 blacklist

```
AmcacheParser.exe -f "C:\Cases\Evidence\Amcache.hve" --csv "C:\Cases\Output" -w "C:\Cases\exclude_hashes.txt"
```

### Parse dirty hive without transaction logs

```
AmcacheParser.exe -f "C:\Cases\Evidence\Amcache.hve" --csv "C:\Cases\Output" --nl
```
