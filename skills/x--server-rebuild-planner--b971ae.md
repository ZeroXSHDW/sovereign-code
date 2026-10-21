---
name: server-rebuild-planner
description: 服务器重建规划中枢。判断重建可行性，选择后端（VMware/QEMU/VirtualBox/Docker/WSL/manual），规划网络、凭据、资源和恢复策略，输出完整 rebuild plan 交给 executor 执行。
---

# server-rebuild-planner

## Purpose

server-rebuild-planner 是服务器重建的规划层。接收 `server-forensics-router` 的 `rebuild-and-connect`，或已由 `cluster-virtualization-forensics` 完成映射的 `hybrid-cluster` 路由决策，评估重建可行性，选择最佳后端，并输出包含资源需求、网络策略、凭据方案和恢复策略的完整 rebuild plan。

**planner 只负责规划，不执行任何操作。** 执行由 `server-rebuild-executor` 的 Stage 0-6 负责。

## Use When

- `server-forensics-router` 决定 `rebuild-and-connect` 模式
- `server-forensics-router` 决定 `hybrid-cluster`，且 `cluster-virtualization-forensics` 已完成 PVE/Ceph 拓扑和磁盘映射
- 检材包含可重建的服务器镜像（E01/VHD/VMDK/qcow2/raw）
- 检材包含可运行的 Docker compose 项目
- 检材包含完整的服务源码和数据库配置
- 需要将离线检材启动为运行态进行分析

## Do Not Use When

- 模式为 `remote-live`：直接连接，无需重建
- 模式为 `offline-image`：只读分析，不启动
- 模式为 `hybrid-cluster` 且 `cluster-virtualization-forensics` 尚未完成存储层映射
- 检材为纯日志、纯备份文件且无可重建的服务
- planner 不执行镜像导出、磁盘转换、VM 创建、网络配置、启动、连接测试

## Request Contract

遵循 `templates/request-envelope.schema.json`。

```yaml
schema_version: "1.0"
request:
  material_info:
    artifact_refs: array
    material_type: string
    triage_notes: array
    size_summary: object|null
  objective: string|null
  objective_status: explicit|inferred|unknown
  context: object|null
  payload:
    mode_decision: rebuild-and-connect|hybrid-cluster
    tool_capability_report: object|null  # 可选，前置 tool-router 的能力报告
    cluster_mapping: object|null         # hybrid-cluster 时引用前置 cluster 分析结果
    target_bindings: array               # 原样接收 router payload.target_bindings
```

## Response Contract

遵循 `templates/response-envelope.schema.json`。

**route_status 和 route_plan 随 feasibility 变化**。仅 `feasibility: yes` 或可降级的 `partial` 时才生成 executor handoff。

```yaml
schema_version: "1.0"
investigation_summary:
  current_assessment: string
  key_evidence: array
  excluded_routes: array
route_record:
  schema_version: "1.0"
  route_id: "route-<uuid>"
  triggered_skill: "server-rebuild-planner"
  route_basis: array
  mode_decision: rebuild-and-connect|hybrid-cluster
  route_status: active|blocked          # feasibility=blocked 时 route_status=blocked
  route_plan:
    - route_step_id: "step-<uuid>"
      skill: string
      dependency_step_ids: []
      parallel_group: null
      status: pending
  handoffs: []                          # 仅 feasibility=yes 或可降级 partial 时包含
  evidence_scope: string
  risk_level: low|medium|high
  next_action: string|null
  execution_gate:
    required: false
    reason: null
    policy_ref: null
  routing_policy:
    max_hops: 16
findings: array
ledger_events: array
artifact_refs: array
payload:
  target_bindings: array
  plan_id: "plan-<uuid>"
  plan_status: draft|ready|blocked|rejected
  rebuild_feasibility: yes|no|partial|blocked
  selected_backend: vmware|qemu|virtualbox|docker|wsl|manual|null
  backend_selection_status: confirmed|provisional|unavailable
  backend_candidates: array
  selection_basis: array
  backend_profile: object
  required_inputs: array
  missing_inputs: array
  prepared_artifact_requirements: array
  resource_requirements:
    cpu: integer
    ram_mb: integer
    disk_mb: integer
    nested_virtualization: boolean|null
    storage_budget:
      source_image_logical_bytes: integer|null
      export_logical_bytes: integer|null
      estimated_sparse_allocated_bytes: integer|null
      actual_sparse_allocated_bytes: integer|null
      estimated_peak_bytes: integer|null
      target_write_root: string|null
      target_free_bytes: integer|null
      write_root_allowed: boolean
  network_mode: host-only|nat|isolated|bridge|backend-default|none
  port_mapping: object|null
  credential_source: string|null
  credential_reference: string|null
  authentication_method: string|null
  modification_plan: string
  rollback_plan: string
  recovery_policy: object       # 符合 recovery-policy.schema.json
  execution_scope:
    approved_stages: array        # 已批准的 Stage 编号
    approved_operations: array    # 已批准的操作列表
    approved_backend: string|null
    approved_network_modes: array
    source_modification_allowed: false
    fallback_backends: array
  executor_handoff: object|null   # 非空时包含 plan_id, route_id, artifact_refs, target_bindings, backend, backend_selection_status, recovery_policy, execution_scope
  cluster_rebuild_profile: object|null
```

hybrid-cluster 的 `cluster_rebuild_profile` 使用专项 payload，不扩展 Route Step 或共享 Schema，至少包含：

```yaml
required_nodes: []
required_system_disks: []
required_osd_disks: []
management_network: object
storage_network: object
expected_monitors: []
expected_osds: []
expected_pools: []
workload_volume_map: []
recovery_gates:
  - outer_nodes_launched
  - node_networks_ready
  - management_services_ready
  - corosync_ready
  - ceph_ready
  - workload_storage_ready
  - guest_access_ready
workload_access_strategy:
  selected_strategy: nested-launch|rbd-offline-mount|rbd-separate-vmware|bounded-tcg|null
  candidate_strategies: []
  fallback_order: []
  readiness: ready|pending|blocked
  blocker_refs: []
```

`candidate_strategies` 与 `fallback_order` 至少支持 `nested-launch`、`rbd-offline-mount`、`rbd-separate-vmware`、`bounded-tcg`；只列入当前证据和 execution scope 允许的候选。所有 cluster profile 字段必须引用前置 cluster Finding、Artifact 和 Ledger Event；未知值进入 `missing_inputs` 或 `blocker_refs`，不得用猜测补齐。

`workload_access_strategy.readiness` 只表示计划是否具备交给 Executor 执行的条件：所需输入、空间预算、后端能力、scope 和 fallback 已明确。`readiness: ready` 不表示 Ceph、目标 RBD、Guest 文件系统或 Guest 服务已经成功访问；这些运行事实只能由 Executor 的 Stage 5 门禁和直接证据证明。

## Workflow

### Step 1: Intake and Feasibility Assessment

接收前置步骤的材料信息，判断重建可行性：

| 条件 | 可行性 |
|------|--------|
| 镜像完整、格式可转换、本地有对应后端 | `yes` |
| 镜像存在但缺少某些组件（如网络配置、部分磁盘） | `partial` |
| 镜像损坏、缺少关键组件或启动会污染证据 | `no` |
| 缺少必要信息无法判断 | `blocked` |

分配 `plan_id`，按以下规则设置 `plan_status`：

| Feasibility | plan_status | executor_handoff |
|------------|-------------|-----------------|
| `yes` | `ready` | 非空 |
| `partial` 且可降级 | `ready` | 非空 |
| `partial` 且关键输入缺失 | `blocked` | null |
| `no` | `rejected` | null |
| `blocked` | `blocked` | null |

`draft` 仅用于规划尚未完成时。

**Ledger Event**: 产生 `finding` event（`rebuild_feasibility`, confidence: medium）。

### Step 2: Select Backend

根据检材特征、可用性报告和建议选择后端。

| 检材特征 | 推荐 backend | 条件 |
|---------|-------------|------|
| 原生 VMDK/VMX 或已转换兼容磁盘 | `vmware` | VMware Workstation 可用 |
| qcow2/raw 镜像；也可处理 VHD/VMDK | `qemu` | qemu-img（格式操作）、qemu-system（运行）可用 |
| VDI/VHD/VMDK 或转换后的兼容磁盘 | `virtualbox` | VirtualBox 可用 |
| compose 项目 / Dockerfile / image archive | `docker` | Docker daemon 可用 |
| rootfs/distro 或适合 WSL 复现的 Linux 应用 | `wsl` | WSL 可用；不用于任意完整服务器镜像 |
| 特殊格式或需要 GUI/取证工具 | `manual` | 需要手动操作 |

- `tool_capability_report` 存在时，`backend_selection_status` 仅在以下条件全部满足时才为 `confirmed`：
  - 报告属于当前执行环境；
  - 报告未过期；
  - 明确包含目标 backend；
  - 对应运行程序状态为 `available`；
  - 所需格式工具状态为 `available`；
  - 所有 `required capabilities` 都有明确 `available` 结果。
- 上述任一条件不满足时保持 `provisional`，由 Executor Stage 0 重新调用 `tool-router` 验证。
- 所有候选后端不可用时，`selected_backend` 为 `null`，`backend_selection_status` 为 `unavailable`。

#### PVE/Ceph Backend Rules

- VMware MCP 的 `health_status` 为 healthy，实际加载路径/版本可追溯，且 `create_vm`、`config_set`、`disk_attach`、`network_config`、`power_control` 及计划所需交互能力逐项为 available 时，PVE 多节点优先选择 `vmware`。
- 案件策略为 `mcp-only` 时，在 `backend_profile` 记录该控制策略；Planner 不把 `vmrun`、`vmrest` 或本地 VMware 命令列为候选或 fallback。
- WSL2 QEMU/TCG 不得作为 PVE 多节点默认后端。TCG 仅可作为 `max_attempts: 1`、`max_wait_seconds: 300` 的有界降级候选，并且必须同时进入 `execution_scope`。
- 嵌套虚拟化不可用时，按证据和资源依次比较：RBD 导出后离线挂载、RBD 导出后在独立 VMware VM 启动、有界 TCG 尝试；不得直接把 Guest 启动失败等同于集群恢复失败。
- VMware MCP 不健康、能力不完整或存在 `tooling_defect` 时，不得 confirmed；受影响计划保持 blocked/provisional，并等待 Executor 预检或重新规划。

生成 `backend_profile`：记录该 backend 需要的特定参数。

**Ledger Event**: 产生 `finding` event（`selected_backend`, `backend_selection_status`, confidence: medium）。

### Step 3: Plan Resources

根据检材大小和复杂度估算资源：

```yaml
resource_requirements:
  cpu: integer               # 建议 CPU 核心数
  ram_mb: integer            # 建议内存 (MB)
  disk_mb: integer           # 预估工作磁盘用量
  nested_virtualization: boolean|null  # 是否需要嵌套虚拟化
  storage_budget:
    source_image_logical_bytes: integer|null
    export_logical_bytes: integer|null
    estimated_sparse_allocated_bytes: integer|null
    actual_sparse_allocated_bytes: integer|null
    estimated_peak_bytes: integer|null
    target_write_root: string|null
    target_free_bytes: integer|null
    write_root_allowed: boolean
```

资源预算是写入前硬门禁：

- Planner 分别记录源镜像逻辑大小、预计导出逻辑大小、`estimated_sparse_allocated_bytes` 和包含中间产物的峰值空间；plan 中的 `actual_sparse_allocated_bytes` 在规划阶段保持 null。Executor 创建产物后把文件系统直接结果写入执行该写入操作的现有 Stage `outputs.storage_budget.actual_sparse_allocated_bytes`；`rbd-offline-mount` 的 RBD 导出实际占用属于 Stage 5，不得回写不可变 plan。不得只用 flat 磁盘的巨大逻辑容量直接触发写入。
- `target_write_root` 必须属于 VMware 报告中的 `tool_capability_report.vmware.allowed_write_roots`（其他后端使用其对应 capability report 字段），并在写入前验证实际可用空间。
- 任一必需估算值未知、`write_root_allowed: false` 或 `target_free_bytes < estimated_peak_bytes` 时，相关计划为 blocked，不生成可执行 handoff；Planner 不因 `actual_sparse_allocated_bytes: null` 阻断。
- 禁止把空间不足临时规避为写入 C 盘或其他未批准根目录。

**Ledger Event**: 产生 `finding` event。

### Step 4: Plan Network

选择网络模式并规划端口映射：

| network_mode | 说明 | 适用场景 |
|-------------|------|---------|
| `host-only` | 仅宿主机访问 | 默认推荐，不暴露外网 |
| `nat` | NAT 网络 | 需要受限外网访问 |
| `isolated` | 完全隔离 | 恶意样本分析 |
| `bridge` | 桥接网络 | 只有 `execution_scope.approved_network_modes` 明确允许时执行 |
| `backend-default` | 使用后端默认 | 由 executor 决定 |
| `none` | 无网络 | 离线分析 |

**Ledger Event**: 产生 `finding` event。

#### PVE/Ceph Multi-node Plan

当 `cluster_rebuild_profile` 非空时，计划必须按以下依赖顺序生成；前一门未满足，后一项不得进入可执行状态：

1. 遍历 `required_nodes` 数组，准备其中每个 PVE 节点及映射给该节点的全部 `required_system_disks`、`required_osd_disks`；
2. 启动 `required_nodes` 中的全部外层 PVE 节点；
3. 验证每台节点的网卡映射；
4. 分别验证 `management_network` 和 `storage_network`；
5. 验证每台节点的 SSH 与 PVE WebUI 8006；
6. 以直接输出验证 Corosync quorum；
7. 验证预期 Ceph MON、MGR 和 OSD；
8. 验证 `expected_pools`、RBD 与 `workload_volume_map`；
9. 依据嵌套虚拟化、RBD 可导出性、VMware 能力与 TCG 上限填写 `workload_access_strategy`；只有 `workload_storage_ready` 后，Executor 才能把所选策略的 Guest 访问门标为完成。

`required_nodes` 为空，或其中任一节点缺少映射的系统盘/OSD 盘，或预期 MON/OSD/Pool、workload 映射缺失时，必须写入 `missing_inputs` 和 blocker Finding；只有数组中的全部 required nodes 和磁盘满足门禁，才能描述集群恢复完成。

对于 `selected_strategy: rbd-offline-mount`，计划必须把执行顺序固定为：Stage 2 只准备外层 PVE 节点的系统盘、OSD 盘和启动/存储恢复所需工作产物；Stage 5 先用直接证据完成 `ceph_ready` 与 `workload_storage_ready`，确认目标 RBD 实际可访问后，才执行 RBD 导出、只读挂载并创建 Guest 根文件系统 Artifact。Planner 不把 RBD 导出或挂载列入 Stage 2。

### Step 5: Plan Credentials

规划凭据来源，**不记录实际凭据值**：

```yaml
credential_source: string|null        # 凭据来源描述
credential_reference: string|null     # 凭据引用（如 "题目附件 config.yml:password 字段"）
authentication_method: string|null    # password|key|token|certificate|interactive|none
```

**Ledger Event**: 产生 `finding` event，仅记录来源和方法。

### Step 6: Define Recovery Policy

生成符合 `templates/recovery-policy.schema.json` 的恢复策略：

```yaml
recovery_policy:
  schema_version: "1.0"
  operations:
    artifact_export:
      required_capability: artifact-export
      error_classes:
        ewf_export_failure:
          auto_retry: true
          max_attempts: 2
          tool_candidates:
            - tool: ewfexport
              operation: ewf-export
          action: retry
        rbd_export_failure:
          auto_retry: true
          max_attempts: 1
          tool_candidates:
            - tool: rbd
              operation: rbd-export
          action: retry
    disk_format_conversion:
      required_capability: disk-format-conversion
      error_classes:
        unsupported_format:
          auto_retry: false
          action: replan
        tool_failure:
          auto_retry: true
          max_attempts: 2
          tool_candidates:
            - tool: qemu-img
              operation: convert
            - tool: VBoxManage
              operation: clonemedium
          action: retry
    runtime_configuration:
      error_classes:
        config_generation_failure:
          auto_retry: false
          fallback_backends: ["qemu"]
          action: fallback
    runtime_launch:
      error_classes:
        startup_timeout:
          auto_retry: true
          max_attempts: 1
          timeout_seconds: 120
          fallback_backends: ["qemu"]
          action: fallback
  default:
    auto_retry: false
    action: replan
```

`artifact_export` 是通用导出能力，但 error class 与输入来源严格绑定：

- E01/EWF 源镜像导出只能使用 `ewf_export_failure`，候选工具只能是适用于 EWF 的 `ewfexport` / `ewf-export`；
- Ceph RBD 导出只能使用 `rbd_export_failure`，候选工具只能是适用于 RBD 的 `rbd` / `rbd-export`；
- 两类失败不得互相使用对方工具作为 retry 或 fallback，也不得把 source type 不匹配的候选写入同一 error class；
- Executor Stage 0 调用 `tool-router` 时，必须同时验证候选工具能力、operation 与当前输入类型匹配；只有“工具可用”和“来源适用”都通过，候选才可执行。

**注意**：`recovery_policy` 中 `fallback_backends` 必须属于 `execution_scope.fallback_backends`。`artifact_export` 只保留与当前 source type 匹配的具体导出 operation 候选，不把 `ewf-export` 与 `rbd-export` 互作 fallback。

**工具选择规则**：只声明 `required_capability` 和候选 `tool_candidates`（`tool` + `operation`）。最终可用工具由 `tool-router` 在 executor Stage 0 判断。

**Ledger Event**: 产生 `state-transition` event。

### Step 7: Define Executor Handoff

hybrid-cluster 的 `executor_handoff` 必须原样携带 Router 的 `target_bindings` 数组，以及同一 `plan_id`、`route_id`、`cluster_rebuild_profile`、资源预算、VMware 控制策略和 `execution_scope` 引用；Planner 不重写绑定或把数组折叠为单对象。只有全部 required nodes/disks 已登记、写入根目录和峰值空间已通过门禁，且 `workload_access_strategy.selected_strategy` 非空、`readiness: ready` 时，才允许 handoff；这里的 ready 仅表示计划可执行，不得作为 RBD 已访问或 Guest 已恢复的证据。

### Feasibility-Based Routing

| Feasibility | Route |
|------------|-------|
| `yes` | handoff → executor |
| `partial` 且可降级 | handoff → executor |
| `partial` 且关键输入缺失 | `plan_status: blocked`，返回 Router 或请求补充输入 |
| `no` + 有远程入口 | handoff → `remote-live` |
| `no` + 有虚拟化存储拓扑 | handoff → `hybrid-cluster` |
| `no` + 无远程入口且无虚拟化拓扑 | handoff → `offline-image` |
| `blocked` | `route_status: blocked`，不生成 executor handoff |

`blocked` 不触发 `execution_gate`——它表示计划无法执行，应设置 `route_status: blocked` 并通知上游。

### Reentry from Executor

当 executor 返回 planner 重新规划时：

- executor `step.status` 为 `blocked` 或 `failed`
- 本 skill reentry `step.status` 设为 `pending`
- `handoff.status` 设为 `pending`
- `route_status` 保持 `active`
- `reentry_reason` 必须记录 `operation` 和 `error_class`
- `new_evidence_refs` 引用 executor 本轮 Ledger Event

只有以下情况 `route_status` 才为 `blocked`：

- 没有允许的 replan 路径
- `hop_count` 超限
- `execution_gate` 未解决
- 缺少任何可继续输入

### Planner-Executor Boundary

| 维度 | Planner（本 skill） | Executor（server-rebuild-executor） |
|------|-------------------|-----------------------------------|
| 评估 | 判断是否可重建、选择后端 | 验证 plan（Stage 0）、检查工具可用性 |
| 规划 | 资源需求、网络、凭据、恢复策略 | 不重新规划，按 plan 执行 |
| 执行 | 不执行任何操作 | Stage 0-6 逐步执行 |
| 恢复 | 定义 `recovery_policy` 边界 | 在 `recovery_policy` 范围内自动恢复 |
| 超出范围 | — | 退回 planner 重新规划 |
| 状态 | 输出 `plan_id` + `execution_scope` | 持久化 `rebuild-status.json`，记录每个 Stage |

## Evidence Requirements

| Event Type | When | LED-Event Fields |
|-----------|------|-----------------|
| `finding` | 可行性判断、后端选择、资源/网络/凭据规划 | `finding`, `confidence` |
| `state-transition` | 恢复策略定义 | `stage`, `next_action` |
| `handoff` | 交接给 executor | `handoff_id`, `route_id`, `artifact_refs` |

Handoff 结构细节保存在 `route_record.handoffs`，Ledger Event 只引用 `handoff_id`、`route_id`、`artifact_refs`。

所有 ledger event 由 `evidence-ledger` 负责持久化。

## Investigation Summary

```markdown
## Investigation Summary

**Current Assessment**: 重建可行性 <feasibility>，后端 <backend> (<selection_status>)

**Key Evidence**:
1. <证据1>
2. <证据2>

**Excluded Routes** (if any): <原因>

**Route Plan**:
- server-rebuild-executor（从 route_record.route_plan 渲染）

或（feasibility=no 时）：
- <offline-image / remote-live>（从 route_record.route_plan 渲染）
```

## Execution Gate

`execution_gate` 仅在操作超出 `execution_scope` 已批准范围时触发：
- 需要执行 `execution_scope` 未批准的 Stage
- 需要修改原始检材（`source_modification_allowed: false` 时）
- 需要使用 `approved_network_modes` 未包含的网络模式
- 需要启用 `fallback_backends` 未列出的后端

`rebuild_feasibility: blocked` 不触发 execution_gate——它应设置 `route_status: blocked` 并停止。

`bridge` 模式仅在 `execution_scope.approved_network_modes` 明确包含时才能执行。

## Stop Conditions

- `rebuild_feasibility` 为 `blocked`：缺少必要信息，`route_status: blocked`
- `rebuild_feasibility` 为 `no` 且无远程入口、无可用域分析路径
- `missing_inputs` 包含关键组件（如缺少系统磁盘）
- 所有候选后端 `backend_selection_status: unavailable` 且 `manual` 不可行
- PVE/Ceph 的 required nodes、system/OSD disks、关键 cluster mapping 或恢复门依赖不完整
- 目标写入根目录不在 `allowed_write_roots`、峰值空间不足，或资源预算无法证明可安全写入

## Quality Checklist

- [ ] 不执行任何重建操作（镜像导出、磁盘转换、VM 创建、启动）
- [ ] 输出 `plan_id` 和 `plan_status`
- [ ] `selected_backend` 可为 null，配合 `backend_selection_status` 和 `backend_candidates`
- [ ] `network_mode` 使用 `host-only|nat|isolated|bridge|backend-default|none` 枚举
- [ ] `recovery_policy` 与 `templates/recovery-policy.schema.json` 一致
- [ ] `tool_candidates` 使用 `tool` + `operation` 结构；不同 operation 不混在同一 error class
- [ ] 工具选择只声明 capability 和候选，不假定具体命令可执行
- [ ] 不记录实际凭据值
- [ ] `credential_source`、`credential_reference`、`authentication_method` 可为 null
- [ ] `route_record` 使用 `route_step_id` 和 `dependency_step_ids`
- [ ] feasibility=blocked 时 `route_status: blocked`，不触发 execution_gate
- [ ] feasibility=no 时根据证据选择 offline-image/remote-live/hybrid-cluster
- [ ] Handoff 包含 `from_step_id`、`to_step_id`、`visited_skills`、`hop_count`
- [ ] `executor_handoff` 包含 `plan_id`、`route_id`、`artifact_refs`、`execution_scope`
- [ ] `execution_scope` 使用结构化批准范围（approved_stages、approved_operations 等）
- [ ] 所有 ledger event 写入 `ledger_events` 数组
- [ ] 不生成旧引用（`battle summary`、`competition-autopilot`、`server-answer-gate`）
- [ ] Investigation Summary 的 Route Plan 从 `route_record.route_plan` 渲染
- [ ] `request.payload` 可接收 `tool_capability_report`
- [ ] `recovery_policy` 中 `fallback_backends` 属于 `execution_scope.fallback_backends`
- [ ] `backend_selection_status=confirmed` 需要完整工具和能力验证，不凭 `tool_capability_report` 存在推断
- [ ] PVE/Ceph profile 含 required nodes/disks、双网络、预期 MON/OSD/Pool、workload volume map、recovery gates 和 workload access strategy
- [ ] PVE/Ceph 顺序遍历 `required_nodes` 及其磁盘集合，直到 Pool/RBD 可用后才完成 Guest 访问门
- [ ] VMware `mcp-only` 不包含 vmrun/vmrest fallback；MCP 必需能力逐项预检
- [ ] WSL2 QEMU/TCG 不是多节点默认方案；TCG 仅为 1 次/300 秒有界降级
- [ ] 资源预算区分逻辑大小、estimated/actual sparse 占用和峰值空间；Planner 只门禁估算、剩余空间与 `allowed_write_roots`，actual 由 Executor 填写
- [ ] reentry 时 `handoff.status=pending`，`reentry_reason` 明确记录 `operation/error_class`
- [ ] `route_status=blocked` 仅在无 replan 路径、hop 超限、execution_gate 未解或输入缺失时设置

## Notes

- planner 只输出规划，不执行任何操作
- planner 不替代 `cluster-virtualization-forensics` 解析 Ceph/PVE 存储层；它消费已完成的 cluster mapping 并生成多节点恢复计划
- 本 skill 不保留旧引用（`competition-autopilot`、`triage-files`、`server-answer-gate`、`battle summary`、`E:\CompetitionTools`）
