---
name: linux-server-forensics
description: Linux 服务器系统层取证。分析账号、登录、SSH、sudo、history、cron、systemd、持久化、服务和网络配置，为时间线生成候选事件，将 Web/Database/Docker 证据交给对应专项 Skill。
---

# linux-server-forensics

## Purpose

分析 Linux 操作系统层证据，提取可疑账号、登录记录、SSH 配置、命令历史、持久化点、服务变更和网络异常。支持三种环境：`remote-live`（来自 `remote-server-live-response` 的 `direct-remote`）、`rebuilt-vm`（由 `remote-server-live-response` 从 rebuilt runtime 交接而来，保留 `server-rebuild-executor` 产生的 `plan_id`、`runtime_instance` 和 rebuild Artifact 引用）和 `offline-image`（只读挂载）。

每个关键 Finding 必须同时具有至少一个 Artifact 引用和至少一个 Ledger Event 引用（或有证据价值的命令输出）。Finding Record 的 `evidence_refs` 指向对应 Ledger Event；finding event 使用 `artifact_refs` 和 `route_id` 绑定证据范围；负面 Finding 必须记录实际检查范围；未检查的路径或日志不能输出“未发现异常”；单纯的 Ledger 文本不能代替源 Artifact。Web、Database、Docker 的深入分析交给对应专项 Skill；本 Skill 只建立 cross-domain candidate。

## Use When

- `remote-server-live-response` 已识别 Linux 系统入口并生成 domain candidate
- `remote-server-live-response` 已从 `server-rebuild-executor` 的 rebuilt runtime 建立会话并生成 `linux-server-forensics` domain candidate
- `server-forensics-router` 决定 `offline-image` 模式且检材为 Linux 镜像
- 需要分析 `/etc/passwd`、`/etc/shadow`、`auth.log`、`bash_history`、`crontab`、`systemd` 等系统层证据

## Do Not Use When

- 需要 Web 源码和访问日志的深度攻击分析（交给 `webapp-server-forensics`）
- 需要数据库业务数据和事务日志分析（交给 `database-server-forensics`）
- 需要 Docker image、volume、layer 的深度分析（交给 `docker-container-forensics`）
- 需要恶意二进制逆向、动态分析或执行；本 Skill 只保留静态 Artifact 和证据，不执行样本
- 需要 Windows Server 分析
- 需要服务器重建（交给 `server-rebuild-planner` / `server-rebuild-executor`）
- 需要新建远程连接或绕过 `live_response_scope`
- 需要生成最终报告

## Request Contract

遵循 templates/request-envelope.schema.json。以下代码块仅展示 `request.payload` fragment，不是完整 Request Envelope：

~~~yaml
environment:
  type: rebuilt-vm|remote-live|offline-image
  plan_id: string|null
  session_id: string|null
  connection_ids: array
  connection_results: array
  root_artifact_ref: string|null
  root_path: string|null
  collection_artifact_refs: array
  time_observation: object|null
analysis_scope:
  time_range: object|null
  allowed_paths: array|null
  targeted_questions: array
  include_user_analysis: boolean
  include_auth_analysis: boolean
  include_persistence_analysis: boolean
  include_service_analysis: boolean
  include_history_analysis: boolean
~~~

`request.context` 携带：

- `route_record`
- 上游 findings
- Artifact 引用
- Ledger Event 引用
- live-response domain candidate 和 footprint 信息

## Response Contract

遵循 templates/response-envelope.schema.json。专项结果只放在 `payload`：

~~~yaml
schema_version: "1.0"
investigation_summary: object
route_record: object
findings: array
ledger_events: array
artifact_refs: array
payload:
  environment:
    type: rebuilt-vm|remote-live|offline-image
    plan_id: string|null
    session_id: string|null
  system_profile:
    hostname: string|null
    distro: string|null
    version: string|null
    kernel: string|null
    architecture: string|null
    timezone: string|null
    boot_time: string|null
  user_account_findings: array
  suspicious_users: array
  login_events: array
  ssh_findings: array
  privilege_events: array
  persistence_points: array
  command_history_findings: array
  service_changes: array
  package_findings: array
  network_config_findings: array
  log_source_map:
    - source_id: string
      source_type: auth-log|journal|login-record|audit-log|package-log|service-log|file-time|other
      path: string
      availability: present|missing|partial|unreadable
      coverage_start: string|null
      coverage_end: string|null
      timezone_hint: object|null
      artifact_ref: string|null
      gap_notes: array
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
      source_artifact_id: string
      parser_id: string
      actor: string|null
      action: string
      target: string|null
      ledger_event_refs: array
      confidence: high|medium|low
      normalization_status: ready|needs-review|unsupported-source
  cross_domain_candidates:
    - candidate_id: string
      skill: string
      basis: array
      confidence: high|medium|low
      connection_ids: array
      artifact_refs: array
      finding_refs: array
      targeted_collection_request:
        actions: array
        paths: array
        max_output_bytes: integer|null
        reason: string
  blockers: array
~~~

targeted_collection_request 规则：

`cross_domain_candidates.skill` 只允许填写当前已实现的 `webapp-server-forensics`、`database-server-forensics`、`docker-container-forensics`、`timeline-reconstruction` 或 `remote-server-live-response`。可疑 ELF、脚本和持久化载荷保存在本 Skill 的 persistence、package、file 或 suspicious Finding/candidate 中，并记录需要后续专项分析；不得为其创建未实现 Skill 的 Route Step、Handoff 或 cross-domain target。

- 不需要补充采集时为 `null`
- 非 null 时四个字段必须存在
- `actions` 是明确的已命名采集动作或命令模板
- `paths` 只能包含申请采集的具体路径
- `reason` 必须说明现有 Artifact 为什么不足
- 该对象只用于返回 `remote-server-live-response`
- 本 Skill 不自行执行其中的新远程命令

## Ownership Boundary

| linux-server-forensics 负责 | 不负责 |
|---|---|
| Linux 系统身份和基础配置 | Web 源码和访问日志深度分析 |
| 用户、组和账号状态 | 数据库业务数据和事务日志分析 |
| 登录、认证和会话分析 | Docker image/volume/layer 深度分析 |
| SSH 配置、密钥和访问痕迹 | 恶意二进制逆向和执行 |
| sudo/su 和权限提升 | Windows Server 分析 |
| Shell history 和命令痕迹 | 服务器重建 |
| cron/systemd/init 和启动持久化 | 新建远程连接或绕过 scope |
| 服务变更和异常服务 | 生成最终报告 |
| 软件包和系统变更痕迹 | |
| 网络配置和主机级异常 | |
| 为时间线生成候选事件 | |

## Environment Modes

上游类型映射：

| 上游来源 | 上游 origin.type | 本 Skill environment.type |
|---|---|---|
| `remote-server-live-response`（direct-remote） | `direct-remote` | `remote-live` |
| `remote-server-live-response`（from executor） | `rebuilt-runtime` | `rebuilt-vm` |
| `server-forensics-router` offline-image 路线 | — | `offline-image` |

统一调用链：`server-rebuild-executor` → `remote-server-live-response` → `linux-server-forensics`。本 Skill 不直接消费 Executor `connection_info` 建立远程连接。

### remote-live

来自 `remote-server-live-response`：

- 使用 `session_id`、`connection_results`、`collection_artifact_refs`、`time_observation`、`domain_candidates`
- 优先分析已经采集的 Artifact
- 需要新增远程命令或文件采集时：创建返回 `remote-server-live-response` 的 targeted collection handoff，明确 command/action、路径、输出限制和理由
- 本 Skill 不自行打开新的远程连接
- 记录预期远程 footprint

### rebuilt-vm

统一调用链：`server-rebuild-executor` → `remote-server-live-response` → `linux-server-forensics`。必须由 `remote-server-live-response` 交接进入本 Skill，不得直接从 Executor 调用。

保留：

- `plan_id`、`runtime_instance`、`connection_ids`、rebuild Artifact 引用、`collection_artifact_refs`

规则：

- 本 Skill 不直接使用 Executor 的 `connection_info` 创建新远程连接
- 需要新增远程命令、日志或文件采集时，只生成 targeted collection handoff 返回 `remote-server-live-response`
- 不绕过 `live_response_scope`

### offline-image

使用 `root_artifact_ref`、`root_path` 或 mount reference、`source_artifact_refs`、timezone hints。

规则：

- 不执行检材中的任何二进制、脚本或 systemd unit
- 不 chroot 启动服务
- 不修改挂载内容
- 需要派生文件时写入工作目录
- 保留原始路径、inode、时间戳和 Artifact 映射
- 不将当前主机用户、进程或网络状态误当成证据系统状态

## Artifact-first 处理规则

remote-live 和 rebuilt-vm 必须优先分析已有 `collection_artifact_refs`、上游 Artifact、已有 Ledger Event 和 Finding。

1. Session 不可用，但已有 Artifact 足够：当前分析状态为 `partial`，继续分析已有 Artifact，不阻断整个 Skill。
2. Session 不可用，已有 Artifact 可分析，但仍需要补充采集：创建返回 `remote-server-live-response` 的 targeted collection handoff，`handoff.status` = `pending`，`route_status` = `active`，已有 Artifact 的分析继续完成。
3. Session 不可用，且没有任何可分析 Artifact：当前 `step.status` = `blocked`，根据路由情况返回上游，只有确实没有继续路径时 `route_status` 才为 `blocked`。
4. 可选日志缺失：使用 `error_class` = `log_source_missing`，对应分析阶段标记 `partial`，其他阶段继续。
5. 只有所有关键输入和 Artifact 均不可用时：使用 `source_artifact_missing`，才允许阻断整个 Skill。

## Analysis Workflow

### analysis_scope 映射

| scope 字段 | 对应 Stage | 始终执行 |
|---|---|---|
| — | Stage 1 Environment Validation | 是 |
| — | Stage 2 System Baseline | 是 |
| `include_user_analysis` | Stage 3 Users and Groups | 否 |
| `include_auth_analysis` | Stage 4 Authentication and Login、Stage 5 SSH Analysis、Stage 6 Privilege Escalation | 否 |
| `include_persistence_analysis` | Stage 7 Persistence | 否 |
| `include_history_analysis` | Stage 8 History and Command Traces | 否 |
| `include_service_analysis` | Stage 9 Services, Packages and Network | 否 |

当某个 scope 字段为 `false` 时：对应 Stage 标记为 `skipped`，生成 `state-transition` Ledger Event，不执行该 Stage，不输出该范围“未发现异常”的负面 Finding，Investigation Summary 中明确该范围未执行。

### Stage 1 — Environment Validation

确认：

- `environment.type`
- Artifact 是否存在
- remote-live Session 是否有效
- offline root 是否可识别
- 时间范围和时区依据
- 分析 `analysis_scope`

不得仅凭目录名判断 Linux 发行版。

### Stage 2 — System Baseline

检查：

- `/etc/os-release`
- kernel/version 信息
- hostname
- machine-id
- timezone
- fstab 和 mount 信息
- boot 时间证据
- 系统日志来源（syslog、journal、rsyslog 配置）

每个结论必须引用 Artifact 或命令结果。

### Stage 3 — Users and Groups

分析：

- `/etc/passwd`
- `/etc/group`
- `/etc/shadow` 的账号状态元数据
- UID/GID 异常
- UID 0 账号
- 新增、隐藏、锁定和异常 Shell
- Home 目录与账号不匹配
- sudoers 和 sudoers.d

不得在 Investigation Summary、Finding 或 Ledger 中输出完整密码 Hash。需要保存 Hash 时：仅作为受保护 Artifact；输出中只记录算法、锁定状态和脱敏摘要。

### Stage 4 — Authentication and Login

分析可用来源：

- auth.log / secure
- journal
- wtmp
- btmp
- lastlog
- audit log
- SSH daemon 日志
- sudo / su 记录

区分：成功登录、失败登录、认证方式、来源地址、会话时间、用户切换、证据缺口。

不得把"端口开放"写成"用户登录成功"。

### Stage 5 — SSH Analysis

分析：

- sshd_config 和 include 文件
- authorized_keys
- known_hosts
- SSH public key fingerprint
- PermitRootLogin
- PasswordAuthentication
- AllowUsers / DenyUsers
- 异常端口
- 密钥文件权限
- SSH 登录记录和来源 IP

不得输出私钥正文。Public key 优先记录 fingerprint 和来源路径。

### Stage 6 — Privilege Escalation

分析：

- sudoers
- sudo 日志
- su 记录
- SUID/SGID 候选
- Linux capabilities
- 可写 systemd unit / cron / profile
- 异常组成员关系

remote-live 需要新的全盘 SUID 搜索时：先判断输出规模和 `analysis_scope`，必要时调用 `large-artifact-strategy` 或 targeted collection。

### Stage 7 — Persistence

至少覆盖：

- user/system crontab
- `/etc/cron.*`
- systemd services、timers、drop-ins
- init.d
- rc.local
- shell profile
- authorized_keys
- ld.so.preload
- modules-load
- udev rules
- 异常启动脚本

每个 persistence point 至少包含：

~~~yaml
persistence_id: "pst-<uuid>"
type: cron|systemd|init|profile|ssh-key|preload|module|udev|other
path: string
principal: string
command_or_target: string
enabled_state: enabled|disabled|masked|unknown
first_seen: ISO8601|null
last_modified: ISO8601|null
artifact_refs: array
ledger_event_refs: array
confidence: high|medium|low
~~~

不能仅凭文件存在就断言恶意持久化。

### Stage 8 — History and Command Traces

分析：

- bash/zsh/sh history
- root 和普通用户 history
- history 时间戳
- sudo/su 与 history 的交叉验证
- Shell 配置中的 history 禁用或清理痕迹
- 脚本、临时目录和命令输出

明确：Shell history 可能缺失、被关闭、被截断或延迟写入。History 缺少命令不能证明命令未执行。

### Stage 9 — Services, Packages and Network

分析：

- systemd service 状态和 unit 变化（enabled/disabled/masked）
- 服务启动时间
- 软件包安装、升级和删除日志
- repository 变化
- 网络接口、路由、DNS 和防火墙配置
- 异常监听服务的主机级证据

Web、Database、Docker 的深入内容只建立 cross-domain candidate。

## Time Handling

每个 login、privilege、service、persistence 和 package 事件必须记录：

- `original_timestamp`
- timezone evidence
- normalized timestamp 或 null
- time precision
- clock skew 依据
- source artifact
- confidence

不能无依据假设 UTC、+08:00 或本地时间。生成 `timeline_candidates`，但正式 Timeline Event 由 `timeline-reconstruction` 统一生成。

## Secret Handling

不得在响应、Ledger 或摘要中输出：

- 密码 Hash 全文
- 私钥
- Token
- 数据库密码
- 未脱敏环境变量

只记录：Secret 类型、来源路径、脱敏值或 fingerprint、Artifact 引用、访问限制。

## Evidence Requirements

| Event type | Required use |
|---|---|
| command | 每个文件读取、解析命令、搜索操作 |
| artifact | 每个分析产物（解析结果、提取列表、摘要文件） |
| finding | 每个关键判断（可疑用户、异常登录、持久化点、服务变更） |
| state-transition | 分析阶段完成/跳过/blocked |
| handoff | 交给 domain skills 或返回上游 |

遵循 templates/ledger-event.schema.json：

- command event：exact command、`started_at`、`ended_at`、`exit_code`、`stdout_path`/`stderr_path`、`output_artifact_refs`
- artifact event：非空 `artifact_refs`，新制品使用 `source_artifact_id` 关联来源
- finding event：`finding`、`confidence`、`artifact_refs`、`route_id`；`evidence_refs` 指向对应 Ledger Event；负面 Finding 必须记录实际检查范围；未检查的路径或日志不能输出“未发现异常”；单纯的 Ledger 文本不能代替源 Artifact

## Route and Handoff Rules

### Domain Handoff

| 发现类型 | 目标 skill |
|---|---|
| Web/API | `webapp-server-forensics` |
| Database | `database-server-forensics` |
| Docker/container | `docker-container-forensics` |
| 多源时间事件 | `timeline-reconstruction` |
| 可疑 ELF、脚本或持久化载荷 | 保留 Artifact、Finding、Ledger 和静态 candidate，记录后续专项分析 limitation；不执行样本，不生成跨域目标 |
| 需要额外远程采集 | `remote-server-live-response` targeted collection handoff |

允许并行 handoff，使用 `dependency_step_ids` 和 `parallel_group`。

### Success

- 将本 skill step 标为 `completed`
- 为每个识别的 domain 创建或激活对应 step
- 所有 handoff 通过 route/finding/artifact refs 可追溯

### Failure and Reentry

当环境不匹配、Session 失效、关键输入缺失或需要额外采集，但仍存在上游或替代路径时：

- 当前 linux `step.status` = `blocked` 或 `failed`
- reentry `step.status` = `pending`
- `handoff.status` = `pending`
- `route_status` = `active`
- `reentry_reason` 必须非空
- `new_evidence_refs` 必须非空
- 保留已有 Artifact、Finding 和已完成分析结果

只有以下情况 `route_status` 才能为 `blocked`：没有任何继续路径、`hop_count` 达到或超过 `max_hops`、`execution_gate` 未解决、所有关键输入均缺失、没有任何可分析 Artifact。

不得在返回 Router、Live Response 或其他 Skill 的同时把 `route_status` 设置为 `blocked`。

## Failure Classification

| error_class | 含义 | 默认动作 |
|---|---|---|
| `environment_mismatch` | 环境类型与实际不符 | blocked |
| `source_artifact_missing` | 所有关键输入和 Artifact 均缺失 | blocked（有替代 Artifact 时不得使用 blocked） |
| `session_unavailable` | remote-live session 不可用 | 已有 Artifact 足够→partial+continue；需要采集→handoff；无 Artifact→blocked |
| `root_path_invalid` | offline root 不可识别 | blocked |
| `permission_insufficient` | 无法读取关键文件 | partial |
| `log_source_missing` | 期望的日志源不存在 | partial+continue（不自动触发 execution_gate） |
| `timezone_uncertain` | 时区无法确定 | finding + continue |
| `output_limit_exceeded` | 输出超过限制 | partial |
| `evidence_conflict` | 证据之间矛盾 | finding + continue |
| `targeted_collection_required` | 需要额外远程采集 | `route_status` = `active`，`handoff.status` = `pending`，返回 `remote-server-live-response` |
| `unsupported_linux_layout` | 非标准 Linux 布局 | blocked |

失败本身不自动触发 `execution_gate`。

## Execution Gate

只有拟执行动作超出既有分析或 live-response scope 时才触发：

- 新增远程命令
- 权限提升
- 大规模采集
- 访问未批准路径
- 挂载方式变化
- 修改源检材
- 执行证据内程序

普通日志缺失、解析失败和权限不足本身不等于 `execution_gate`。

## Stop Conditions

- 环境类型无法确认
- 没有任何可分析 Artifact（所有关键输入均不可用）
- `evidence_scope` 不包含任何可分析路径
- route hop 超限

以下情况不停止整个 Skill：

- remote-live session 不可用但已有 Artifact 足够 → 继续分析，标记 `partial`
- 所有日志源缺失 → Authentication/Login 分析标记 `partial`，在 `log_source_map` 中记录 `missing` 和 `gap_notes`；以下仍可继续：passwd/group/shadow 元数据、sudoers、authorized_keys、sshd_config、cron、systemd units、shell profile、persistence 配置、package records、network configuration、文件时间和配置 Artifact

## Investigation Summary

~~~markdown
## Investigation Summary

**Current Assessment**: <一句话总结系统状态和关键发现>

**Key Evidence**:
1. <账号/登录/SSH 证据>
2. <持久化/服务/history 证据>

**Excluded Routes** (if any): <排除的 domain 路线及依据>

**Route Plan**:
- <从 route_record.route_plan 渲染，不独立维护>
~~~

## Quality Checklist

- [ ] Frontmatter 只有 name 与 description
- [ ] 输入/输出使用当前 Request/Response Envelope
- [ ] 支持 `remote-live`、`rebuilt-vm` 和 `offline-image` 三种环境
- [ ] offline-image 不执行检材内程序、不 chroot、不修改挂载内容
- [ ] remote-live 不自行打开新连接，额外采集返回 live-response
- [ ] 每个关键 Finding 同时有 Artifact 和 Ledger Event 引用（或有证据价值的命令输出）
- [ ] `/etc/passwd`、`/etc/shadow`、`auth.log`、`bash_history`、`crontab`、`systemd` 等关键路径均已覆盖
- [ ] 不输出密码 Hash 全文、私钥或 Token
- [ ] SSH private key 不输出正文，public key 记录 fingerprint
- [ ] 不把"端口开放"写成"用户登录成功"
- [ ] 不仅凭文件存在断言恶意持久化
- [ ] History 缺失不等于命令未执行
- [ ] 时间事件记录 timezone evidence 和 confidence
- [ ] 不无依据假设 UTC 或本地时间
- [ ] timeline_candidates 由 timeline-reconstruction 统一生成正式 Timeline Event
- [ ] cross_domain_candidates 只映射到当前已实现的 webapp/database/docker/timeline/live-response；可疑载荷证据保留在本 Skill
- [ ] command event 使用 `output_artifact_refs`，artifact event 使用 `artifact_refs`
- [ ] failure classification 覆盖 11 种 error_class
- [ ] execution_gate 仅在超出 scope 时 required
- [ ] 不硬编码本机路径
- [ ] rebuilt-vm 统一通过 live-response 交接，不直接从 Executor 调用
- [ ] Artifact-first：优先分析已有 collection_artifact_refs 和上游 Artifact
- [ ] Session 不可用时按 Artifact 可用性决定 partial/continue/blocked
- [ ] log_source_missing 不阻断整个 Skill
- [ ] source_artifact_missing 仅用于所有关键 Artifact 均缺失
- [ ] reentry 时 route_status=active，handoff.status=pending
- [ ] 不得在返回上游的同时把 route_status 设为 blocked
- [ ] log_source_map/timeline_candidates/cross_domain_candidates 使用结构化字段
- [ ] analysis_scope 字段为 false 时对应 Stage 标记 skipped
- [ ] 每个关键 Finding 同时有 Artifact 和 Ledger Event 引用
- [ ] 负面 Finding 记录实际检查范围，未检查路径不输出“未发现异常”
