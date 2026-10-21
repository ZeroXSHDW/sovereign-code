---
name: tool-router
description: 执行环境路由器。判断应使用 Windows、WSL、Docker、VMware、QEMU 还是混合环境来执行取证工具，避免工具环境和路径混乱。
disable-model-invocation: false
---

# tool-router

## Purpose

tool-router 是执行环境路由器。根据任务类型和工具需求，选择最合适的执行环境（Windows、WSL、Docker、VMware、QEMU），避免环境冲突和路径混乱。

## Use When

- 需要执行取证工具但不确定在哪个环境
- 工具只在特定环境可用（如 binwalk 在 WSL，Autopsy 在 Windows）
- 需要隔离执行环境（如恶意样本分析在 VM）

## Inputs

| Input | Required | Description |
|-------|----------|-------------|
| `task_type` | Yes | 任务类型（文件分析、固件解包、内存分析、网络分析等） |
| `tools_needed` | Recommended | 需要的工具列表 |
| `material_path` | Recommended | 检材路径（影响路径转换） |
| `execution_policy` | Recommended | 当前案件的工具策略；VMware 可指定 `mcp-only` |

## Outputs

| Output | Description |
|--------|-------------|
| `environment` | 选定的执行环境 |
| `path_mapping` | 路径转换规则（Windows ↔ WSL） |
| `tool_commands` | 在目标环境中执行的命令 |
| `tool_capability_report` | 环境、实际加载实现、逐项能力和允许写入根目录的预检结果 |

## Workflow

### Step 1: Assess Tool Requirements

根据 task_type 和 tools_needed 判断工具的环境需求：

| Tool Category | Preferred Environment | Fallback |
|---------------|----------------------|----------|
| file, strings, xxd, binwalk | WSL | Windows (Git Bash) |
| 7z, exiftool | Windows | WSL |
| Autopsy, FTK Imager | Windows | — |
| Volatility | WSL/Python | Windows |
| tshark, Wireshark | Windows | WSL |
| docker, docker-compose | Docker | — |
| qemu-system, qemu-img | QEMU | VMware |
| vmrun, vmware | VMware | QEMU |
| Python scripts | WSL/Python | Windows Python |

**Evidence**: 记录工具环境需求

### Step 2: Determine Environment

选择单一环境或混合环境：
- 单一环境：所有工具在同一环境运行
- 混合环境：部分工具在 WSL，部分在 Windows，通过路径映射协作

**Evidence**: 记录环境选择决策

#### VMware Layered Preflight

选择 VMware 时必须分层识别并分别留证，不能把“Workstation 已安装”或“MCP 已注册”写成整体可用：

1. VMware Workstation 本体及版本；
2. 已注册的 VMware MCP 及健康状态；
3. MCP 包装层实际加载的模块路径与版本或 Hash；
4. MCP 暴露的具体能力及逐项实际预检结果；
5. 嵌套虚拟化的实际状态；
6. 当前案件允许写入的工作目录。

VMware 专项结果写入现有 `tool_capability_report`，至少包含：

```yaml
vmware:
  workstation:
    available: true|false|unknown
    version: string|null
  mcp_registered: true|false
  health_status: healthy|degraded|unhealthy|unknown
  loaded_module_path: string|null
  loaded_version_or_hash: string|null
  capabilities:
    create_vm: available|unavailable|blocked|unknown
    config_set: available|unavailable|blocked|unknown
    disk_attach: available|unavailable|blocked|unknown
    network_config: available|unavailable|blocked|unknown
    power_control: available|unavailable|blocked|unknown
    screenshot: available|unavailable|blocked|unknown
    console_input: available|unavailable|blocked|unknown
  nested_virtualization_status: available|unavailable|blocked|unknown
  allowed_write_roots: []
  tooling_defect_refs: []  # 仅保存正式 tooling_defect Finding ID
```

普通案件运行中的预检只允许非状态变更的健康检查、能力发现和参数契约验证；MCP 注册信息本身不算能力证据。参数契约错误、旧进程未重载，或源码路径/版本与 `loaded_module_path`、`loaded_version_or_hash` 不一致时，生成带命令输出或日志引用的 `tooling_defect` Finding，将其 `finding_id` 写入 `tooling_defect_refs`，并将受影响能力标为 `blocked`。该数组不得内嵌第二套缺陷对象。

`create_vm`、`config_set`、`disk_attach`、`network_config`、`power_control`、`console_input` 等会改变状态的烟雾测试，只允许在以下环境执行：

- 与案件取证分离的独立工具维护测试；或
- Executor 已批准、位于 `execution_scope` 且具有有效 rollback checkpoint 的可回滚测试环境。

tool-router 只能读取这些测试产生的命令输出、日志或 Artifact 来判断能力，不得为了证明能力在案件运行中创建 VM、附加磁盘、修改配置/网络或控制电源。

当 `execution_policy: mcp-only`：

- 所有 VMware 控制只能经已注册且健康的 VMware MCP；禁止生成或建议绕过 MCP 的 `vmrun`、`vmrest` 或其他本地 VMware 控制命令。
- 任一必需能力未实际通过预检，或存在相关 `tooling_defect`，都必须阻断依赖该能力的执行 Stage 并返回规划层。
- 工具维护和案件执行分离；不得在正式取证运行中修改 MCP 源码、重载旧进程后原地继续重建。

### Step 3: Set Up Path Mapping

如使用混合环境，建立路径映射：
- Windows → WSL: `E:\` → `/mnt/e/`
- WSL → Windows: `/mnt/e/` → `E:\`

**Evidence**: 记录路径映射规则

### Step 4: Generate Commands

为目标环境生成可执行的命令序列。

命令序列仅表达经预检可用的环境入口。tool-router 不创建 VM、不附加磁盘、不配置网络、不启动实例；这些动作由已批准计划的 executor 执行。

## Evidence Requirements

| Field | When to Record |
|-------|---------------|
| `artifact` | 待分析的检材 |
| `command` | 环境检测命令、工具调用命令 |
| `finding` | 环境选择结果 |
| `confidence` | 环境判断置信度 |

VMware 预检还必须把 `loaded_module_path`、`loaded_version_or_hash`、逐项能力状态、`nested_virtualization_status`、`allowed_write_roots` 和任何 `tooling_defect` 绑定到对应命令输出、日志或配置 Artifact。

## Handoff

**Passes to**: forensic-autopilot（传递环境决策）
**Data available**: 环境、路径映射、命令模板、`tool_capability_report`（含 VMware MCP 逐项能力、tooling defects 与 allowed write roots）

## Stop Conditions

- 所需工具在所有环境都不可用
- 环境配置损坏或无法启动
- 路径映射冲突
- `mcp-only` 所需的 VMware MCP 未注册、不健康、实际加载实现不一致或必需能力预检失败

## Notes

- tool-router 只做环境选择，不执行分析
- tool-router 只判断 VMware MCP 能力和执行环境，不直接执行重建或维护 MCP 代码
- 原始检材应保留；任何状态变更操作应隔离到工作副本、重建环境或显式记录的会话中
- VM 环境用于隔离分析（恶意样本、不可信代码）
