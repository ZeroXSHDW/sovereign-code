---
name: forensic-autopilot
description: 总调度入口。接收用户输入（检材、目标），自动编排完整的取证分析链路：路由、分流、专项分析、时间线、校验、报告。只在高风险动作前询问用户。
---

# forensic-autopilot

## Purpose

forensic-autopilot 是取证工作流的总调度入口。用户只需提供检材和目标，autopilot 自动完成路径规划、工具选择、初筛、专项分析、证据记录和答案输出。

本 skill 保留通用取证调度框架。Phase 3 的 `uncommon-media-triage`、`proprietary-format-recovery`、`firmware-iot-forensics`、`nas-raid-encrypted-storage` 与 `malware-forensics` 均已实现。

## Use When

- 用户提供检材（文件、镜像、目录、远程入口）和目标（找什么、回答什么）
- 用户说"分析这个"、"看看这个镜像"、"帮我查一下"
- 用户提供目标不完整时，先使用当前通用取证链做中立、只读的证据化处理；没有已实现消费者的专项需求按 `no-compatible-skill` 处理

## Inputs

| Input | Required | Description |
|-------|----------|-------------|
| `material` | Yes | 检材路径或描述（文件、目录、压缩包、镜像、远程入口） |
| `objective` | Recommended | 目标（找什么、回答什么）。若可从题面推断则不追问 |

## Outputs

| Output | Description |
|--------|-------------|
| `evidence-ledger` | 完整的证据记录 |
| `findings` | 结论列表，每条绑定证据 |
| `report` | 结构化报告（通过 report-writer 生成） |

## Workflow

### Step 1: Intake

- 接收检材和目标
- 确认检材存在（文件存在、远程可达）
- 推断目标（如可从题面/上下文推断）
- 初始化当前 Run 和 Route/Stage 状态；仅当被调用 Skill 的现有契约声明 Response Envelope 时才初始化并验证 Envelope。Start 或任何必需状态初始化失败时立即留证并阻断，不得手工伪造 `running` 状态或 Response Envelope 后继续

**Evidence**: 记录检材路径、类型、大小、mtime

### Step 2: Tool Precheck

- 调用 `tool-router` 检查执行环境可用性（Windows/WSL/Docker/VMware/QEMU）
- 确认所需工具已安装、路径可达
- 建立路径映射规则（如需要）
- 工具维护与案件取证执行分开记录；发现 `tooling_defect` 时停止受影响执行路径，不在案件运行中边修工具边继续

**Evidence**: 记录环境检查结果

### Step 3: File Triage

- 调用 `file-triage` 做只读初筛：文件识别、hash、分类
- 如检材 >= 1GB，调用 `large-artifact-strategy`
- 产出 `material_type`、`hash`、`triage_notes`；存在结构候选时同时产出 bounded `candidate_regions` 和相关采样 Evidence
- 记录 triage 结论到 evidence-ledger

**Evidence**: 记录文件类型、hash、triage 分类结果

### Step 4: Route

- 调用 `forensic-router`，基于 Step 3 的 `triage_notes` 做最终路径决策
- 判断检材应进入当前已实现的 Server、领域分析、`uncommon-media-triage`、`proprietary-format-recovery`、`firmware-iot-forensics`、`nas-raid-encrypted-storage` 或 `malware-forensics` 路径，或返回 `no-compatible-skill`
- 只有 Router 通过对应输入完整性检查并返回 Phase 3 消费者决策时，才允许调用该 Skill
- 分配并行路径（如需要）
- `route_decision: no-compatible-skill` 表示当前仓库没有兼容消费者；它不是 Route Record、Route Step、Handoff 或 execution gate 的状态值
- 五个 Phase 3 消费者均已实现；malware 仍需满足有效样本/区域加明确分析目标或独立可疑上下文的 Router 门槛

**Evidence**: 记录路由决策和依据

### Step 5: Domain Analysis

- 根据 forensic-router 的路由结果，进入对应的专项 skill：
  - 服务器镜像、远程服务器入口、完整服务器目录、混合服务器材料、虚拟化导出和模式不明确的服务器材料 → `server-forensics-router`
  - 单一明确的 Web、Database 或 Docker 静态材料 → forensic-router 选定的已实现领域 Skill
  - forensic-router 返回 `uncommon-media-triage` → 调用 `uncommon-media-triage`
  - forensic-router 返回 `proprietary-format-recovery` → 调用 `proprietary-format-recovery`
  - forensic-router 返回 `firmware-iot-forensics` → 调用 `firmware-iot-forensics`
  - forensic-router 返回 `nas-raid-encrypted-storage` → 调用 `nas-raid-encrypted-storage`
  - forensic-router 返回 `malware-forensics` → 调用 `malware-forensics`
- 调用 Phase 3 消费者时，原样传递 Router 批准的 Request payload 和包含当前 Route Record 的 Route context；不得重新构造、删减、重命名或丢弃字段
- 专项判断阈值、工具选择和 limits 只由 `forensic-router` 与对应领域 Skill 维护；autopilot 不重复判断、不生成或扩展候选，也不改变 limits 或动态范围
- 当前仓库没有兼容消费者时，保留 Artifact、分类证据和限制说明，不调用不存在的领域 Skill
- 多条路径可并行
- 所有目标相关 domain Route Step 完成并具有证据前，不得把 Route、Run 或报告标记为“任务完成”

**Evidence**: 每个专项 skill 写入自己的 findings

### Step 5a: No Compatible Skill

当 `forensic-router.route_decision` 为 `no-compatible-skill`：

1. 不重复路由，不进入 Timeline，不创建到不存在 Skill 的 Route Step 或 Handoff。
2. 记录带 Artifact 和 Ledger Event 引用的 blocker 或 scope-limitation Finding，说明当前仓库不支持该来源或分析目标。
3. 将限制和现有证据交给 `answer-gate`；校验后允许 `report-writer` 输出限制报告。
4. 不把 unsupported source 描述为已完成分析，也不把 `no-compatible-skill` 写入 `route_status`、Route Step status、Handoff status 或 `execution_gate`。

### Step 5b: Bounded Uncommon Re-entry

`uncommon-media-triage` 需要 Router 重评时，只允许一次从 uncommon 发出的单向 `uncommon-media-triage` → `forensic-router` bounded re-entry：

1. uncommon 必须产生新的 Artifact 或 Finding。
2. Handoff 的 `new_evidence_refs` 必须非空，并且每个引用都指向 uncommon 本轮产生的新 Ledger Event。
3. `reentry_reason` 必须说明新 Evidence 如何改变候选路线。
4. `visited_skills`、`hop_count` 和 `routing_policy.max_hops` 必须合法。
5. 同一 route 和 evidence scope 最多执行一次 uncommon → Router re-entry。
6. 没有新 Evidence 时禁止 re-entry。
7. Router 重评时 `visited_skills` 已包含 uncommon，因此不得再次进入 uncommon；仍无兼容消费者时进入 Step 5a，由 Answer Gate 校验范围限制并生成限制报告。

不得形成 `forensic-router` → uncommon → Router → uncommon 的循环。

### Step 5c: Bounded Proprietary Re-entry

`proprietary-format-recovery` 默认返回 autopilot。没有新消费者时直接进入 Answer Gate；只有本轮产生新 Artifact 或 Finding 时，才允许最多一次 proprietary → Router re-entry：

1. `reentry_reason` 非空，说明新 Evidence 如何改变消费者候选。
2. `new_evidence_refs` 非空，每项都指向 proprietary 本轮新 Ledger Event。
3. Handoff 包含本轮新 Ledger Event，以及合法 `hop_count` 和 `routing_policy.max_hops`。
4. Router 重评后不得再次选择 `uncommon-media-triage` 或 `proprietary-format-recovery`。
5. 没有其他当前可执行消费者时返回 autopilot，不重复路由。

不得形成 uncommon → Router → proprietary → Router → uncommon，也不得形成 proprietary → Router → proprietary。autopilot 不自行改变这些消费者决策。

### Step 5d: Bounded Firmware Re-entry

`firmware-iot-forensics` 默认返回 autopilot。没有新消费者时直接进入 Answer Gate；只有 firmware 本轮产生新 Artifact 或 Finding 时，才允许最多一次 firmware → Router re-entry：

1. `reentry_reason` 非空，说明新 Evidence 如何改变消费者候选。
2. `new_evidence_refs` 非空，每项都指向 firmware 本轮新 Ledger Event。
3. Handoff 包含本轮新 Ledger Event，以及合法 `hop_count` 和 `routing_policy.max_hops`。
4. Router 重评不得再次选择同一 route 和 evidence scope 的 `visited_skills` 中已有 Skill。
5. 只有 firmware 实际提取独立存储 Artifact 且 Router 通过 storage input gate 时，才可进入 storage；不得由 autopilot 自行判断。
6. firmware 的 malware candidate 只有通过 Router 的 malware input gate 后才可进入；autopilot 不把普通 firmware 组件转为样本。
7. 没有其他当前可执行消费者时返回 autopilot，不重复路由。

不得形成 proprietary → Router → firmware → Router → proprietary、firmware → Router → firmware，或 uncommon → Router → firmware → Router → uncommon。autopilot 不自行改变这些消费者决策。

### Step 5e: Bounded Storage Re-entry

`nas-raid-encrypted-storage` 默认返回 autopilot。没有新消费者时直接进入 Answer Gate；只有 storage 本轮产生新 Artifact 或 Finding 且出现新的可执行消费者候选时，才允许最多一次 storage → Router re-entry：

1. `reentry_reason` 非空，说明新 Evidence 如何改变消费者候选。
2. `new_evidence_refs` 非空，每项都指向 storage 本轮新 Ledger Event。
3. Handoff 包含本轮新 Artifact 或 Finding、本轮新 Ledger Event，以及合法 `hop_count` 和 `routing_policy.max_hops`。
4. Router 重评不得再次选择同一 route 和 evidence scope 的 `visited_skills` 中已有 Skill。
5. 恢复卷只在新 Evidence 支持服务器上下文时进入 `server-forensics-router`；不得把所有恢复卷默认送入服务器链。
6. 没有其他当前可执行消费者时返回 autopilot，不重复路由。

不得形成 storage → Router → storage、storage → Router → proprietary → Router → storage、uncommon → Router → storage → Router → uncommon、proprietary → Router → storage → Router → proprietary，或 firmware → Router → storage → Router → firmware。autopilot 不自行改变这些消费者决策。

### Step 5f: Bounded Malware Re-entry

`malware-forensics` 默认返回 autopilot。没有新消费者时直接进入 Answer Gate；只有本轮产生新 Artifact 或 Finding、新 Ledger Event 和新的可执行消费者候选时，才允许最多一次 malware → Router re-entry：

1. `reentry_reason` 和 `new_evidence_refs` 非空，且引用本轮新 Evidence。
2. Handoff 包含本轮新 Artifact 或 Finding、新 Ledger Event，以及合法 hop。
3. Router 不得重选同一 route/evidence scope 的已访问 Skill；原上游已访问时不得返回该消费者。
4. 没有其他当前可执行消费者时返回 autopilot，不重复路由。

不得形成 malware → Router → malware，或 proprietary、firmware、storage、uncommon → Router → malware → Router → 原上游。autopilot 不执行样本、不创建沙箱，也不维护动态分析条件。

### Step 6: Timeline

- 仅当已实现的领域 Skill 产生兼容 `timeline_candidates` 且需要多源关联时，调用 `timeline-reconstruction`
- PCAP/网络流量和 `no-compatible-skill` 不进入当前 Timeline

**Evidence**: 记录合并后的时间线

### Step 7: Validate

- 调用 `answer-gate` 做五步校验
- 对已进入兼容领域 Skill 且存在明确新证据路径的结果，校验不通过时返回 Step 5 补充证据
- 对 `no-compatible-skill`，Answer Gate 只校验证据引用、范围限制和未完成声明；无兼容消费者不是重新路由理由，不返回 Step 5，保留 limitation 并进入 Step 8 输出限制报告
- Answer Gate 的 verdict 不是 `pass` 时，不得输出最终答案；只输出补证 Route、正式 blocker 或经校验的限制报告

**Evidence**: 记录校验结果

### Step 8: Report

- 仅在 Answer Gate 通过，或 `no-compatible-skill` 的限制声明已经 Answer Gate 校验后，调用 `report-writer` 生成结构化报告
- 输出 findings、evidence、timeline、conclusions

**Evidence**: 报告本身即为最终产物

## Progress and Failure Convergence

Autopilot 必须以 Evidence Ledger 的新增事实衡量进度，而不是以动作数量或工具输出长度衡量：

1. 同一 `operation + error_class` 最多尝试 2 次；下游 `recovery_policy` 给出更低上限时使用更低值。
2. 连续 3 个动作没有产生新的 Artifact、Finding、Ledger Event 支持的事实或明确 negative finding 时，停止当前路线并执行 evidence-backed route reassessment。
3. 同一 Skill 在同一 `route_id + evidence_scope` 最多重入 1 次；需要超过 1 次时，必须由非空 `new_evidence_refs` 证明出现明确新证据，并按 Route Record 填写 `reentry_reason`。
4. retry、fallback 和 replan 必须保留原失败 Ledger Event、stdout/stderr、attempt、错误分类和派生 Artifact；不得用新结果覆盖失败历史。
5. 没有安全继续路径时，创建符合现有 Route Record 的 Handoff，或记录带 Artifact/Ledger 引用的 blocker Finding；不得盲目重试。

### Stage Completion Gate

阶段完成门必须先读取被调用 Skill 或 Autopilot 内部阶段的现有输出契约，不得把 Response Envelope 强加给未声明该契约的步骤：

- 声明使用 `templates/response-envelope.schema.json` 的 Skill，只有输出可通过该 Schema 验证的 Response Envelope 才能完成；
- Autopilot 内部阶段以及未采用 Response Envelope 的 Skill，必须满足其现有输出契约，并保留相应 Ledger Event 与 Route/Stage/Run 状态记录；
- 两类阶段都必须具有至少一个可解析的 Ledger Event 引用，以及新 Finding、Artifact，或明确记录且有证据支持的 negative finding；
- 不得为了通过完成门而伪造、补写或推断一个并非该 Skill 契约要求的 Response Envelope。

缺少适用契约所要求的任一项时保持与事实一致的非 completed 合法状态：Route Step 使用 `pending|running|blocked|failed|skipped`，rebuild Stage 使用 `pending|in_progress|retrying|blocked|failed|skipped|rolled_back`。不得仅凭叙述性总结完成阶段；Route Step 继续只使用 `route_step_id`、`skill`、`dependency_step_ids`、`parallel_group` 和 `status`。

### Expensive Operation Gate

大文件导出、磁盘转换或服务器重建前，必须由现有 Route/Stage 与 Ledger 证明：

- 目标后端及必需能力已预检；
- 源/输出逻辑大小、实际或预计占用、峰值空间和目标盘可用空间已评估；
- 写入目录属于 `allowed_write_roots`。

任一条件缺失或空间不足时阻断；禁止临时改写到未批准目录或 C 盘。

## Evidence Requirements

| Field | When to Record |
|-------|---------------|
| `artifact` | 每个被检查的文件/服务/容器 |
| `source` | 检材来源（磁盘镜像路径、远程主机、容器 ID） |
| `hash` | 检材和关键文件的完整性 hash |
| `command` | 每次工具调用 |
| `finding` | 每个发现 |
| `confidence` | 每个 finding 的置信度 |
| `next_action` | 下一步计划 |

进度判断必须引用新 Ledger Event；“无新证据”也要以 negative finding 或状态转换事件明确记录，不能只在会话文字中声明。

## Handoff

**Passes to**: `tool-router` → `file-triage` → `large-artifact-strategy` (if triggered) → `forensic-router` → domain skills 或五个 Phase 3 消费者 → `answer-gate` → `report-writer`
**Data available**: evidence-ledger 中的所有记录；调用 Phase 3 消费者时还包括 Router 批准的原始 Request payload 和当前 Route Record context

## Stop Conditions

- 检材类型未知本身不是停止条件：继续只读 triage，并把 Artifact、文件头、采样结果和分类证据交给 `forensic-router`；无兼容消费者时使用 `route_decision: no-compatible-skill`
- 不因 unknown material 自动追问用户；只有继续处理必然越出授权范围、破坏证据，或无法在互斥高风险动作间安全选择时才停止
- 连续 3 个动作无新证据时，更新 Investigation Summary 和 Route Record 并重新评估路线；同类错误达到 2 次或 Skill 重入达到上限时不得继续原循环
- 需要修改原始检材、改写运行中系统状态，或执行不在当前任务范围内的外部网络操作时停止并请求授权
- Run Start、必需状态文件初始化，或声明使用 Response Envelope 的 Skill 创建/验证 Envelope 失败，且无法在既有契约内恢复

## Notes

- 本 skill 是抽象调度框架，不维护领域专项阈值
- Phase 3 五个模块均已实现；malware 只执行 Router 返回的 evidence-backed 决策
- 当前没有兼容消费者时按 `no-compatible-skill` 记录证据和范围限制
- 大体积检材（>= 1GB）必须先走 large-artifact-strategy，不默认全量扫描
- 工具修复属于独立维护活动；维护记录不得混入案件执行 Stage，维护完成后必须开启新的能力预检与执行尝试
