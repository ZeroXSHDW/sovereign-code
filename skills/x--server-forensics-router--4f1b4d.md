---
name: server-forensics-router
description: 服务器取证总入口。根据服务器检材形态选择 rebuild-and-connect、remote-live、offline-image 或 hybrid-cluster 执行模式，覆盖服务器镜像、远程入口、完整服务器目录、混合材料和虚拟化导出场景。
---

# server-forensics-router

## Purpose

server-forensics-router 是服务器取证的总入口和模式路由器。接收来自 `forensic-router` 或 `forensic-autopilot` 的服务器材料，判断执行模式并生成下游路由方案。它只做模式判断和路由，不展开域分析。

本 skill 不替代：
- `forensic-autopilot`：总调度入口
- `forensic-router`：材料级路由器
- `file-triage`：文件初筛
- `large-artifact-strategy`：大文件策略
- `tool-router`：执行环境路由

## Use When

- `forensic-router` 识别出服务器镜像（E01/VHD/VMDK/qcow2/raw/dd/img）
- 检材包含完整服务器目录结构（Linux 根目录、Windows Server 目录）
- 题目提供远程服务器入口（SSH/WebUI/RDP/WinRM/DB 凭据）
- 检材包含混合服务器材料（镜像 + Web 源码 + 数据库 dump）
- 检材包含虚拟化导出（PVE/Proxmox 虚拟机配置和磁盘）
- 材料类型为"服务器相关"但模式不明确

## Do Not Use When

- 单一且明确的 `docker-compose.yml` 项目：由 `docker-container-forensics` 直接处理
- 单一且明确的数据库备份或 dump：由 `database-server-forensics` 直接处理
- 单一且明确的 Web 源码或日志：由 `webapp-server-forensics` 直接处理
- 纯固件/IoT 固件：返回 `forensic-router`，记录 `out-of-phase-scope`，不创建到未实现 Skill 的 Route Step 或 Handoff
- 纯加密容器（无服务器特征）：返回 `forensic-router`，记录 `out-of-phase-scope`，不创建到未实现 Skill 的 Route Step 或 Handoff
- 当 `large_artifact_mode` 被触发时：先调用 `large-artifact-strategy`，再回到本 router

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
  payload: {}                  # 无专项载荷
```

## Response Contract

遵循 `templates/response-envelope.schema.json`。

```yaml
schema_version: "1.0"
investigation_summary:
  current_assessment: string
  key_evidence: array
  excluded_routes: array
route_record:
  schema_version: "1.0"
  route_id: "route-<uuid>"
  triggered_skill: "server-forensics-router"
  route_basis: array
  mode_decision: rebuild-and-connect|remote-live|offline-image|hybrid-cluster|pending
  route_status: active
  route_plan:
    - route_step_id: "step-<uuid>"
      skill: string
      dependency_step_ids: []
      parallel_group: null
      status: pending
  handoffs:
    - handoff_id: "hof-<uuid>"
      route_id: "route-<uuid>"
      from_step_id: "step-<uuid>"
      to_step_id: "step-<uuid>"
      from: "server-forensics-router"
      to: string
      reason: string
      artifact_refs: []
      finding_refs: []
      visited_skills: ["server-forensics-router"]
      hop_count: 1
      status: pending
      priority: normal
      reentry_reason: null
      new_evidence_refs: []
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
  mode_decision: rebuild-and-connect|remote-live|offline-image|hybrid-cluster|pending
  target_bindings:
    - question_ref: string
      target_type: string
      target_ref: string
      expected_evidence_type: string
      dependency_step_ids: []
```

`target_bindings` 是 Response `payload` 中对题目、答案主体、证据类型和现有 Route Step 的绑定，不是 Route Step 的扩展字段。`target_type` 至少支持 `cluster`、`pve-node`、`guest-vm`、`web-application`、`database`，但保持开放字符串以兼容其他证据化主体；Route Step 仍只使用 `route_step_id`、`skill`、`dependency_step_ids`、`parallel_group` 和 `status`。

## Routing Workflow

### Step 1: Receive and Assess Material

从 `request.material_info` 和 `request.context` 获取：
- `artifact_refs`：已登记的制品引用（由 `file-triage` / `evidence-ledger` 预先登记）
- `material_type`：材料类型
- `triage_notes`：来自 `file-triage` 的分类结论
- `size_summary`：大小汇总（如有）

不执行任何文件系统操作。Router 只引用已有 `artifact_refs`，不创建或拆分任何派生制品。派生 Artifact 由 `file-triage`、`large-artifact-strategy`、`cluster-virtualization-forensics` 或 executor 创建。

**Ledger Event**: 产生 `finding` event，记录材料接收和初步评估。

### Step 2: Classify Server Material

根据材料特征归类为以下类型之一：

| 材料特征 | 分类 |
|---------|------|
| 磁盘/虚拟机镜像文件（E01/VHD/VMDK/qcow2/raw/dd/img） | server image |
| 题目直接提供 IP/端口/账号/密钥/服务入口 | remote server entry |
| 备份包/目录包含完整 Linux 或 Windows Server 结构 | complete server directory |
| 同时包含镜像 + 源码 + 数据库 dump 的混合检材 | mixed server artifacts |
| PVE/Proxmox 虚拟机配置和导出磁盘 | virtualization export |
| 无法明确归类的服务器特征材料 | uncertain server material |

分类依据记录到 `route_record.route_basis`，confidence 写入 finding。

### Step 3: Determine Execution Mode

根据材料分类选择执行模式：

| 分类 | 默认模式 | 条件 |
|------|---------|------|
| server image | `rebuild-and-connect` | 镜像完整、副本可创建、本地可仿真 |
| remote server entry | `remote-live` | 有远程入口和凭据 |
| complete server directory | `offline-image` 或 `rebuild-and-connect` | 目录完整且有服务配置时可重建 |
| mixed server artifacts | `offline-image` 或 `rebuild-and-connect` | 根据证据组合多个 domain skill；不默认使用 `hybrid-cluster` |
| virtualization export | `hybrid-cluster` | PVE/Proxmox 导出需要先处理存储层 |
| uncertain server material | `pending` | 证据不足时标记待定 |

**Windows Server 材料**：可以识别、选择当前可执行的 server mode，并路由证据支持的 Web、Database、Docker 等已实现子域；不得路由到 `linux-server-forensics`，也不得为缺失的 Windows OS 层消费者创建 Route Step 或 Handoff。Windows OS 层专项分析缺失时，记录带 Artifact 和 Ledger 引用的 scope gap、blocker 或 limitation Finding。

- 仍有当前 Skill 可继续执行时，`route_status=active`。
- 当前可执行分析全部完成且限制已记录时，可设置 `route_status=completed`。
- 用户核心目标必须依赖 Windows OS 层分析且无继续路径时，设置 `route_status=blocked`。
- 不得使用 `partial` 作为 `route_status`。

**hybrid-cluster 仅用于**：PVE/Proxmox、Ceph、多节点、多磁盘虚拟化拓扑、VM 磁盘映射，以及服务于虚拟化拓扑的 LVM/RAID/ZFS/btrfs。普通 Compose 项目或混合材料不归入此模式。

hybrid-cluster 必须把分析对象分为两个 evidence scope：

- **cluster-level**：PVE 宿主、Corosync、Ceph、Pool、RBD、Snapshot；
- **guest-level**：内层业务 VM、Linux、Web、应用和数据库。

PVE 宿主与内层 Guest 不得合并为同一服务器对象。每个问题或目标必须在 `payload.target_bindings` 中绑定 `question_ref`、`target_type`、`target_ref`、`expected_evidence_type` 和对应 Route Step 的 `dependency_step_ids`；Guest 目标必须依赖证明目标 RBD 或 Guest 文件系统可访问的步骤。

### Step 4: Construct Route Plan

根据模式构建 `route_record.route_plan`：

| 模式 | route_plan 步骤 |
|------|----------------|
| `rebuild-and-connect` | server-rebuild-planner → server-rebuild-executor → remote-server-live-response → domain skills |
| `remote-live` | remote-server-live-response → domain skills |
| `offline-image` | domain skills (linux/webapp/database/docker/cluster) |
| `hybrid-cluster` | cluster-virtualization-forensics → server-rebuild-planner → server-rebuild-executor → 按 Guest 访问方式进入 live 或 offline domain 分支 |
| `pending` | 按原因路由：`large_artifact_mode`→large-artifact-strategy；服务器属性不明或非常见结构→forensic-router/file-triage 基于新证据补充分流；缺少输入→mode_decision pending |

mixed server artifacts 根据证据分别构建串行或并行 `route_plan`，可同时包含 `offline-image` 域分析步骤和 `rebuild-and-connect` 重建步骤。

每个步骤使用 `route_step_id` 唯一标识，通过 `dependency_step_ids` 声明依赖。

hybrid-cluster 中每个箭头都必须由 `dependency_step_ids` 明确表达：Planner 依赖 cluster mapping，Executor 依赖 ready plan。Executor 根据 `workload_access_strategy.selected_strategy` 和实际证据激活一个后继分支：

- **live/rebuilt**：Executor → `remote-server-live-response` → Linux/Web/Database 等 domain steps；
- **offline mount**：Executor 成功挂载并产生 Guest 根文件系统 Artifact → Linux/Web/Database 等 offline domain steps，不创建 `remote-server-live-response`。

不得在 Planner 后绕过 Executor 直接进入 domain skill，也不得让 guest-level 目标绕过 `workload_storage_ready` / `guest_access_ready` 证据。未选中的条件 Route Step 使用 `skipped`，不另造 Route Step 字段。

**Ledger Event**: 产生 `state-transition` event，记录路由方案。

### Step 5: Prepare Handoffs

为每个下游 skill 创建 handoff 记录：
- `from_step_id`：当前步骤 ID
- `to_step_id`：目标步骤 ID
- `visited_skills`：记录已访问的 skill 列表
- `hop_count`：当前跳数

**防循环规则**：同一 `route_id` + 同一 evidence scope 不得重复进入同一 Skill，除非新证据明确要求重新分析（记录 `reentry_reason` 和 `new_evidence_refs`）。

`hop_count` 上限由 `routing_policy.max_hops` 控制（默认 16）。

**Ledger Event**: 产生 `handoff` event，引用 `handoff_id`、`route_id`、`artifact_refs`。

## Mode Decision Rules

### rebuild-and-connect

**条件**：
- 有磁盘镜像、VM 配置、容器镜像或 compose 项目
- 本地有或可以创建副本
- 需要观察服务运行态（进程、端口、登录行为）

**输出**：`route_plan` 指向 `server-rebuild-planner`

### remote-live

**条件**：
- 题目直接提供远程入口（IP/端口/凭据/SSH key/WebUI/DB 凭据）
- 无本地镜像或镜像不足以复现

**输出**：`route_plan` 指向 `remote-server-live-response`

### offline-image

**条件**：
- 镜像损坏、无法启动或启动会污染证据
- 只有日志包、源码包、备份包、database dump

**输出**：`route_plan` 指向相应的 domain skill

### hybrid-cluster

**条件（以下任一）**：
- PVE/Proxmox 集群或导出
- Ceph/RBD/OSD 存储
- 多节点服务器拓扑
- 多磁盘虚拟化拓扑需要磁盘映射
- 服务于虚拟化拓扑的 LVM/RAID/ZFS/btrfs

**不包括**：普通 Compose 项目、混合服务器材料（无虚拟化存储层）。

**输出**：`route_plan` 先指向 `cluster-virtualization-forensics` 做存储层分析，再回到重建或域分析。

共同前缀固定为：

`cluster-virtualization-forensics` → `server-rebuild-planner` → `server-rebuild-executor`。

随后按 Planner 的 `workload_access_strategy.selected_strategy` 和 Executor 的 `guest_access_mode` 分支：

- `live`（如 `nested-launch`、`rbd-separate-vmware` 或成功的 `bounded-tcg`）：→ `remote-server-live-response` → 证据支持的 domain skills；
- `offline`（`rbd-offline-mount`）：→ Guest 根文件系统 Artifact → `linux-server-forensics` / `webapp-server-forensics` / `database-server-forensics` 等 offline domain skills。

offline mount 路线不得强制创建 `remote-server-live-response` 或伪造 Live Session。

当 `required_nodes`、required cluster members、`required_system_disks` 或 `required_osd_disks` 缺失：

- 无安全继续路径时设置 `route_status: blocked` 和受影响 Route Step `status: blocked`；
- 仍可完成有限离线分析时保持 `route_status: active`，把不可执行的 Route Step 标为 `blocked|skipped`，并继续证据支持的 offline Route Step；
- 执行开始后的局部/阻断状态只写入 Executor 的 `rebuild-status.overall_status: partial|blocked` 及对应 Stage，不另建 payload 状态；无论哪种情况都不得声称集群恢复完成。

### pending

**条件**：
- 证据不足以确定模式
- 当 `large_artifact_mode` 被触发且尚未完成策略分析
- 服务器属性仍不明确
- 发现非常见结构

**统一规则**：`large_artifact_mode` 未处理 → `mode_decision: pending` → 进入 `large-artifact-strategy` → 完成后回到 `server-forensics-router`。

**输出（按原因区分）**：
- `large_artifact_mode` → `large-artifact-strategy`（完成后回到本 router）
- 服务器属性不明 → `forensic-router` / `file-triage` 补充分流
- 非常见结构 → `forensic-router` / `file-triage` 进行一次有新证据依据的重新分类；重新分类后仍无当前消费者时记录 blocker，不创建到未实现 Skill 的 Handoff
- 缺少必要输入 → `mode_decision: pending`，标记下一步动作为收集信息

Router reentry 必须带非空 `new_evidence_refs`。相同 `route_id` 和 evidence scope 在没有新证据时不得在 `server-forensics-router`、`forensic-router` 与 `file-triage` 之间循环。

## Handoff Rules

| 下游 Skill | 交接条件 |
|-----------|---------|
| `server-rebuild-planner` | 模式为 `rebuild-and-connect` 且检材可重建，或 hybrid-cluster 已完成 cluster mapping |
| `server-rebuild-executor` | Planner 已输出 ready plan；hybrid-cluster 中必须位于 Planner 之后 |
| `remote-server-live-response` | 模式为 `remote-live`、已有可用入口，或 Executor 的 `guest_access_mode: live` 已通过运行/访问门禁 |
| `cluster-virtualization-forensics` | 模式为 `hybrid-cluster`（PVE/Ceph/多节点/多磁盘虚拟化拓扑） |
| `linux-server-forensics` | 离线分析 Linux 系统、live-response 之后，或 offline mount 产生 Guest 根文件系统 Artifact 后进入 |
| `webapp-server-forensics` | 离线分析 Web 源码、live-response 之后，或 offline Guest Artifact 可用后进入 |
| `database-server-forensics` | 离线分析数据库、live-response 之后，或 offline Guest Artifact 可用后进入 |
| `docker-container-forensics` | 发现 compose/Dockerfile（含多服务 Compose，后续 handoff 到 webapp/database） |
| `large-artifact-strategy` | 当 `large_artifact_mode` 被触发且未完成策略分析 |
| `forensic-router` / `file-triage` | 服务器属性不明时补充分流 |

## Evidence Requirements

| Event Type | When | LED-Event Fields |
|-----------|------|-----------------|
| `finding` | 材料分类和模式决策时 | `finding`, `confidence` |
| `state-transition` | 路由方案确定时 | `stage`, `next_action`, `route_id` |
| `handoff` | 准备交接时 | `handoff_id`, `route_id`, `artifact_refs` |

Handoff 结构细节（`from_step_id`、`to_step_id`）保存在 `route_record.handoffs`，Ledger Event 只引用 `handoff_id`、`route_id`、`artifact_refs`。

所有 ledger event 由 `evidence-ledger` 负责持久化。

## Investigation Summary

```markdown
## Investigation Summary

**Current Assessment**: <服务器形态 + 执行模式>

**Key Evidence**:
1. <证据1，含路径/文件/配置/入口>
2. <证据2>
3. <证据3，可选>

**Excluded Routes** (if any): <被排除的路线及原因>

**Route Plan**:
- <下一步1>（从 route_record.route_plan 渲染）
- <下一步2，如有并行>
```

Route Plan 必须由 `route_record.route_plan` 渲染，不得独立维护。

## Execution Gate

本项目默认在已批准环境中工作。`execution_gate` 仅在以下情况触发：
- 操作超出已批准的 rebuild plan
- 操作会修改原始检材
- 操作会改变既定网络模式
- 需要重新规划（超出当前 `recovery_policy` 范围）

## Stop Conditions

- 检材无法读取且无法获得任何 triage_notes 或元数据
- 多条候选路径互斥，继续执行会造成无效分析
- 当 `large_artifact_mode` 被触发且 `large-artifact-strategy` 尚未完成（缺少必要的 offset map）
- 非 Phase 2 材料已完成一次有新证据依据的重新分类，但仍没有当前已实现消费者

> `objective_status: unknown` 不是停止条件。Router 仍可判断服务器材料类型、可用执行模式，构建中立 Route Plan。具体目标优先级留作后续补充。
>
> Unknown material type is not a stop condition. Route to `forensic-router` for re-triage or flag as `pending`.

## Quality Checklist

- [ ] `route_record` 使用 `route_step_id` 而非 skill 名作为步骤标识
- [ ] `route_plan` 中每个 step 通过 `dependency_step_ids` 声明依赖
- [ ] Handoff 包含 `from_step_id`、`to_step_id`、`visited_skills`、`hop_count`
- [ ] Investigation Summary 的 Route Plan 从 `route_record.route_plan` 渲染
- [ ] 所有 ledger event 写入 `ledger_events` 数组
- [ ] 不生成 `battle summary`、`competition-autopilot`、`triage-files`、`server-answer-gate` 等旧引用
- [ ] `execution_gate` 仅在超出批准范围时设为 `required: true`
- [ ] 路由依据基于文件结构和内容，不凭目录名猜测
- [ ] 当 `large_artifact_mode` 被触发时 → `mode_decision: pending` → `large-artifact-strategy` → 完成后回到 router
- [ ] mixed server artifacts 不默认映射到 `hybrid-cluster`
- [ ] hybrid-cluster 的共同前缀为 cluster → planner → executor；live 分支经 live-response，offline mount 分支直接进入 offline domain skills
- [ ] cluster-level 与 guest-level 分组明确，每个目标绑定 `question_ref`、`target_type`、`target_ref`、`expected_evidence_type`、`dependency_step_ids`
- [ ] Guest 目标等待 RBD 或 Guest 文件系统实际可访问
- [ ] required members/disks 缺失时只更新 Route Step 与 Executor rebuild-status，不另建 payload 恢复状态
- [ ] offline mount 路线不创建 `remote-server-live-response` 或 Live Session
- [ ] Windows Server 材料不路由到 `linux-server-forensics`
- [ ] Windows OS 层缺口只记录 scope gap/blocker/limitation，不创建到未实现 Skill 的 Handoff
- [ ] 非 Phase 2 材料返回 forensic-router 并记录 out-of-phase-scope，不创建未实现目标
- [ ] `pending` 按原因区分路由目标
- [ ] Router reentry 必须有新证据，禁止无新证据循环

## Notes

- server-forensics-router 不执行分析，只做模式判断和路由
- 服务器模式选择（rebuild/remote/offline/hybrid）由本 skill 决定
- 单一明确的 compose/DB/Web 材料由 `forensic-router` 直接路由，不经过本 skill
- 本 skill 不保留旧引用（`competition-autopilot`、`triage-files`、`server-answer-gate`、`battle summary`、`E:\CompetitionTools`）
- Windows Server 材料可以执行通用路由和已实现子域分析；Windows OS 层缺口必须证据化，不创建伪造 Handoff
