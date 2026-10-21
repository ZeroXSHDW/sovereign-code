---
name: srumecmd
version: 1.0.0
description: Parse and extract Windows SRUM (System Resource Usage Monitor) database using Eric Zimmerman's SrumECmd. Covers CLI flags, CSV output, and output field reference for application resource usage, network usage, network connections, energy usage, push notifications, and timeline data.
metadata:
  tool-name: SrumECmd
  tool-vendor: Eric Zimmerman
---

# SrumECmd Skill

SrumECmd is Eric Zimmerman's command-line tool for parsing the Windows SRUM database (SRUDB.dat). It extracts application resource usage, network data, energy usage, push notifications, and timeline data into structured CSV output. Providing the SOFTWARE hive alongside the SRUM database resolves application and user identifiers. Forensic interpretation of SRUM data (application usage profiling, network activity analysis, etc.) belongs in a separate analysis skill.

## Command Syntax

```
SrumECmd.exe -f <SRUDB.dat> --csv <dir> [-r <SOFTWARE hive>] [other options]
SrumECmd.exe -d <directory> --csv <dir> [other options]
```

Single-letter options use a single dash (`-`). Multi-character options use double dashes (`--`).

## Input

| Flag | Description |
|------|-------------|
| `-f` | SRUDB.dat file to process. Either this or `-d` is required. |
| `-r` | SOFTWARE hive to process. Optional but recommended — resolves application and user identifiers. |
| `-d` | Directory to recursively search for SRUDB.dat and SOFTWARE hive. Either this or `-f` is required. |

## Output Formats

| Flag | Description |
|------|-------------|
| `--csv` | Directory to write CSV output. Required. |

It's recommended to write results to a file. Forensic output can be very large and may consume the context window. SrumECmd produces multiple CSV files per run (one per SRUM table).

## Options

| Flag | Description | Default |
|------|-------------|---------|
| `--dt` | Custom date/time format string | `yyyy-MM-dd HH:mm:ss` |
| `--debug` | Show debug information | FALSE |
| `--trace` | Show trace information | FALSE |

## Output Files

SrumECmd produces multiple CSV files per run, one for each SRUM table found in the database:

| File | Description |
|------|-------------|
| `*_AppResourceUseInfo.csv` | Application CPU, I/O, and resource usage |
| `*_NetworkUsages.csv` | Network data transfer (bytes sent/received) |
| `*_NetworkConnections.csv` | Network connection durations and interface details |
| `*_EnergyUsage.csv` | Application energy consumption and battery state |
| `*_PushNotifications.csv` | Push notification metadata |
| `*_AppTimelineProvider.csv` | Application timeline activity |
| `*_vfuprov.csv` | VFU provider activity with durations |

## Common Output Fields — AppResourceUseInfo (CSV)

Output columns depend on tool version.

| Column | Description |
|--------|-------------|
| **Id** | Record identifier |
| **Timestamp** | SRUM entry timestamp (UTC) |
| **ExeInfo** | Executable path or application identifier |
| **ExeInfoDescription** | Resolved application description (from SOFTWARE hive) |
| **ExeTimestamp** | Executable timestamp |
| **SidType** | SID type |
| **Sid** | User SID |
| **UserName** | Resolved username (from SOFTWARE hive) |
| **UserId** | User identifier |
| **AppId** | Application identifier |
| **BackgroundBytesRead** | Bytes read in background |
| **BackgroundBytesWritten** | Bytes written in background |
| **BackgroundContextSwitches** | Context switches in background |
| **BackgroundCycleTime** | CPU cycle time in background |
| **BackgroundNumberOfFlushes** | Flush operations in background |
| **BackgroundNumReadOperations** | Read operations in background |
| **BackgroundNumWriteOperations** | Write operations in background |
| **FaceTime** | Foreground time |
| **ForegroundBytesRead** | Bytes read in foreground |
| **ForegroundBytesWritten** | Bytes written in foreground |
| **ForegroundContextSwitches** | Context switches in foreground |
| **ForegroundCycleTime** | CPU cycle time in foreground |
| **ForegroundNumberOfFlushes** | Flush operations in foreground |
| **ForegroundNumReadOperations** | Read operations in foreground |
| **ForegroundNumWriteOperations** | Write operations in foreground |

## Common Output Fields — NetworkUsages (CSV)

| Column | Description |
|--------|-------------|
| **Id** | Record identifier |
| **Timestamp** | SRUM entry timestamp (UTC) |
| **ExeInfo** | Executable path or application identifier |
| **ExeInfoDescription** | Resolved application description |
| **ExeTimestamp** | Executable timestamp |
| **SidType** | SID type |
| **Sid** | User SID |
| **UserName** | Resolved username |
| **UserId** | User identifier |
| **AppId** | Application identifier |
| **BytesReceived** | Bytes received |
| **BytesSent** | Bytes sent |
| **InterfaceLuid** | Network interface LUID |
| **InterfaceType** | Network interface type |
| **L2ProfileFlags** | Layer 2 profile flags |
| **L2ProfileId** | Layer 2 profile identifier |
| **ProfileName** | Network profile name |

## Common Output Fields — NetworkConnections (CSV)

| Column | Description |
|--------|-------------|
| **Id** | Record identifier |
| **Timestamp** | SRUM entry timestamp (UTC) |
| **ExeInfo** | Executable path or application identifier |
| **ExeInfoDescription** | Resolved application description |
| **ExeTimestamp** | Executable timestamp |
| **SidType** | SID type |
| **Sid** | User SID |
| **UserName** | Resolved username |
| **UserId** | User identifier |
| **AppId** | Application identifier |
| **ConnectedTime** | Total connected time |
| **ConnectStartTime** | Connection start timestamp |
| **InterfaceLuid** | Network interface LUID |
| **InterfaceType** | Network interface type |
| **L2ProfileFlags** | Layer 2 profile flags |
| **L2ProfileId** | Layer 2 profile identifier |
| **ProfileName** | Network profile name |

## Common Output Fields — EnergyUsage (CSV)

| Column | Description |
|--------|-------------|
| **Id** | Record identifier |
| **Timestamp** | SRUM entry timestamp (UTC) |
| **ExeInfo** | Executable path or application identifier |
| **ExeInfoDescription** | Resolved application description |
| **ExeTimestamp** | Executable timestamp |
| **SidType** | SID type |
| **Sid** | User SID |
| **UserName** | Resolved username |
| **UserId** | User identifier |
| **AppId** | Application identifier |
| **IsLt** | Is long-term energy data |
| **ConfigurationHash** | Configuration hash |
| **EventTimestamp** | Energy event timestamp |
| **StateTransition** | Power state transition |
| **ChargeLevel** | Battery charge level |
| **CycleCount** | Battery cycle count |
| **DesignedCapacity** | Battery designed capacity |
| **FullChargedCapacity** | Battery full charged capacity |
| **ActiveAcTime** | Active time on AC power |
| **ActiveDcTime** | Active time on DC (battery) power |
| **ActiveDischargeTime** | Active discharge time |
| **ActiveEnergy** | Active energy consumption |
| **CsAcTime** | Connected standby time on AC |
| **CsDcTime** | Connected standby time on DC |
| **CsDischargeTime** | Connected standby discharge time |
| **CsEnergy** | Connected standby energy consumption |

## Workflow Examples

### Parse SRUDB.dat with SOFTWARE hive

```
SrumECmd.exe -f "C:\Cases\Evidence\SRUDB.dat" -r "C:\Cases\Evidence\SOFTWARE" --csv "C:\Cases\Output"
```

### Parse SRUDB.dat without SOFTWARE hive

```
SrumECmd.exe -f "C:\Cases\Evidence\SRUDB.dat" --csv "C:\Cases\Output"
```

### Auto-discover SRUDB.dat and SOFTWARE in a directory

```
SrumECmd.exe -d "C:\Cases\Evidence" --csv "C:\Cases\Output"
```

### Parse from a mounted forensic image

```
SrumECmd.exe -d "E:\Windows" --csv "C:\Cases\Output"
```
