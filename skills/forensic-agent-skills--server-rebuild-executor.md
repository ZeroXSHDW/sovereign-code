---
name: server-rebuild-executor
description: 执行已由 server-rebuild-planner 生成并批准的服务器重建计划。按 Stage 0-6 完成能力预检、工作副本准备、运行或离线访问、状态落盘、计划内失败恢复，并按 Guest 访问模式交接 live-response 或 offline domain skills。
---

# server-rebuild-executor

## Purpose

将 server-rebuild-planner 输出的 rebuild_plan 转换为可审计的 Stage 0-6 执行过程。严格在 execution_scope 与 recovery_policy 内执行，持续更新 rebuild-status.json；live 成功后交给 remote-server-live-response，offline mount 成功后把 Guest 根文件系统 Artifact 交给 domain skills，计划外动作或恢复失败时返回 planner 重新规划。

## Use When
- planner 已输出 plan_id、可执行的 rebuild_plan 和非空 executor_handoff
- plan_status: ready，且 feasibility 为 yes 或可降级执行的 partial
- 需要启动 VMware、QEMU、VirtualBox、Docker、WSL 或已定义的 manual 流程
- hybrid-cluster 选择 `rbd-offline-mount`，需要在批准范围内生成并交接 Guest 根文件系统 Artifact
- 需要重建状态持久化、阶段恢复和可复现连接交接

## Do Not Use When
- 尚未判断是否应重建：先调用 server-rebuild-planner
- planner 输出 plan_status: blocked|rejected 或 executor_handoff: null
- 路线本身为 remote-live 或 offline-image（hybrid-cluster 内已批准的 `rbd-offline-mount` 仍由本 Executor 执行）
- PVE/Ceph/多节点存储拓扑尚未由 cluster-virtualization-forensics 映射
- 需要 Linux、Web、Database 或 Docker 的深度取证；这些属于下游 domain skills
- 需要修改 rebuild plan、扩大 execution scope 或生成最终报告

## Request Contract

遵循 templates/request-envelope.schema.json。request.payload 至少包含：

~~~yaml
rebuild_plan: object
tool_capability_report: object|null
target_bindings: array
~~~

rebuild_plan 是 planner 响应 payload 的不可变包装，必须包含 plan_id、plan_status、rebuild_feasibility、selected_backend、backend_selection_status、backend_profile、prepared_artifact_requirements、resource_requirements、network_mode、port_mapping、recovery_policy、execution_scope、凭据引用和 executor_handoff。`target_bindings` 必须与 Planner payload/executor_handoff 中的数组一致并原样传入；source artifacts 使用 request.material_info.artifact_refs；request.context 必须携带上游 route_record，且 plan_id、route_id 和 handoff 一致。

hybrid-cluster 还必须包含非空 `required_nodes`、节点到系统盘/OSD 盘的映射，以及结构化 `workload_access_strategy`。Executor 只执行 `selected_strategy`，并据此设置：`nested-launch|rbd-separate-vmware|bounded-tcg` → `guest_access_mode: live`；`rbd-offline-mount` → `guest_access_mode: offline`。

拒绝 selected_backend: null、backend_selection_status: unavailable 或与 plan_id 不一致的 handoff。实际凭据值不进入请求副本、状态文件、命令行、日志或 Ledger Event。

## Response Contract

遵循 templates/response-envelope.schema.json。专项结果只放在 payload：

~~~yaml
schema_version: "1.0"
investigation_summary: object
route_record: object
findings: array
ledger_events: array
artifact_refs: array
payload:
  target_bindings: array
  plan_id: "plan-<uuid>"
  rebuild_status: object
  rebuild_status_path: "work/rebuild/rebuild-status.json"
  overall_status: pending|in_progress|blocked|partial|completed|failed|rolled_back
  current_stage: 0|1|2|3|4|5|6
  prepared_artifacts: array
  runtime_definition: object|null
  runtime_instance: object|null
  runtime_running: boolean
  guest_access_mode: live|offline|null
  offline_guest_artifact_refs: array
  network_config: object|null
  services_discovered: array
  cluster_gate_status: object|null
  connection_info:
    connections: array
  recovery_actions: array
  blockers: array
~~~

route_plan 与 handoffs 只存在于 route_record。`guest_access_mode: live` 成功时创建到 remote-server-live-response 的 Route Step/Handoff；`guest_access_mode: offline` 成功时直接创建到证据支持的 offline domain Route Step/Handoff。超出计划时创建返回 server-rebuild-planner 的 reentry handoff，`handoff.status` 为 `pending`，`route_status` 保持 `active`，并记录 `reentry_reason` 和 `new_evidence_refs`。

PVE/Ceph 的 `cluster_gate_status` 写入现有 Stage 5 `outputs` 并投影到 Response `payload`；它不是新的 Route、Stage 或 rebuild-status 顶层结构。

## Planner–Executor Boundary
| Planner owns | Executor owns |
|---|---|
| feasibility、backend 候选、资源、网络和凭据来源规划 | 验证计划与能力并执行已批准动作 |
| recovery_policy 与 execution_scope | 计划内 retry/fallback 和状态持久化 |
| 生成 plan_id 与 executor handoff | 沿用 plan_id，不改写规划 |
| 计划外重新规划 | 阻断、留证并 handoff 回 planner |

Executor 不把“已规划”写成“已执行”，不把“能启动”写成“已稳定”，不把配置推测写成恢复事实。

## State Files and Workspace

使用案件工作区内的相对路径：

~~~text
work/rebuild/rebuild-status.json
work/rebuild/rebuild-status.json.tmp
logs/rebuild/
output/rebuild/
~~~

初始化时创建包含 Stage 0-6 的状态对象。每次状态转换后：

1. 将完整新状态写入临时文件。
2. 验证其符合 templates/rebuild-status.schema.json。
3. 以同一文件系统内的原子替换更新正式文件。
4. 将旧错误、stdout、stderr 和 attempt 详情保留在 logs/rebuild/，不得静默抹除。

完成的 Stage 必须至少引用一个 evidence_event_id；Stage 编号和名称固定对应，且 0-6 唯一、完整。

## Resume and Idempotency

1. `rebuild-status.json` 不存在：初始化包含 Stage 0-6 的新状态。
2. 文件存在且 `plan_id`、`route_id` 一致：
   - 先验证 Schema；
   - 验证 completed Stage 的 `evidence_event_ids` 和输出 Artifact；
   - 从第一个未完成 Stage 继续；
   - 不重新执行已完成 Stage；
   - runtime 已存在时先查询实际状态，不重复启动。
3. 文件存在但 `plan_id` 或 `route_id` 不一致：
   - 冲突的旧状态文件保持不变，不得为了记录 blocked 而改写；
   - 本次 Response 的 `overall_status` 设置为 `blocked`；
   - 生成 finding 和 `state-transition` Ledger Event 记录冲突；
   - 返回 planner。
4. 文件损坏：
   - 原文件保留为带时间戳的损坏副本；
   - 不静默重建；
   - 阻断并报告。
5. Retry 必须增加 `attempt`，并保留历史日志和错误信息。

## State Transition Table

### Stage 状态

~~~text
pending → in_progress → completed
in_progress → retrying → in_progress
in_progress → blocked | failed
~~~

`completed` 不得无条件回到 `pending`。

### Overall 状态

~~~text
pending → in_progress
in_progress → completed | partial | blocked | failed | rolled_back
partial | blocked | failed → rolled_back
~~~

`partial|blocked|failed → rolled_back` 仅在 rollback 位于 `execution_scope`、存在有效 checkpoint，且所有批准的 rollback 操作成功后允许。

### Stage Rollback 状态

~~~text
completed | blocked | failed → rolled_back
~~~

仅限该 Stage 创建了可逆工作状态。源检材引用和纯审计 Stage 不标为 `rolled_back`。

`current_stage` 在 Stage 开始前更新。

### 状态变化流程

每次状态变化：

1. 先生成 `state-transition` Ledger Event；
2. 再使用临时文件和原子替换更新 `rebuild-status.json`。

## Stage 0-6 Workflow

### Stage 0 — Plan Validation & Preflight

**Preconditions**

- plan_status: ready
- plan_id、route ID、executor handoff 和 source artifact refs 一致
- Recovery Policy 符合 templates/recovery-policy.schema.json

**Actions**

1. 验证 backend、network mode、Stage 和 operation 均在 execution_scope 内。
2. 验证 source Artifact Record 存在，路径和 preservation 状态可解析。
3. 检查 CPU、RAM、工作磁盘空间、所需权限和网络创建能力。
4. 读取 tool_capability_report；缺失、过期、字段不完整或结论不明确时调用 tool-router 重新检查。
5. 即使报告对象存在，也必须核对目标 backend、运行程序、格式工具和必需 capability 的状态确为 available，才能将 backend 视为 confirmed。
6. 对 VM 后端检查虚拟化和嵌套虚拟化；对 Docker 检查 daemon/compose；对 WSL 检查发行版导入与运行能力。
7. 只验证 credential_reference 可解析，不读取或记录实际凭据。
8. 验证资源预算中的逻辑大小、稀疏占用、预计峰值空间和目标盘可用空间；目标目录必须属于 `allowed_write_roots`。
9. VMware 计划为 `mcp-only` 时，逐项核对 `mcp_registered`、`health_status`、实际加载模块路径/版本或 Hash，以及计划需要的 MCP 能力；禁止用 Workstation 已安装或 MCP 已注册替代能力预检。

**Outputs**
- preflight_report 至少包含 checked_at、recommended_backend、backend_profile、available_tools、missing_tools、available_capabilities、missing_capabilities、disk_space_available、storage_budget、allowed_write_roots、write_root_allowed、admin_privilege、virtualization_supported、network_capabilities 和 blocker
- 经直接能力检查 confirmed 的目标 backend

**Completion criterion**

目标 backend 的所有必需 capability 均有直接检查结果，资源满足要求，且执行未越出 scope；否则本 Stage 为 blocked。

**Evidence**

为每个有证据价值的检查输出 command/finding event，并用 state-transition event 完成 Stage 0。

**Failure and recovery**

- 目标 backend 不可用或结果不明确：overall_status: blocked，handoff 回 planner；Stage 0 不执行 runtime fallback。
- 缺失能力或 scope 越界：overall_status: blocked，handoff 回 planner。
- 不因 capability report “存在”而推断工具可用。
- `mcp-only` 下 MCP 未注册/不健康、实际加载实现不一致、参数契约错误或任一必需能力失败：记录 `tooling_defect`，阻断本 Stage 并返回 Planner；不得改用 `vmrun`、`vmrest` 或本地 VMware 命令。
- 工具维护不属于案件执行 Stage；不得在本 Stage 修改 MCP 代码、重载后原地继续。

### Stage 1 — Workspace & Source Preservation

**Preconditions**

- Stage 0 completed
- 案件工作区和 source artifact refs 可用

**Actions**

1. 建立 work/rebuild、logs/rebuild 和 output/rebuild。
   - 创建前确认解析后的工作目录位于 `allowed_write_roots`；禁止因空间不足改写到 C 盘或其他未批准根目录。
2. 从既有 Artifact Record 登记 source artifacts，不重新发明 Artifact ID。
3. 建立 source → working artifact 映射，但尚未执行未批准的复制或转换。
4. 按 large-artifact-strategy 决定 Hash 状态：verified|provided|deferred|unavailable；不使用固定大小阈值。
5. 使用 original-reference|read-only-mounted|working-copy-created 描述 preservation 状态；不要把普通 lock 文件称为只读锁。

**Outputs**
- workspace_path、完整 source_artifacts、source → working map、可用空间和 rollback checkpoint

**Completion criterion**

每个 source artifact 均可追溯到既有 Artifact Record，Hash 状态和 preservation 状态明确，且源检材未被默认修改。

**Evidence**

记录 workspace、Artifact 引用、Hash 决策和 preservation finding。

**Failure and recovery**

源不存在、Artifact 引用断裂或空间不足时阻断；不得通过删除已有成果或更改源检材来绕过。

### Stage 2 — Artifact Preparation

**Preconditions**

- Stage 1 completed
- 所需 operation 位于 execution_scope.approved_operations

**Actions**

按计划分别处理 artifact access/export、disk format conversion、image extraction、working copy creation 和 backend-specific preparation。每个 operation 先由 tool-router 依据 capability 选择实际工具。

- ewfexport `ewf-export`：仅从 E01/EWF 源导出
- xmount mount：提供只读访问，不等价于导出产物
- qemu-img convert：磁盘格式转换，不假定可直接读取 E01
- VBoxManage clonemedium：仅在其格式与 operation 适用时使用

仅准备外层 PVE 节点的系统盘、OSD 盘、启动/存储恢复所需工作产物，或普通非集群计划需要的磁盘/服务材料；支持时可使用 sparse 输出，但必须验证逻辑大小、实际占用和后端兼容性。

写入前重新核对源镜像逻辑大小、导出逻辑大小、预计稀疏占用、预计峰值空间与目标盘可用空间；本 Stage 每个写入 attempt 后用文件系统直接结果把实际稀疏占用写入现有 `rebuild-status.stages[2].outputs.storage_budget.actual_sparse_allocated_bytes`。不得改写不可变 `rebuild_plan.resource_requirements.storage_budget`。flat 磁盘逻辑容量巨大不能成为直接开始导出/转换的依据；空间预算不成立时阻断，不产生部分写入后再临时换盘。

hybrid-cluster 选择 `rbd-offline-mount` 时，本 Stage 不导出目标 RBD、不挂载 Guest 文件系统，也不创建 Guest 根文件系统 Artifact；这些动作必须等待 Stage 5 以直接证据完成 `ceph_ready` 和 `workload_storage_ready`。

**Outputs**
- 每个新工作产物的 Artifact Record
- prepared_artifacts 与 source artifact 映射
- output Hash 状态和验证 finding
- 同步投影到 rebuild_status.working_artifacts，包含 type、hash 和非空 created_at

**Completion criterion**
每个 required prepared artifact 均存在、可读、映射到 source artifact，并通过计划指定的格式或完整性验证。

**Evidence**

- command event 使用 `output_artifact_refs` 引用其产出的 Artifact；
- artifact event 使用非空 `artifact_refs` 引用涉及的 Artifact；
- finding event 引用相关 Artifact 和对应的 command Ledger Event。

产物 ID 不得只写入 `output_artifact_refs` 而省略 `artifact_refs`。

**Failure and recovery**

仅按相同 operation 且与输入来源匹配的 error class 重试。Stage 2 的 E01/EWF 导出只使用 `ewf_export_failure`，不得调用 `rbd`；Stage 5 的 Ceph RBD 导出只使用 `rbd_export_failure`，不得调用 `ewfexport`。不得把 export、mount 和 conversion 互相当作等价 fallback；达到对应 `max_attempts` 后返回 planner 重新规划。

### Stage 3 — Runtime Configuration

**Preconditions**

- Stage 2 completed
- prepared artifacts 满足 backend profile

**Actions**

生成 runtime_definition，不要提前创建 runtime_instance：

VMware `mcp-only` 计划中的 VM 创建、配置写入和磁盘附加只能调用已注册 VMware MCP 中已预检为 available 的 `create_vm`、`config_set`、`disk_attach`；能力失败立即保留失败证据并 handoff 回 Planner，不得自行切换本地 VMware 命令。

~~~yaml
runtime_definition:
  planned_name: string
  backend: vmware|qemu|virtualbox|docker|wsl|manual
  config_artifact_ref: "artifact-<uuid>"
  config_path: string
  config_type: string
  resources:
    cpu: integer
    ram_mb: integer
    disk_paths: array
  prepared_artifact_refs: array
  startup_method: string
  backend_profile: object
~~~

**Completion criterion**

配置产物存在并可解析，资源、磁盘和启动方法与 rebuild plan 一致，尚未声称实例已启动。

**Evidence**

配置文件作为 Artifact；生成命令、参数验证和配置摘要分别进入 Ledger。

**Failure and recovery**

仅在 runtime_configuration policy 中选择 fallback backend，且该 backend 同时位于 execution_scope.fallback_backends。切换后必须重新验证 Stage 2 输出兼容性；不兼容则阻断并重新规划。

### Stage 4 — Network Configuration

**Preconditions**

- Stage 3 completed
- network mode 位于 execution_scope.approved_network_modes

**Actions**

- 支持 host-only|nat|isolated|bridge|backend-default|none。
- bridge 仅在 scope 明确包含时使用。
- none 不创建网络；backend-default 记录后端实际采用的配置。
- 端口映射只用于适用的 backend。
- 记录网络创建、变更和验证命令。
- VMware `mcp-only` 的网络变更只使用已预检的 MCP `network_config` 能力；失败时阻断并返回 Planner。

**Outputs**

- network_config
- port_mapping、ports_mapped: boolean 与验证 finding

**Completion criterion**

实际网络模式和端口映射已验证且未越出 scope；none 和 backend-default 也有明确结果。

**Failure and recovery**

不得静默切换到 bridge、NAT 或其他未批准模式。计划外模式设置 execution gate 并 handoff 回 planner；在修订后的计划进入前不得继续执行。

### Stage 5 — Runtime Launch & Stabilization

**Preconditions**

- Stage 4 completed
- 通用 rebuild 的 runtime definition、network config 和日志路径就绪
- hybrid-cluster 的 `workload_access_strategy.selected_strategy` 及外层节点/存储恢复准备产物已验证；live 策略还必须具有可执行的 Guest runtime definition，offline 策略必须具有目标 RBD 的 `workload_volume_map` 和通过空间门禁的导出/挂载计划，但此时不得假定 RBD 已可访问

**Actions**

1. hybrid-cluster 根据 `selected_strategy` 设置 `guest_access_mode`；非 cluster rebuild 使用 `live`。不得在 Stage 中自行更换未批准策略。
2. hybrid-cluster 遍历 `required_nodes` 及其磁盘映射，启动/验证所有外层节点，并严格按序推进 `outer_nodes_launched` 至 `workload_storage_ready`；在 `ceph_ready` 与 `workload_storage_ready` 都 completed 前，不得执行任何目标 RBD 导出或 Guest 访问动作。
3. `guest_access_mode: live` 时执行批准的 Guest 启动或访问动作；hybrid-cluster 必须等待 `workload_storage_ready` completed，普通非集群 rebuild 则遵循其既有 Stage 4 前置条件。按 backend profile 等待稳定并使用有上限的 timeout 和健康检查；取得直接 Guest 访问证据后才完成适用的 `guest_access_ready` 并生成：

~~~yaml
runtime_instance:
  instance_id: string
  instance_type: string
  launched_at: ISO8601
runtime_running: boolean
startup_log: string              # 捕获日志的相对路径，不内嵌日志正文
startup_log_artifact_ref: "artifact-<uuid>"
startup_errors: array
~~~

4. `guest_access_mode: offline` 时，仅在 `workload_storage_ready` completed 后按 `selected_strategy: rbd-offline-mount` 执行目标 RBD 导出与只读挂载，创建可追溯的 Guest 根文件系统 Artifact，并以这些直接证据完成 `guest_access_ready`；每个导出 attempt 后把实际稀疏占用写入 `rebuild-status.stages[5].outputs.storage_budget.actual_sparse_allocated_bytes`。不启动 Guest，不创建 `runtime_instance` 或 Live Session，并允许 `runtime_running: false`。
5. 保存启动日志或 Stage 5 的 RBD 导出/挂载日志为 Artifact。
6. retry 或 fallback 始终必须同时受 `recovery_policy` 与 `execution_scope` 约束；hybrid-cluster 还必须位于 `workload_access_strategy.fallback_order`，普通非集群 rebuild 不读取该 cluster 专项字段。

**Completion criterion**

- **live**：Guest 运行实例可被后端查询，健康/稳定检查有直接输出，`runtime_running: true` 与实际状态一致；超时不算成功。
- **offline**：在 `workload_storage_ready` 后执行的目标 RBD 导出/只读挂载成功，Guest 根文件系统 Artifact 存在、可读并绑定源 RBD/命令 Ledger Event；不要求 Guest `runtime_running`，且不得创建伪造 runtime/connection 记录。

**Retry behavior**

- Stage 状态改为 retrying，attempt 增加。
- Retry event 使用 parent_event_id 关联最初失败 event。
- 每次 attempt 保留独立 stdout/stderr。
- 超过 max_attempts 后阻断或失败，不无条件切换 backend。

#### PVE/Ceph Hard Gates

当 plan 含 `cluster_rebuild_profile` 时，Stage 5 的 `outputs.cluster_gate_status` 必须包含下列七个子状态；Executor 遍历 `required_nodes` 及其磁盘集合，并按 `workload_access_strategy.selected_strategy` 动态验证。每项只允许在直接证据满足完成标准后从 pending/in_progress 进入 completed，任一必需项失败则为 blocked：

```yaml
outer_nodes_launched: pending|in_progress|completed|blocked
node_networks_ready: pending|in_progress|completed|blocked
management_services_ready: pending|in_progress|completed|blocked
corosync_ready: pending|in_progress|completed|blocked
ceph_ready: pending|in_progress|completed|blocked
workload_storage_ready: pending|in_progress|completed|blocked
guest_access_ready: pending|in_progress|completed|blocked
```

门禁严格串行，后一项必须依赖前一项 completed，并把直接输出的 Ledger Event ID 写入 Stage 5 `evidence_event_ids`：

1. **outer_nodes_launched**：`required_nodes` 数组非空，数组中的每个外层节点都由所选后端查询为运行；hostname 与计划一致，且该节点映射的全部系统盘和 OSD 盘存在。任一 required node 或磁盘不满足都不得完成。
2. **node_networks_ready**：每台节点的管理网与 Ceph 存储网接口都经过运行态验证；仅阅读配置文件不能证明网络已生效。
3. **management_services_ready**：每台节点的 SSH 端口和 PVE WebUI 8006 都有直接连接证据。
4. **corosync_ready**：保存 `pvecm status` 直接输出，且 `Quorate: Yes`；推测 quorum 或只看配置不得完成。
5. **ceph_ready**：保存 `ceph -s`、`ceph osd tree`、Pool 与 RBD 检查输出；必须直接验证 MGR 状态，且实际 MON/OSD/Pool 集合满足 plan 的 `expected_monitors`、`expected_osds`、`expected_pools`。
6. **workload_storage_ready**：目标 RBD 必须能被实际访问并与 `workload_volume_map` 对应；配置中存在 RBD 引用不等于内容可用。
7. **guest_access_ready**：只在 `workload_storage_ready: completed` 后按 `selected_strategy` 执行并验证。live 策略中 `qm status` 为 running 仅是候选证据，还必须至少取得 tap 设备、VNC/console 可用、Guest IP、SSH 或业务端口之一；`rbd-offline-mount` 必须在本 Stage 完成 RBD 导出、只读挂载并创建 Guest 根文件系统 Artifact，且不要求 Guest runtime。不得用 Stage 2 准备产物替代这些直接证据。

七项未全部 completed 时，PVE/Ceph 的 Stage 5 不得 completed，Stage 6 不得创建成功 handoff，也不得声称集群或 Guest 已恢复。

#### Bounded TCG Stop Rule

仅当 `selected_strategy: bounded-tcg` 时允许 PVE Guest 的 TCG 降级尝试，并且必须同时满足：

- `max_attempts: 1`
- `max_wait_seconds: 300`

在上限内连续没有控制台变化、网络证据或服务证据时立即停止：恢复尝试前的原 VM 配置，保存配置差异、stdout/stderr 和失败日志。仅当 `fallback_order` 的下一策略已在当前 policy/scope 中批准时才切换；否则返回 Planner 重新规划。禁止无限截图、重复 VNC/console 尝试或重复启动。

VMware `mcp-only` 的 power、screenshot 和 console 操作只能调用已预检的 MCP 能力。能力失败时返回 Planner；不得调用 `vmrun`、`vmrest`、其他本地 VMware 控制命令，也不得在正式 Stage 中修改 MCP 代码。

### Stage 6 — Service Discovery, Connection Test & Handoff

**Preconditions**

- Stage 5 completed
- 存在 PVE/Ceph profile 时，其七项 `cluster_gate_status` 必须全部 completed；普通非集群 rebuild 不适用此门禁
- live：`runtime_running: true`；offline：非空 `offline_guest_artifact_refs` 且 Guest 根文件系统 Artifact 已验证可读

**Actions**

按 `guest_access_mode` 执行互斥分支。

**live**：

1. 在批准范围内发现端口和服务。
2. 执行低影响连接测试，记录命令与结果。
3. 生成不含实际凭据的 connection records：

~~~yaml
connections:
  - connection_id: string
    type: ssh|webui|db-client|docker-exec|winrm|rdp|service-client
    host: string
    port: integer
    service: string|null
    credential_source: string|null
    credential_reference: string|null
    authentication_method: password|key|token|certificate|interactive|none
~~~

4. 将服务、入口和验证 finding 关联到 Artifact 和 Ledger。
5. 在 `route_record.route_plan` 中创建或完成 `remote-server-live-response` Route Step，并生成 Handoff。

**offline**：

1. 复核只读挂载状态、Guest 根文件系统 Artifact、源 RBD 映射和 Hash 状态。
2. 将根文件系统 Artifact 与导出/挂载命令、Finding、Ledger Event 绑定。
3. 遍历 `target_bindings` 数组，对每个 guest-level binding 按其 `target_type`、`target_ref`、`expected_evidence_type` 和 `dependency_step_ids` 创建或完成证据支持的 `linux-server-forensics`、`webapp-server-forensics`、`database-server-forensics` 等 offline domain Route Step/Handoff；不得把数组当作单对象，也不得为无匹配证据的 binding 猜测下游。
4. 保持 `runtime_running: false`，`connection_info.connections: []`；不得创建 `remote-server-live-response`、connection record 或 Live Session。

**凭据和认证边界**

live 分支的 Stage 6 默认只做低影响、非认证确认：

- TCP 连接
- 服务 Banner
- HTTP health check
- 明确的端口映射
- 后端运行状态

认证后的 live 取证采集交给 `remote-server-live-response`；offline 分支不执行认证或远程连接。

必须使用 Secret 时：

- 通过 `credential_reference` 即时解析
- 不放进命令行参数
- 不写入 `rebuild-status.json`
- 不写入 Ledger
- 不出现在 stdout 或 stderr
- 使用 stdin、环境变量、Secret Store 或受限临时文件
- 使用后清理临时 Secret 材料

**live 服务发现范围**

只允许以下目标：

- `runtime_instance` 自身地址
- `localhost`
- host-only 地址
- 明确的 `port_mapping`

不得执行无范围的子网扫描。

**Completion criterion**

- **live**：至少一个服务或已证实的“未发现服务”结果有直接证据；所有连接记录均来自实际发现。
- **offline**：Guest 根文件系统 Artifact、只读挂载验证和 offline domain Handoff 均通过 route/finding/artifact refs 可追溯；不要求服务发现结果。

**Failure and recovery**

不得伪造 connection info。live 服务未发现时保留 Stage 0-5 产物并设置 partial|blocked|failed；仅当既有 route_record 已包含批准的 offline fallback 时才能切换。offline 导出/挂载失败时按同一 operation 的 policy 处理，超出 scope 则 handoff 回 planner。

## Backend Profiles
| Backend | Capability checks | Configuration and launch evidence |
|---|---|---|
| VMware | Workstation 与计划指定控制策略；`mcp-only` 时逐项验证已注册 MCP、实际加载实现、create/config/disk/network/power/interaction 能力及 nested virtualization | VMX/config Artifact；按 plan 为多节点配置 system + data/OSD disks；`mcp-only` 只记录 MCP 调用与返回，不生成本地控制命令 |
| QEMU | qemu-system-* 负责运行，qemu-img 只负责格式；验证 Windows/WSL 可用性和性能 | 完整启动参数、PID/monitor/serial log、状态查询；PVE 多节点网络复杂时不得盲目采用 WSL2 QEMU/KVM |
| VirtualBox | VBoxManage、嵌套虚拟化及 PVE/Ceph 兼容性检查 | 注册/config/startvm/状态输出；兼容性未验证时保持 provisional |
| Docker | daemon、Compose、image/load/build 能力按 plan 验证 | resolved Compose config、容器 ID、health/log output |
| WSL | import/distro/run 能力；仅用于 rootfs/distro 或适合 WSL 的应用 | distro 名、导入 Artifact、服务启动和端口证据 |
| manual | 明确人工步骤与产物引用 | 每一步命令/截图/日志均进入 Ledger；不得宣称未验证成功 |

### PVE/Ceph Multi-node Profile

仅在 planner/backend profile 已明确 required nodes/disks、多节点顺序、双网络、预期 Ceph 成员、workload volume map 与 scope 时执行。执行结果必须通过 Stage 5 七项硬门禁，不再以启动顺序说明替代完成标准。

- 不自动修复 Ceph，不重置密码，不修改 `/etc/network/interfaces`，不启动未批准的 VM。
- 任一节点或必需磁盘失败时保留已完成状态与证据；按 policy retry，计划外拓扑变更 handoff 回 server-rebuild-planner，由 planner 决定是否先调用 cluster-virtualization-forensics 重新映射。

## Recovery Policy Execution
对失败先分类为 operation + error_class：

1. 找不到对应策略：使用 default，通常为 replan。
2. auto_retry: true 且未超过 max_attempts：执行同 operation 的候选工具或同阶段重试。
3. Backend fallback 仅允许用于 runtime configuration/launch，且必须同时存在于 policy 与 scope。
4. 所有 retry/fallback 记录 recovery action、parent event、attempt 和输出路径。
5. 超出 policy 或 scope：Stage 转为 blocked|failed，不得扩权执行。

计划内自动恢复不得修改源检材、删除已有成果、改变未批准网络模式或引入未登记输入。

## Failure Classification Matrix

错误分类名称必须与 `recovery_policy` 中的 `operation.error_class` 完全一致：

| Stage | operation | error_class | recovery_policy 引用 |
|-------|-----------|-------------|---------------------|
| 0 | 无匹配 operation | `tooling_defect` | `recovery_policy.default` → replan |
| 2（E01/EWF source） | `artifact_export` | `ewf_export_failure` | `artifact_export.ewf_export_failure` |
| 5（Ceph RBD source） | `artifact_export` | `rbd_export_failure` | `artifact_export.rbd_export_failure` |
| 2 | `disk_format_conversion` | `unsupported_format` | `disk_format_conversion.unsupported_format` |
| 2 | `disk_format_conversion` | `tool_failure` | `disk_format_conversion.tool_failure` |
| 3 | `runtime_configuration` | `config_generation_failure` | `runtime_configuration.config_generation_failure` |
| 5 | `runtime_launch` | `startup_timeout` | `runtime_launch.startup_timeout` |
| 1, 4, 5（offline mount 或其他无匹配 operation）, 6 | 无匹配 operation | — | `recovery_policy.default` → replan |

`artifact_export` 的分类由 Stage 与 source Artifact type 共同决定，不能只按 operation 名称归类：

- `ewf_export_failure` 的候选只能是 `ewfexport` / `ewf-export`，不得调用 `rbd`；
- `rbd_export_failure` 的候选只能是 `rbd` / `rbd-export`，不得调用 `ewfexport`；
- `tool-router` 必须在执行前验证候选工具、operation 与当前输入类型匹配；来源不匹配视为不可用，不得跨 error class fallback；
- 超过 `ewf_export_failure.max_attempts: 2` 或 `rbd_export_failure.max_attempts: 1` 后，保留全部失败证据并 handoff 回 Planner 重新规划；
- RBD 导出后的只读挂载失败没有现有 operation 匹配时，继续使用 `recovery_policy.default` → replan。

## Rollback and Cleanup

- 只处理当前 `plan_id` 创建的 working artifacts 和 runtime；
- 不修改或删除 source artifacts；
- 不删除 Ledger、日志和失败证据；
- `rollback_available` 只有存在有效 checkpoint 且操作可逆时才为 `true`；
- rollback 完成后 `overall_status = rolled_back`；
- 每个 rollback 操作生成 command、artifact/finding 和 state-transition Ledger Event；
- 删除已有工作成果超出 `execution_scope` 时触发 `execution_gate`。

## Evidence Requirements

| Event type | Required use |
|---|---|
| command | 能力检查、导出/转换、配置、网络、启动、发现和连接测试 |
| artifact | 工作副本、转换产物、配置、启动日志及其他派生制品 |
| finding | 能力、验证、服务发现、失败分类和排除路线 |
| state-transition | 每次 Stage 状态变化、retry、fallback、blocked/failed/completed |
| handoff | 成功交给 live-response，或计划外返回 planner |

遵循 templates/ledger-event.schema.json：

- command event 必须含非空 command、started_at，完成后补 ended_at、exit_code 和 stdout/stderr。
- artifact event 必须含非空 artifact_refs；新制品使用 source_artifact_id 关联来源。
- finding event 必须含 finding、confidence，并用 artifact_refs/route_id 绑定当前证据范围；Finding Record 再用 evidence_refs 引用对应 Ledger Event。
- state-transition event 必须含固定 Stage name。
- retry event 使用 parent_event_id；handoff event 使用 route_id 与 handoff_id。

事件由 evidence-ledger 持久化到 JSONL 和 Markdown；Executor 只产生事件对象。

## Route and Handoff Rules

### Success

- 将 executor step 标为 completed。
- live：新增或激活 `remote-server-live-response` Route Step，并用 `dependency_step_ids` 指向 executor step；connection info 只包含入口元数据和凭据引用。
- offline：新增或激活证据支持的 offline domain Route Step，并用 `dependency_step_ids` 指向 executor step；Handoff 携带 Guest 根文件系统 Artifact，且 connection info 为空。
- 两种 Handoff 都使用 from_step_id、to_step_id、artifact/finding refs、visited skills 和 hop count；offline 不得伪造 live-response Handoff。

### Partial or blocked

需要重新规划时：

- executor `step.status` 设置为 `blocked` 或 `failed`
- planner reentry `step.status` 设置为 `pending`
- `handoff.status` 设置为 `pending`
- `route_status` 保持 `active`
- `reentry_reason` 记录 `operation` 和 `error_class`
- `new_evidence_refs` 引用本轮 Ledger Event

保留所有可复用 Artifact 与 completed Stage。防循环规则继续使用同一 route ID、visited skills、hop count 和 max hops。

只有以下情况 `route_status` 才为 `blocked`：

- 没有允许的 replan 路径
- `hop_count` 超限
- `execution_gate` 未解决
- 缺少任何可继续输入

每次返回 planner 都必须明确 `reentry_reason`、`handoff.status` 和 `route_status`。

## Execution Gate

仅在拟执行动作超出 execution_scope 时设置 required: true：

- Stage 或 operation 未获批准
- Backend 不在 approved/fallback 列表
- Network mode 未获批准
- 需要修改源检材
- 需要删除已有工作产物
- 需要使用 plan 中没有的新输入

blocked、失败或普通远程连接本身不等于 execution gate。Gate 未解决时不得执行越界动作；保留状态并返回 planner。

## Stop Conditions
- plan/handoff/route ID 不一致
- plan 不是 ready，或 feasibility 不允许执行
- source Artifact 无法解析或关键输入缺失
- 所需能力不可用，且无 policy/scope 同时允许的 fallback
- 可用空间不足或状态文件无法安全持久化
- 所需操作会修改源检材，而 scope 不允许
- route hop 超限或 handoff 会形成无新证据的循环
- `mcp-only` 的 VMware MCP 未注册/不健康、实际加载实现不一致、必需能力失败或需要修改 MCP 代码
- PVE/Ceph 任一 required node/disk 缺失，或七项 cluster hard gates 无法按序完成

## Failure Reporting

失败时不得只输出错误句。至少记录：

- plan_id、route ID、Stage、attempt 和 error class
- 精确命令（脱敏后）、exit code、stdout/stderr paths
- 已完成 Stages 与可复用 Artifacts
- Recovery Policy 匹配结果和已尝试动作
- 当前 overall_status、can_continue_on_failure 和 blocker
- 下一步为 retry、planner replan，或 route_record 中已批准的替代步骤

不得把凭据、token、private key 或未脱敏 secret 写入失败日志。

## Investigation Summary

~~~markdown
## Investigation Summary

**Current Assessment**: <plan_id> 已执行至 Stage <n>，状态 <overall_status>

**Key Evidence**:
1. <能力/产物/启动或服务发现证据>
2. <状态与恢复证据>

**Excluded Routes** (if any): <排除的 backend/路线及依据>

**Route Plan**:
- <从 route_record.route_plan 渲染，不独立维护>
~~~

## Quality Checklist

- [ ] Frontmatter 只有 name 与 description
- [ ] 输入/输出使用当前 Request/Response Envelope
- [ ] Planner 的 plan_id、route ID、policy 和 scope 未被改写
- [ ] Stage 0-6 唯一、完整，编号与名称符合 Schema
- [ ] backend 只有在具体能力均验证 available 后才 confirmed
- [ ] State 更新采用临时文件、Schema 校验和原子替换
- [ ] completed Stage 至少引用一个 Ledger Event
- [ ] 不使用固定文件大小阈值决定 Hash
- [ ] 不把 EWF export、mount 和 format conversion 视为等价 operation
- [ ] Stage 2 EWF 与 Stage 5 RBD 导出使用不同 error class，且不跨用 `ewfexport`/`rbd`
- [ ] live runtime instance 只在 Stage 5 成功启动后创建；offline 不创建 Guest runtime instance
- [ ] bridge 和 backend fallback 同时受 policy 与 scope 约束
- [ ] Retry 增加 attempt 并用 parent event 关联失败
- [ ] 不记录实际凭据或未脱敏 secret
- [ ] 不自动修复 Ceph、重置密码或启动未批准 VM
- [ ] connection info 来自实际服务发现，不得伪造
- [ ] live 成功 handoff 到 live-response；offline 成功直接 handoff 到 domain skills；计划外失败返回 planner
- [ ] 所有结论绑定 Artifact、Ledger Event 或命令输出
- [ ] 不硬编码本机路径，不修改原始检材
- [ ] Resume 按 plan_id/route_id 一致性和 Schema 验证决定续跑或阻断
- [ ] State Transition 按临时文件、原子替换和 Ledger Event 流程执行
- [ ] Failure Classification 与 recovery_policy operation/error_class 完全一致
- [ ] Rollback 不修改源检材、Ledger、日志或失败证据
- [ ] 凭据不进入命令行、状态文件、Ledger 或日志
- [ ] 服务发现只扫描 runtime_instance、localhost、host-only 或已映射端口
- [ ] PVE/Ceph Stage 5 包含七项硬门禁，且每项完成都绑定直接证据
- [ ] 七项门禁遍历 `required_nodes` 和磁盘集合，并按 `selected_strategy` 动态验证
- [ ] Stage 2 不导出/挂载目标 RBD；Stage 5 只有在 `workload_storage_ready` 后才按策略执行 Guest 访问
- [ ] live 中 `qm status: running` 不单独满足 guest access gate；offline 在 Stage 5 以 RBD 导出、只读挂载和 Guest 根文件系统 Artifact 满足
- [ ] offline 不要求 Guest `runtime_running`，不创建 connection record、Live Session 或 `remote-server-live-response`
- [ ] TCG 仅尝试 1 次、最多 300 秒，并保存差异/日志后恢复配置和返回 Planner
- [ ] VMware `mcp-only` 不调用 vmrun/vmrest/本地控制命令，不在执行 Stage 修改 MCP 代码
- [ ] 所有工作目录属于 `allowed_write_roots`，空间预算不足时不改写到 C 盘
