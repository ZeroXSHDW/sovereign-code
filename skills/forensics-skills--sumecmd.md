---
name: sumecmd
version: 1.0.0
description: Parse and extract Windows User Access Logging (UAL) databases using Eric Zimmerman's SumECmd. Covers CLI flags, CSV output, and output field reference for client access, DNS, role access, and VM entries.
metadata:
  tool-name: SumECmd
  tool-vendor: Eric Zimmerman
---

# SumECmd Skill

SumECmd is Eric Zimmerman's command-line tool for parsing Windows User Access Logging (UAL) databases. It processes the SystemIdentity.mdb and chained .mdb files found under `C:\Windows\System32\LogFiles\SUM`, extracting client access records, DNS entries, role access history, and virtual machine information. Forensic interpretation of UAL data (lateral movement detection, service access profiling, etc.) belongs in a separate analysis skill.

## Command Syntax

```
SumECmd.exe -d <directory> --csv <dir> [other options]
```

Single-letter options use a single dash (`-`). Multi-character options use double dashes (`--`).

## Input

| Flag | Description |
|------|-------------|
| `-d` | Directory to process, looking for SystemIdentity.mdb, Current.mdb, and chained databases. Required. |

## Output Formats

| Flag | Description |
|------|-------------|
| `--csv` | Directory to write CSV output. Required. |

It's recommended to write results to a file. Forensic output can be very large and may consume the context window. SumECmd produces multiple CSV files per run (one per data type).

## Options

| Flag | Description | Default |
|------|-------------|---------|
| `--wd` | Generate CSV with day-level detail breakdowns | TRUE |
| `--dt` | Custom date/time format string | `yyyy-MM-dd HH:mm:ss` |
| `--debug` | Show debug information | FALSE |
| `--trace` | Show trace information | FALSE |

## Output Files

SumECmd produces multiple CSV files per run:

| File | Description |
|------|-------------|
| `*_Clients.csv` | Client access records (users/machines that accessed server roles) |
| `*_ClientDayDetails.csv` | Day-level access breakdowns (when `--wd` is enabled) |
| `*_Dns.csv` | DNS hostname/address resolution records |
| `*_RoleAccess.csv` | Server role first/last seen access times |
| `*_Vm.csv` | Virtual machine entries |
| `*_ChainedDbInfo.csv` | Chained database metadata |
| `*_RoleInfo.csv` | Role GUID to name mappings |
| `*_SystemIdentInfo.csv` | System identity and OS version |

## Common Output Fields — Clients (CSV)

Output columns depend on tool version.

| Column | Description |
|--------|-------------|
| **RoleGuid** | GUID of the server role accessed |
| **RoleDescription** | Resolved role name |
| **AuthenticatedUserName** | Username of the authenticated client |
| **TotalAccesses** | Total number of accesses |
| **InsertDate** | First access timestamp |
| **LastAccess** | Most recent access timestamp |
| **IpAddress** | Client IP address |
| **ClientName** | Client hostname |
| **TenantId** | Tenant identifier |
| **SourceFile** | Source .mdb file |

## Common Output Fields — DNS (CSV)

| Column | Description |
|--------|-------------|
| **HostName** | DNS hostname |
| **Address** | Resolved IP address |
| **LastSeen** | Last seen timestamp |
| **SourceFile** | Source .mdb file |

## Common Output Fields — RoleAccess (CSV)

| Column | Description |
|--------|-------------|
| **RoleGuid** | GUID of the server role |
| **RoleDescription** | Resolved role name |
| **FirstSeen** | First access timestamp |
| **LastSeen** | Last access timestamp |
| **SourceFile** | Source .mdb file |

## Common Output Fields — VM (CSV)

| Column | Description |
|--------|-------------|
| **VmGuid** | Virtual machine GUID |
| **CreationTime** | VM creation timestamp |
| **LastSeenActive** | Last seen active timestamp |
| **BiosGuid** | BIOS GUID |
| **SerialNumber** | VM serial number |
| **SourceFile** | Source .mdb file |

## Workflow Examples

### Parse UAL databases to CSV

```
SumECmd.exe -d "C:\Cases\Evidence\LogFiles\SUM" --csv "C:\Cases\Output"
```

### Parse without day-level details

```
SumECmd.exe -d "C:\Cases\Evidence\LogFiles\SUM" --csv "C:\Cases\Output" --wd false
```

### Parse from a mounted forensic image

```
SumECmd.exe -d "E:\Windows\System32\LogFiles\SUM" --csv "C:\Cases\Output"
```
