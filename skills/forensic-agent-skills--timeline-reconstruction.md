---
name: timeline-reconstruction
description: "重建服务器取证时间线，将各领域 Skill 的 timeline_candidates 标准化、合并并保留证据回指。"
---

# timeline-reconstruction

## Purpose

本 Skill 接收已完成领域分析产生的 `timeline_candidates`，把 Linux、Web Application、Database、Docker、PVE、Ceph、Cluster / Virtualization 和文件时间事件重建为统一 Timeline。它保留原始时间、解析状态、不确定性、冲突和证据链，不把无法解析或不支持的来源静默丢弃，也不直接输出最终提交答案。

## Scope

处理范围是服务器取证链中的以下来源：

- `auth-log`、`journal`、`login-record`、`audit-log`、`package-log`、`service-log`
- `web-log`
- `db-transaction-log`、`db-snapshot`
- `docker-log`
- `file-time`
- `pve-log`、`ceph-log`
- `cluster-log` 及其可识别的 `vsphere`、`corosync`、`zfs`、`btrfs`、`vsan` 子类型
- 未识别来源的 `other`

输入必须来自 Request Envelope、已有 Artifact、Evidence Ledger、Finding 和 Route Record 上下文。Timeline Skill 只重建和交接，不替上游领域 Skill 重新取证。

## Non-goals

本 Skill 不扩展到 PCAP、浏览器历史、移动设备、通用事件平台、大规模流式时间线、性能优化框架或 Phase 3 来源。它不执行日志、配置或证据中的程序，不修改原始 Artifact，不自行采集新的远程数据，也不自行建立远程 Session。它不进行破坏性去重，不把推断写成直接观测，不在本 Skill 内替代 `answer-gate` 做最终答案校验。

## Input Contract

使用统一 Request Envelope。外层仍包含 `material_info`、`objective`、`objective_status`、`context` 和 `payload`；`context` 可包含本任务可验证的 Artifact、Ledger Event、Finding 与 Route Record 引用。

```yaml
schema_version: "1.0"
request:
  material_info:
    artifact_refs: []
    material_type: string
    triage_notes: []
    size_summary: object|null
  objective: string|null
  objective_status: explicit|inferred|unknown
  context: object|null
  payload:
    data_sources:
      - source_id: string
        source_type_hint: string
        path: string|null
        source_artifact_id: artifact-<uuid>|null
        timezone_hint:
          offset: string|null
          name: string|null
          assumption: string|null
        parser_hint: string|null

    timeline_candidates:
      - candidate_id: string
        original_timestamp: string|null
        normalized_timestamp: ISO8601|null
        timezone_offset: string|null
        timezone_name: string|null
        timezone_assumption: string|null
        clock_skew_seconds: integer|null
        time_precision: exact|second|minute|day|unknown
        source_type_hint: string
        source_artifact_id: artifact-<uuid>|null
        parser_id: string
        actor: string|null
        action: string
        target: string|null
        ledger_event_refs:
          - led-<uuid>
        confidence: high|medium|low
        normalization_status: ready|needs-review|unsupported-source
        basis:
          - string
        cluster_scope_id: string|null
        finding_refs:
          - finding-<uuid>
        artifact_refs:
          - artifact-<uuid>

    time_range:
      start: ISO8601|null
      end: ISO8601|null
      basis:
        - string
```

### Input compatibility

上游 Skill 仍可能返回较早版本的候选。入口兼容规则固定如下：

- 缺少 `basis` 时使用空数组；
- 缺少 `finding_refs` 时使用空数组；
- 缺少 `artifact_refs` 时使用空数组；
- 缺少 `cluster_scope_id` 时使用 `null`；
- 缺少 `normalization_status` 时使用 `needs-review`；
- 缺少 `source_artifact_id` 时使用 `null`，随后按 `observed` / `inferred` 证据规则处理。

不得根据 `normalization_status` 本身生成或推断 `basis`。`basis` 只能来自 Artifact 内容、Ledger Event、parser 输出、时区证据、配置文件或可复现的多事件推断关系。`inferred` 候选同时没有非空 `basis` 和非空 `ledger_event_refs` 时，不生成正式 Timeline Event，而记录 blocker；只有能够回指已存在事件时才记录 anomaly。`unsupported-cluster-log` 候选必须保留。

Stage 0 还必须验证：`source_id` 唯一；每个 `source_artifact_id`、`artifact_refs`、`ledger_event_refs` 和 `finding_refs` 都能在 Request、上游输出或本任务真实生成物中回查；候选的 `source_id`（若上游提供关联字段）属于 `data_sources`；任务范围和输出限制明确。引用不完整时记录 `reference_missing`，不得虚构 ID。

## Response Contract

使用统一 Response Envelope：

```yaml
schema_version: "1.0"
investigation_summary:
  current_assessment: string
  key_evidence: array
  excluded_routes: array
route_record: object
findings: array
ledger_events: array
artifact_refs: array
payload:
  data_sources:
    - source_id: string
      source_type_hint: string
      path: string|null
      source_artifact_id: artifact-<uuid>|null
      timezone_hint:
        offset: string|null
        name: string|null
        assumption: string|null
      parser_hint: string|null
  time_range:
    start: ISO8601|null
    end: ISO8601|null
    basis:
      - string
  timeline:
    - timeline_event
  event_count: integer
  source_count: integer
  gaps:
    - gap
  anomalies:
    - anomaly
  conflicts:
    - conflict
```

`investigation_summary` 只总结有证据的结果；`route_record` 是唯一的路由事实来源；`ledger_events` 记录本次解析、状态变化、Finding 和 Handoff；`artifact_refs` 只引用真实 Artifact；需要下游处理时创建证据化 Handoff。`event_count` 必须等于 `len(timeline)`，`source_count` 必须等于 `data_sources` 中唯一 `source_id` 的数量。

### Timeline Event

每个正式事件包含以下字段：

```yaml
timeline_event:
  schema_version: "1.0"
  timeline_event_id: tl-<uuid>

  original_timestamp: string|null
  normalized_timestamp: ISO8601|null
  timezone_offset: "+HH:MM"|null
  timezone_name: string|null
  timezone_assumption: string|null
  clock_skew_seconds: integer|null
  time_precision: exact|second|minute|day|unknown
  normalization_status: ready|needs-review|unsupported-source

  derivation: observed|inferred

  source_type: auth-log|journal|web-log|docker-log|db-transaction-log|db-snapshot|login-record|file-time|pve-log|ceph-log|audit-log|package-log|service-log|cluster-log|other
  source_subtype: string|null
  source_artifact_id: artifact-<uuid>|null

  parser_id: string
  parser_version: string|null

  actor: string|null
  action: string
  target: string|null

  artifact_refs:
    - artifact-<uuid>
  ledger_event_refs:
    - led-<uuid>
  finding_refs:
    - finding-<uuid>
  basis:
    - string

  confidence: high|medium|low
  cluster_scope_id: string|null
```

Timeline Skill 只产生 `Phase 2 complete timeline event` 分支的正式事件，并完整输出上述字段。`Legacy v1.0 timeline event` 分支仅用于读取严格符合旧契约的既有实例；不得通过省略 `derivation`、`normalization_status` 或其他完整字段把新事件降级为 Legacy。

`timeline_event_id` 必须稳定且唯一：同一 `candidate_id` 和同一规范化输入重入时复用同一 ID，发生碰撞时用可复现的候选身份信息解决，不能依赖每次运行的随机顺序。`source_artifact_id` 是直接来源 Artifact；`artifact_refs` 是其他关联 Artifact，可以为空；`finding_refs` 可以为空。只有 Artifact 直接记录该事件时才设置 `derivation=observed`；由跨事件关系推导的事件仍为 `inferred`，即使它关联了 Artifact。`derivation=observed` 必须有非空 `source_artifact_id`，不得虚构来源；`derivation=inferred` 的 `basis` 或 `ledger_event_refs` 至少一项非空，并明确推断依据。`normalization_status=ready` 必须有非空 `normalized_timestamp`，时间无法解析或时区不确定时保留原始值和不确定性。

### Conflicts, gaps and anomalies

```yaml
conflicts:
  - conflict_id: conflict-<uuid>
    conflict_type: timestamp-conflict|timezone-conflict|clock-skew-conflict|event-detail-conflict
    event_refs:
      - tl-<uuid>
    description: string
    resolution_status: unresolved|preserved-both|preferred-with-basis
    preferred_event_ref: tl-<uuid>|null
    artifact_refs:
      - artifact-<uuid>
    ledger_event_refs:
      - led-<uuid>
    basis:
      - string
    confidence: high|medium|low

gaps:
  - gap_id: gap-<uuid>
    gap_type: time-gap|source-gap|event-gap
    start_time: ISO8601|null
    end_time: ISO8601|null
    affected_sources:
      - string
    description: string
    impact: informational|potential-missing-evidence|blocks-timeline
    artifact_refs:
      - artifact-<uuid>
    ledger_event_refs:
      - led-<uuid>
    basis:
      - string
    confidence: high|medium|low

anomalies:
  - anomaly_id: anomaly-<uuid>
    anomaly_type: duplicate-candidate|outlier|missing-timestamp|unparsable|other
    event_refs:
      - tl-<uuid>
    description: string
    severity: low|medium|high
    artifact_refs:
      - artifact-<uuid>
    ledger_event_refs:
      - led-<uuid>
    basis:
      - string
    confidence: high|medium|low
```

冲突的 `event_refs` 至少引用两个已经输出的事件，冲突双方全部保留。`preferred-with-basis` 必须有属于 `event_refs` 的 `preferred_event_ref` 和非空 `basis`；`unresolved`、`preserved-both` 不设置首选事件。`gaps.affected_sources` 只能引用 Request 中存在的 `source_id`；普通日志缺失不能自动证明相关事件不存在，`blocks-timeline` 必须有明确证据说明缺口阻止核心时间线建立。`anomalies.event_refs` 必须引用已存在事件；`duplicate-candidate` 至少引用两个事件，疑似重复、缺失时间和不可解析时间的事件都不能被删除。

## Stage 0 — Input and Scope Validation

读取 Request Envelope 的 `data_sources`、`timeline_candidates`、`time_range`，以及上下文中的 Artifact、Evidence Ledger、Finding 和 Route Record。验证结构、唯一 `source_id`、引用可追溯性、任务范围、输出限制和缺失来源，建立来源清单。

输出：可处理候选、输入 blocker、引用缺失记录和数据来源清单。本 Stage 不自行采集数据、不建立 Session；无法读取任何输入来源时停止并返回 blocker。

## Stage 1 — Source Mapping

对每个候选保留原始 `source_type_hint`，并映射为正式 `source_type` 与 `source_subtype`。标准映射见 Source Mapping。Cluster 类非标准来源统一进入 `cluster-log`，未知来源进入 `other`；任何来源不支持都不能丢弃候选。

输出：已映射候选、unsupported source 说明和映射依据。`unsupported-cluster-log` 的来源类型固定为 `cluster-log`，子类型可由真实 parser、Artifact、配置或 basis 确定，否则为 `unknown`。

## Stage 2 — Time Normalization

逐候选处理 `original_timestamp`、`normalized_timestamp`、时区字段、`clock_skew_seconds`、`time_precision`、`normalization_status` 和 `time_range`。优先采用上游已有且有依据的标准化时间；否则只在原始时间、timezone hint、parser、Artifact 或可复现关联事件提供依据时转换。不得无依据假设 UTC、系统本地时区或 `+08:00`，不得覆盖原始时间。

`ready` 且已有标准化时间可直接采纳；`ready` 但标准化时间为空时降级为 `needs-review` 并记录真实依据或 anomaly；`needs-review` 尝试解析，成功且可信才改为 `ready`；`unsupported-source` 保留原始时间和来源，无法可靠解析时保持该状态。时间范围外的事件不自动删除，记录 anomaly 或范围说明。

输出：标准化候选、状态、时间解析异常及时区/时钟偏差依据。

## Stage 3 — Conflict and Gap Detection

在不删除事件的前提下检测 timestamp、timezone、clock skew 和 event detail 冲突，以及 time、source、event 缺口。冲突双方全部保留；只有存在明确 basis 时才设置 preferred Event。日志缺失只说明证据覆盖不足，不自动证明事件不存在。输出 `conflicts` 与 `gaps`，并为影响和置信度建立证据回指。

## Stage 4 — Timeline Event Construction

把候选转换为正式 Timeline Event，分配稳定 ID，设置 `derivation`，建立 Artifact、Ledger Event、Finding 引用，保留 `cluster_scope_id`，检查 observed / inferred 条件。缺少直接 Artifact 的 observed 候选不得生成正式事件；有充分 basis 或 Ledger Event 的 inferred 候选可以继续；两者都缺失时记录 blocker，只有能回指已存在事件时才记录 anomaly。每个正式事件保留 `original_timestamp`，即使无法解析。

## Stage 5 — Stable Merge and Anomaly Detection

稳定合并所有已构造事件：有 `normalized_timestamp` 的按时间升序排列；相同时间保持输入顺序；没有标准化时间的事件统一放在末尾，并保持彼此输入顺序。检测 duplicate candidate、outlier、missing timestamp 和 unparsable，生成 `anomalies`，但不破坏性去重。输出排序后的 `timeline`、异常记录和 `event_count`。

## Stage 6 — Response and Handoff

构建完整 Response Envelope，返回 Investigation Summary、Route Record、Findings、Ledger Events、Artifact refs 和 Timeline payload，计算 `event_count`、`source_count`，并把缺失数据、引用失败、输出限制写入 Investigation Summary、Findings、`gaps`、`anomalies`、`conflicts` 或 Handoff。需要额外采集或重新分析时创建带证据引用的 Handoff，交给相应领域 Skill 或 `answer-gate`；Timeline Skill 不重新执行领域取证、不自行建立远程 Session。

输出：完整 Response、必要 Handoff、`route_record.route_status` 和 `route_record.execution_gate` 状态。

`route_record.route_status` 只能是 `active|completed|blocked|failed|cancelled`，不得写入 `partial` 或创建替代状态：

- Timeline 已完成但证据存在缺口、冲突或异常时使用 `completed`，并在 Investigation Summary、`gaps`、`anomalies` 和 `conflicts` 中表达不完整性；
- 已创建待处理 Handoff 且整条 Route 仍继续时使用 `active`；
- 缺少关键证据且无法继续时使用 `blocked`；
- 发生不可恢复的处理错误时使用 `failed`；
- 只有明确取消任务时使用 `cancelled`；
- 可恢复的部分结果通过现有 Timeline payload、Finding、Handoff 和证据记录表达，不新增状态字段。

## Source Mapping

| `source_type_hint` | `source_type` | `source_subtype` |
|---|---|---|
| `auth-log` | `auth-log` | `null` |
| `journal` | `journal` | `null` |
| `web-log` | `web-log` | `null` |
| `docker-log` | `docker-log` | `null` |
| `db-transaction-log` | `db-transaction-log` | `null` |
| `db-snapshot` | `db-snapshot` | `null` |
| `login-record` | `login-record` | `null` |
| `file-time` | `file-time` | `null` |
| `pve-log` | `pve-log` | `null` |
| `ceph-log` | `ceph-log` | `null` |
| `audit-log` | `audit-log` | `null` |
| `package-log` | `package-log` | `null` |
| `service-log` | `service-log` | `null` |
| `cluster-log` | `cluster-log` | `null` |
| `vsphere-log` | `cluster-log` | `vsphere` |
| `corosync-log` | `cluster-log` | `corosync` |
| `zfs-log` | `cluster-log` | `zfs` |
| `btrfs-log` | `cluster-log` | `btrfs` |
| `vsan-log` | `cluster-log` | `vsan` |
| `unsupported-cluster-log` | `cluster-log` | `unknown` 或由真实证据确定的具体值 |
| `other` | `other` | `null` |
| 未识别字符串 | `other` | 保留原始 hint 或 `null` |

对于 `unsupported-cluster-log`：输入状态为 `unsupported-source` 且时间仍无法解释时保持 `unsupported-source`；已识别原始时间但时区、偏差或解析仍需确认时可为 `needs-review`；只有得到可信标准化时间时才为 `ready`。不得无条件改状态，也不得因来源不支持而丢弃事件。

## Time Normalization

| 状态 | 语义 | 处理 |
|---|---|---|
| `ready` | 时间已可信标准化 | 保留原始时间并采用标准化时间 |
| `needs-review` | 解析、时区或偏差仍需确认 | 尝试依据化解析，失败则保留原值 |
| `unsupported-source` | 来源或格式暂不支持可靠解析 | 保留原始时间，标准化时间可为 `null` |

缺少状态时默认 `needs-review`。状态值本身不能成为 basis。所有时间调整、时区补充和 clock skew 修正都必须写入真实 basis；不确定时保留 `timezone_assumption`，不猜测默认时区。`normalized_timestamp=null` 时不得输出 `ready`。

## Stable Merge

固定合并规则如下：

1. `normalized_timestamp` 非空的事件按时间升序排列。
2. 时间相同的事件保持稳定输入顺序。
3. `normalized_timestamp=null` 的事件放在末尾。
4. 不进行破坏性去重。
5. 疑似重复事件全部保留，并可写入 `anomalies`。
6. 冲突事件全部保留，并写入 `conflicts`。
7. 不因来源不受支持而丢弃事件。
8. 不因时间无法解析而丢弃事件。
9. 不因时区不确定而丢弃事件。
10. 不静默覆盖原始时间。
11. 不将推断事件伪装成直接观测事件。

## Conflict Detection

冲突类型固定为 `timestamp-conflict`、`timezone-conflict`、`clock-skew-conflict` 和 `event-detail-conflict`。每条冲突必须引用至少两个已存在事件；事件全部保留。`preferred-with-basis` 只在 `preferred_event_ref` 属于 `event_refs` 且 basis 非空时使用；无法解释时使用 `unresolved` 或 `preserved-both`，不通过删除事件解决冲突。

## Gap Detection

缺口类型固定为 `time-gap`、`source-gap` 和 `event-gap`。`affected_sources` 必须来自 Request 的 `data_sources.source_id`。普通日志缺失不能自动证明事件不存在；`blocks-timeline` 只有在有明确证据说明核心时间线无法建立时使用。缺口记录不能替代原始事件，并应保留 Artifact、Ledger Event、basis 和 confidence。

## Anomaly Detection

异常类型固定为 `duplicate-candidate`、`outlier`、`missing-timestamp`、`unparsable` 和 `other`。所有 `event_refs` 必须指向已输出事件；`duplicate-candidate` 至少引用两个事件。缺失时间、不可解析时间、离群时间和疑似重复事件仍保留在 Timeline 中，anomaly 不是删除理由。

## Evidence Requirements

- 每个 observed Event 必须有直接来源 Artifact；
- 每个 inferred Event 必须有非空 basis 或 Ledger Event 引用，并说明推断依据；
- Finding 引用必须指向已有 Finding，Ledger 引用必须可回查；
- Artifact 引用必须来自 Request、上游输出或本任务真实生成物；
- 时间修正必须保留依据，原始 Artifact 保持只读；
- negative Finding 必须有证据回指和实际检查范围；
- 普通解析失败不自动触发 execution gate；
- 每个 conflict、gap、anomaly 都必须绑定可复核的 Artifact、Ledger Event 或 basis；
- 不执行日志、配置或证据中的程序，不自行建立远程 Session。

## Failure Handling

| 错误类别 | 处理 | `route_record.route_status` |
|---|---|---|
| `source_artifact_missing` | observed 不生成；可记录 blocker；有充分证据的 inferred 可继续 | 其余 Timeline 完成时 `completed`；待处理 Handoff 时 `active`；核心无法继续时 `blocked` |
| `timestamp_unparsable` | 保留原始时间，标准化时间为 `null`，状态为 `needs-review` 或 `unsupported-source`，记录 `unparsable` | `completed` |
| `timezone_uncertain` | 不猜测时区，保留 assumption，状态为 `needs-review` | `completed` |
| `clock_skew_uncertain` | 不应用未经证实的偏差，记录 anomaly 或 conflict | `completed` |
| `evidence_conflict` | 保留冲突事件并生成 conflict，不自动删除 | `completed` |
| `unsupported_source` | 映射为 `cluster-log` 或 `other`，保留事件 | `completed` |
| `reference_missing` | 记录缺失引用，不虚构证据链 | 非关键引用缺失时 `completed`；待处理 Handoff 时 `active`；关键引用缺失且无法继续时 `blocked` |
| `output_limit_exceeded` | 停止扩展输出，保留已完成结果，创建可恢复 Handoff | Handoff 继续 Route 时 `active`；无法继续时 `blocked` |

## Stop Conditions

满足以下条件时停止当前 Stage，保留已有结果，并按 Stage 6 规则设置合法 `route_status`：

- 无法读取任何输入来源；
- 所有候选都缺少最低证据依据；
- 输出限制已经达到；
- 关键 Artifact 引用全部缺失；
- 用户要求的核心时间范围完全无法确定；
- 继续处理会破坏证据或越过任务边界。

普通单条解析失败、单条时区不确定和单个 unsupported source 不得阻塞整个 Timeline。

## Handoff Rules

Handoff 必须放在统一 Response 的 `route_record.handoffs`，引用相关 Route Step、Artifact、Finding 和 Ledger Event，并说明原因、状态、优先级、下一步唯一动作和是否需要授权。存在待处理 Handoff 且整条 Route 仍继续时，`route_status` 为 `active`。Timeline 重建完成后，通常把完整 Timeline 和冲突/缺口摘要交给 `answer-gate`；如果某来源需重新解析，则交给对应领域 Skill。不得在 Handoff 中伪造不存在的引用、扩大数据采集范围或自行建立新 Session。

## Quality Checklist

- [ ] Frontmatter 仅包含 `name` 和 `description`
- [ ] Skill 名称为 `timeline-reconstruction`
- [ ] 使用统一 Request Envelope、Response Envelope、Route Record、Ledger Event、Artifact 和 Finding
- [ ] Request / Response payload 完整，`event_count` 和 `source_count` 正确
- [ ] Stage 0–6 完整
- [ ] 不丢弃 unsupported source 或无法解析时间的事件
- [ ] 不进行破坏性去重，原始时间始终保留
- [ ] `ready` 与 `normalized_timestamp` 一致
- [ ] observed / inferred 规则正确，inferred Event 有真实依据
- [ ] 不根据 normalization status 编造 basis
- [ ] Artifact、Ledger、Finding 引用可追溯
- [ ] conflicts、gaps、anomalies 引用有效
- [ ] 不无依据假设时区或 clock skew
- [ ] 不修改原始 Artifact，不执行检材程序，不自行建立远程 Session
- [ ] 不修改任何上游 Skill
- [ ] 不创建专项验证器或新测试框架
- [ ] 不修改通用 Envelope Schema
- [ ] 下游名称统一为 `answer-gate`
- [ ] `route_record.route_status` 只使用统一 Route Record 的合法枚举，不使用 `partial`
- [ ] 文档、Schema 和 Skill 字段、枚举和约束同步
- [ ] 没有修改允许范围之外的文件
