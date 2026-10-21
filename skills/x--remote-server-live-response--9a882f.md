---
name: remote-server-live-response
description: 当服务器已重建成功或题目直接提供远程入口时，负责 SSH、WebUI、DB client、Docker exec、WinRM、RDP 和 service client 连接后的受控低影响远程活体取证。验证连接、建立受控会话、执行低影响易失性数据采集、记录远程操作 footprint，并生成到 domain skills 的 handoff。
---

# remote-server-live-response

## Purpose

将已验证的远程连接信息转换为受控、低影响的远程活体取证会话。只读只用于描述具体查询操作。支持两种来源：来自 `server-rebuild-executor` 的重建运行时（`rebuilt-runtime`），或来自 `server-forensics-router` 的直接远程入口（`direct-remote`）。

严格在 `live_response_scope` 内执行，持续更新 `session-status.json`，记录所有命令、产物和时间观察，成功后交给 domain skills；超出 scope 或连接失败时返回正确的上游步骤。

## Use When

- `server-rebuild-executor` 已完成 Stage 6 并生成 connection_info
- `server-forensics-router` 决定 `remote-live` 模式并提供远程入口
- 需要建立 SSH、WebUI、DB client、Docker exec、WinRM、RDP 或 service client 会话
- 需要执行低影响易失性数据采集并记录取证 footprint
- 需要识别操作系统、服务、容器和数据库入口以交接给 domain skills

## Do Not Use When

- 服务器镜像尚未重建或无远程入口
- 需要修改远程网络或服务配置
- 需要安装软件包或取证工具
- 需要重启服务或主机
- 需要修改密码或账号
- 需要清理日志或 shell history
- 需要完整 Linux、Web、Database、Docker 深度分析（属于下游 domain skills）
- 需要完整 Windows Server 域分析
- 需要生成最终报告

## Request Contract

遵循 templates/request-envelope.schema.json。以下代码块仅展示 `request.payload` fragment，不是完整 Request Envelope：

~~~yaml
origin:
  type: rebuilt-runtime|direct-remote
  plan_id: string|null          # rebuilt-runtime 时非空
connections:                      # 来自 executor Stage 6 或 router 直接入口
  - connection_id: string
    type: ssh|webui|db-client|docker-exec|winrm|rdp|service-client
    host: string
    port: integer
    service: string|null
    credential_source: string|null
    credential_reference: string|null
    authentication_method: password|key|token|certificate|interactive|none
live_response_scope:
  allowed_connection_types: array
  allowed_commands: array|null    # 精确命令模板或已命名采集动作；不使用子串/前缀匹配；未显式批准时禁止管道、重定向、命令替换、多命令拼接和任意路径参数；null 使用默认允许列表
  allowed_targets:                # 允许连接的目标
    - host: string
      ports: array
      connection_types: array
  privilege_escalation_allowed: boolean
  remote_staging_allowed: boolean
  file_collection_allowed: boolean
  max_session_seconds: integer|null
  max_output_bytes: integer|null
  connect_timeout_seconds: integer|null
  max_attempts_per_connection: integer|null
  retry_backoff_seconds: integer|null
session_resume: object|null       # 会话恢复信息
~~~

`max_session_seconds`、`max_output_bytes`、`connect_timeout_seconds`、`max_attempts_per_connection` 或 `retry_backoff_seconds` 为 `null` 时，从项目或案件策略解析默认值；连接前形成非空 `effective_max_session_seconds`、`effective_max_output_bytes`、`effective_connect_timeout_seconds`、`effective_max_attempts_per_connection` 和 `effective_retry_backoff_seconds` 并写入 Session Manifest。无请求值且无可用默认策略时，连接前 `blocked`。

Docker exec 另外验证已批准 container ID。

实际凭据值不得进入 Request 副本、状态文件、命令行、日志或 Ledger Event。

`request.context` 携带：

- `route_record`（包含 route_id、step 依赖和 handoffs）
- executor findings（来源为 `rebuilt-runtime` 时）
- `runtime_instance` 信息
- 已有 Artifact 和 Ledger 引用

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
  session_id: "session-<uuid>"
  origin:
    type: rebuilt-runtime|direct-remote
    plan_id: string|null
  session_status: pending|connecting|active|partial|completed|blocked|failed
  connection_results:
    - connection_id: string
      status: preflight|reachable|connected|authenticated|blocked|failed
      authenticated: boolean|null
      client: string|null
      started_at: ISO8601
      ended_at: ISO8601|null
      error_class: string|null
      attempt_count: integer
      ledger_event_refs: array
  session_summary: string
  remote_identity: object|null
  time_observation: object|null
  volatile_data: array
  collection_artifact_refs: array
  expected_remote_footprint: array
  domain_candidates:
    - skill: string
      basis: array
      confidence: high|medium|low
      connection_ids: array
      finding_refs: array
      artifact_refs: array
  blockers: array
  effective_limits:
    max_session_seconds: integer
    max_output_bytes: integer
    connect_timeout_seconds: integer
    max_attempts_per_connection: integer
    retry_backoff_seconds: integer
~~~

## Ownership Boundary

| remote-server-live-response 负责 | 不负责 |
|---|---|
| 验证远程连接信息 | 服务器镜像重建 |
| 建立受控远程会话 | 修改远程网络或服务配置 |
| 记录连接前后时间和环境信息 | 安装软件包或取证工具 |
| 执行低影响易失性数据采集 | 重启服务或主机 |
| 保存命令、stdout、stderr 和采集产物 | 修改密码或账号 |
| 记录远程操作造成的预期取证痕迹 | 清理日志或 shell history |
| 识别操作系统、服务、容器和数据库入口 | 完整 Linux/Web/Database/Docker 深度分析 |
| 生成到 domain skills 的 route step 和 handoff | 完整 Windows Server 域分析 |
| 失败时返回正确的上游步骤 | 生成最终报告 |

## Workspace and Session State

使用案件工作区内的相对路径：

~~~text
work/live-response/<session_id>/session-status.json
logs/live-response/<session_id>/
output/live-response/<session_id>/
~~~

session manifest 至少记录：

~~~yaml
session_id: "session-<uuid>"
route_id: "route-<uuid>"
connection_ids: array
origin:
  type: rebuilt-runtime|direct-remote
  plan_id: string|null
started_at: ISO8601
ended_at: ISO8601|null
status: pending|connecting|active|partial|completed|blocked|failed
source_handoff_id: "hof-<uuid>"
effective_max_session_seconds: integer
effective_max_output_bytes: integer
effective_connect_timeout_seconds: integer
effective_max_attempts_per_connection: integer
effective_retry_backoff_seconds: integer
completed_actions: array
artifact_refs: array
ledger_event_refs: array
expected_remote_footprint: array
~~~

Session Manifest 登记为 Artifact，相关 Ledger Event 通过 `artifact_refs` 引用。

初始化时创建 session manifest。每次状态转换后：

1. 将完整新状态写入临时文件。
2. 以同一文件系统内的原子替换更新正式文件。
3. 将旧错误、stdout、stderr 和 action 详情保留在 `logs/live-response/<session_id>/`，不得静默抹除。

## Resume and Idempotency

Session 身份使用 `session_id`、`route_id`、`origin` 和规范化（排序、去重）后的 `connection_ids` 集合。每个 action 和 connection_result 单独记录 `connection_id`。

1. `session-status.json` 不存在：初始化新会话。
2. 文件存在且 `session_id`、`route_id`、`origin` 和规范化后的 `connection_ids` 一致：
   - 验证后继续未完成 action；
   - 不重复已完成命令；
   - 已建立会话先验证是否仍有效。
3. 文件存在但身份不一致：
   - 冲突的旧状态文件保持不变，不得为了记录 blocked 而改写；
   - 本次 Response 的 `session_status` 设置为 `blocked`；
   - 生成 finding 和 `state-transition` Ledger Event 记录冲突；
   - 返回上游。
4. 文件损坏：
   - 原文件保留为带时间戳的损坏副本；
   - 不静默重建；
   - 阻断并报告。

## Connection Preflight

每个连接必须检查：

- host 和 port 是否属于 `allowed_targets` 中对应 host 的已批准 ports
- connection type 是否位于该 host 的 `connection_types` 以及 `allowed_connection_types`
- `authentication_method` != `none` 时 `credential_reference` 或安全交互凭据来源必须可解析
- `authentication_method` == `none` 时 `credential_reference` 可以为 null；无认证 Health Check、Banner 和端口确认不因凭据为空而阻断
- `authentication_method` 是否与连接类型匹配
- tool-router 是否确认本地客户端可用
- timeout 和输出限制是否已定义（`effective_max_session_seconds`、`effective_max_output_bytes`、`effective_connect_timeout_seconds`、`effective_max_attempts_per_connection` 和 `effective_retry_backoff_seconds` 非空）
- `request.context.route_record.route_id` 与当前 route_id 一致
- 当前 handoff 的 `to` 为 `remote-server-live-response`
- `handoff.to_step_id` 对应当前 Route Step
- 每个 `connection_id` 在输入 connections 数组中唯一
- 规范化后的 `connection_ids` 集合与 Session Manifest 一致
- 来源为 `rebuilt-runtime` 时 `runtime_running` 是否仍为 true

不得因为端口开放就断言认证成功。连接尝试本身生成 `command` 或 `state-transition` event。

## Bounded Retry Rules

1. 每次连接尝试都增加 `attempt_count`。
2. Retry Ledger Event 使用 `parent_event_id` 关联首次失败事件。
3. 每次 attempt 都保存独立 stdout/stderr。
4. 只有以下错误可以按策略自动 retry：
   - `network_unreachable`
   - `connection_timeout`
   - `remote_session_lost`
   - `artifact_transfer_failed`
5. `host_key_mismatch` 不自动 retry。
6. `authentication_failed` 不使用同一凭据无限 retry；只有 `credential_reference` 更新或出现新证据时才允许重新尝试。
7. 达到 `effective_max_attempts_per_connection` 后：
   - `connection_result.status` = `failed` 或 `blocked`
   - 不再继续自动尝试
   - 根据 origin 返回 executor、planner 或 router
8. 达到 `effective_max_session_seconds` 时停止所有新尝试。
9. 每次连接操作都使用 `effective_connect_timeout_seconds`。
10. Retry 间等待 `effective_retry_backoff_seconds`，不进行无上限等待。

## Session State Transitions

~~~text
pending → connecting
connecting → active | blocked | failed
active → completed | partial | blocked | failed
~~~

`completed`、`blocked`、`failed` 不得自动回到 `connecting`。

只有收到新 Handoff、新凭据引用或明确 Resume 请求时，才允许建立新的连接尝试，并记录 `reentry_reason` / `new_evidence_refs`。

## Connection Type Rules

### SSH

- 支持非交互命令和受控会话
- 使用案件工作区内的 case-scoped `known_hosts`，不修改用户全局 `known_hosts`
- 首次连接记录 host key fingerprint 为 Finding/Artifact
- fingerprint 变化时 blocked 并核验，不自动删除旧 Host Key
- 不使用无条件 `StrictHostKeyChecking=no`
- 不把密码放进命令行参数

### Docker exec

- 只能连接已批准的 container ID
- 不启动新容器
- 不修改 image、volume 或 container configuration

### WinRM

- 可执行通用低影响环境采集
- 不宣称具备完整 Windows Server 域分析能力

### RDP

- 主要用于确认入口和记录交互会话
- RDP 会话本身会改变系统状态，必须记录预期 footprint
- 不把 GUI 观察结果写成已验证命令结果

### WebUI

- 只做受控访问和页面/状态确认
- 深度 Web 分析交给 `webapp-server-forensics`

### DB client

- 只确认连接和基础元数据
- 查询和业务数据分析交给 `database-server-forensics`

### service-client

- 仅执行协议相关的低影响确认

## Time Observation

连接前后必须记录：

~~~yaml
time_observation:
  local_started_at: ISO8601
  local_ended_at: ISO8601
  remote_timestamp: string|null
  remote_timezone: string|null
  timezone_offset: string|null
  estimated_clock_skew_seconds: integer|null
  time_source: string         # remote-clock|config-file|log-entry|assumed
  confidence: high|medium|low
~~~

不能直接假定本地和远程时间一致。`estimated_clock_skew_seconds` 在能获取远程时间时必须估算。

## Volatile Collection Order

按从高易失性到低易失性执行，但只执行 `live_response_scope` 允许的项目。

### Tier 1 — Session and Time

- 会话身份（whoami、id）
- hostname
- 当前时间、时区、uptime
- 当前登录用户和会话

### Tier 2 — Runtime State

- 进程列表
- 网络连接
- 监听端口
- 当前服务状态
- 容器运行状态

### Tier 3 — System Context

- OS/kernel 版本
- 用户和组摘要
- 挂载点
- 环境和关键配置位置
- 当前任务或计划任务摘要

### Tier 4 — Targeted Collection

- 根据 `objective` 和前置 finding 采集指定日志或配置
- 必须有明确 objective、路径、scope 和输出上限
- 大文件或大量目录必须先调用 `large-artifact-strategy`
- 不执行无范围递归扫描

每项必须有：

~~~yaml
collection_id: "col-<uuid>"
category: session|runtime|system|targeted
command: string|null              # 实际执行的命令
started_at: ISO8601
ended_at: ISO8601
output_artifact_ref: "artifact-<uuid>|null"
finding_ref: "finding-<uuid>|null"
impact_level: none|low|medium|high   # none 仅允许 skipped action 或纯本地处理既有 Artifact；任何远程连接、命令或查询至少为 low
status: pending|completed|failed|skipped
~~~

## Credential Handling

- 通过 `credential_reference` 即时解析
- 不放进命令行参数
- 不写入 `session-status.json`
- 不写入 Ledger
- 不出现在 stdout 或 stderr
- 优先使用 stdin、环境变量、Secret Store、SSH agent
- 临时 Secret 文件必须受限权限并及时清理
- 输出只保留 `credential_source`、`credential_reference` 和 `authentication_method`
- 认证失败日志必须脱敏

## Remote Footprint

远程采集不能宣称"零修改"。至少记录可能产生的：

- SSH/WinRM/RDP 登录记录
- shell 或进程创建记录
- sudo/权限提升记录
- 文件访问时间变化（atime）
- WebUI/DB 审计记录
- Docker exec 事件
- 临时文件或环境变量使用痕迹

~~~yaml
expected_remote_footprint:
  - category: login|process|privilege|file-access|audit|container|temp-artifact
    description: string
    reversible: boolean
    evidence_location: string|null
~~~

尽量使用：

- 非交互命令
- 只读查询
- stdout 流式返回
- 本地保存结果

未经批准不得：

- 在远程长期落盘脚本
- 安装依赖
- 修改 shell profile
- 清理 history
- 更改日志配置

## File Collection

若 `live_response_scope.file_collection_allowed` 为 `true`：

- 优先流式传输到本地
- 记录远程路径和本地 Artifact
- 能获取时记录远程 Hash
- 本地重新计算 Hash
- 记录大小、时间、传输方法和完整性结果
- 不覆盖同名已有 Artifact
- 大文件先走 `large-artifact-strategy`
- 远程 staging 只有 `remote_staging_allowed` 为 `true` 时才使用

command event 使用 `output_artifact_refs`。
artifact event 使用 `artifact_refs`。
finding event 引用相应 Artifact 和 command Ledger Event。

## Evidence Requirements

| Event type | Required use |
|---|---|
| command | 每个连接尝试、每个实际执行的命令 |
| artifact | 每个输出文件（命令输出、日志片段、采集产物、Session Manifest） |
| finding | 连接结果、服务发现、系统身份、异常检测 |
| state-transition | 会话状态变化、连接成功/失败、action 完成 |
| handoff | 交给 domain skills 或返回上游 |

遵循 templates/ledger-event.schema.json：

- command event 必须含非空 `command`、`started_at`，完成后补 `ended_at`、`exit_code` 和 `stdout/stderr`，使用 `output_artifact_refs` 引用产出的 Artifact。
- artifact event 必须含非空 `artifact_refs`；新制品使用 `source_artifact_id` 关联来源。Session Manifest 和 Action Record 登记为 Artifact，相关 Event 通过 `artifact_refs` 引用。
- finding event 必须含 `finding`、`confidence`，并用 `artifact_refs`/`route_id` 绑定当前证据范围。非命令 `acquisition_method` 写入 Artifact Record 或 Finding Record，再产生 artifact/finding event。
- state-transition event 使用 `stage`、`status`、`route_id`、`artifact_refs`、`next_action`。
- handoff event 使用 `route_id` 与 `handoff_id`。

Ledger Event 不得添加 schema 未定义的字段（如 `session_id`、`connection_id`、`acquisition_method`）；这些信息保存在 Session Manifest 或 Action Record 中。

每次连接尝试 → `command` 或 `state-transition` event。
每个实际命令 → `command` event。
每个输出文件 → Artifact Record + `artifact` event。
每个关键判断 → Finding Record + `finding` event。
每个交接 → `handoff` event。

事件由 evidence-ledger 持久化到 JSONL 和 Markdown；本 skill 只产生事件对象。

## Route and Handoff Rules

### Domain Handoff

根据实际发现建立 domain handoff：

| 发现类型 | 目标 skill |
|---|---|
| Linux 系统 | `linux-server-forensics` |
| Docker/container | `docker-container-forensics` |
| Web/API | `webapp-server-forensics` |
| Database | `database-server-forensics` |
| 需要时间关联 | `timeline-reconstruction` |
| Windows Server | 在批准范围内执行通用 WinRM/RDP 入口验证和低扰动采集；仅交给证据支持的现有 Web、Database、Docker 或 Timeline 路径，不路由到 `linux-server-forensics` |

允许并行 handoff，但必须通过 `dependency_step_ids` 和 `parallel_group` 表达。

Handoff 使用 `from_step_id`、`to_step_id`、`artifact_refs`、`finding_refs`、`visited_skills` 和 `hop_count`。

Windows OS 层没有当前消费者时，记录带 Artifact/Ledger 引用的 scope gap、blocker 或 limitation Finding，不创建到未实现 Skill 的 Route Step 或 Handoff。若仍有现有领域消费者则 Route 保持 `active`；没有任何当前消费者且核心目标无法继续时才设置 `blocked`。

### Success

- 将本 skill step 标为 `completed`。
- 为每个识别的 domain 创建或激活对应 step，并用 `dependency_step_ids` 指向本 step。
- `connection_info` 只包含入口元数据和凭据引用。

### Failure — Rebuilt Runtime

来源为 `rebuilt-runtime` 且 runtime/端口/connection_info 错误：

→ handoff 回 `server-rebuild-executor`
→ `reentry_reason` 记录 connection/error class

来源为 `rebuilt-runtime` 且凭据规划或凭据引用错误：

→ handoff 回 `server-rebuild-planner`
→ `reentry_reason` 记录 credential/error class

### Failure — Direct Remote

来源为 `direct-remote` 且入口或凭据材料错误：

→ handoff 回 `server-forensics-router`
→ `reentry_reason` 记录 connection/error class

### Credential Failure

凭据无效或缺失：

- `route_status` 保持 `active`
- 生成 `blocked` step 和 `pending` reentry handoff
- `handoff.status` = `pending`
- `reentry_reason` 明确
- `new_evidence_refs` 非空
- 请求补充 `credential_reference`

只有没有任何继续路径、`hop_count` 超限或 `execution_gate` 未解决时，`route_status` 才为 `blocked`。

## Failure Classification

错误类别：

| error_class | 含义 | 默认动作 |
|---|---|---|
| `target_out_of_scope` | 目标不在 allowed_targets 内 | blocked |
| `client_capability_missing` | 本地客户端不可用 | blocked |
| `network_unreachable` | 网络不可达 | retry |
| `connection_timeout` | 连接超时 | retry |
| `host_key_mismatch` | SSH host key 变更 | blocked |
| `authentication_failed` | 认证失败 | blocked |
| `service_mismatch` | 服务类型与预期不符 | finding + continue |
| `privilege_insufficient` | 权限不足 | partial |
| `output_limit_exceeded` | 输出超过 effective_max_output_bytes | partial |
| `remote_session_lost` | 远程会话丢失 | retry |
| `artifact_transfer_failed` | 文件传输失败 | retry |

## Execution Gate

只有操作超出 `live_response_scope` 时 `execution_gate.required` 才为 `true`：

- 使用未批准的连接类型
- 权限提升（`privilege_escalation_allowed` 为 `false` 时）
- 远程 staging（`remote_staging_allowed` 为 `false` 时）
- 安装工具
- 修改服务或网络
- 重启系统
- 采集未批准的大量数据
- 执行会明显改变远程状态的操作

普通连接失败和认证失败本身不触发 `execution_gate`。

## Stop Conditions

- Session 身份（`session_id`/`route_id`/`origin`/`connection_ids`）不一致
- 来源运行时不再运行且无其他入口
- 所有连接尝试均失败且无 retry 路径
- 凭据缺失且无法获取
- `live_response_scope` 为空或全部连接类型未批准
- 超过 `effective_max_session_seconds` 且无法安全续期
- 输出超过 `effective_max_output_bytes` 且无法分段
- route hop 超限或 handoff 会形成无新证据的循环

## Investigation Summary

~~~markdown
## Investigation Summary

**Current Assessment**: 会话 <session_id> 状态 <session_status>，来源 <origin.type>

**Key Evidence**:
1. <连接/身份/系统发现证据>
2. <易失性数据采集证据>

**Excluded Routes** (if any): <排除的 domain 路线及依据>

**Route Plan**:
- <从 route_record.route_plan 渲染，不独立维护>
~~~

## Default Allowed Commands

默认允许（当 `allowed_commands` 为 `null` 时）：

- `hostname`、`date`、`whoami`、`id`、`uname -a`
- `ip addr` 或 `ipconfig`
- `ss -tulpn` 或等价只读命令
- `docker ps`、`docker compose ps`
- `docker logs --tail`（须指定已批准 container ID 和受限 tail 数量）

日志、配置、源码的查看属于 Tier 4 Targeted Collection，必须有明确 objective、路径、scope 和输出上限。数据库查询交给 `database-server-forensics`。

## Default Forbidden Commands

默认禁止：

- 重启服务、修改账号/密码、修改防火墙/网络
- 清理日志、安装依赖、外网扫描
- 执行未知样本、删除文件、改数据库

## Quality Checklist

- [ ] Frontmatter 只有 name 与 description
- [ ] 输入/输出使用当前 Request/Response Envelope
- [ ] 支持 `rebuilt-runtime` 和 `direct-remote` 两种来源
- [ ] `live_response_scope` 约束所有连接和命令行为
- [ ] `allowed_commands` 使用精确匹配，禁止隐式管道/重定向/命令替换
- [ ] `allowed_targets` 结构化为 host + ports + connection_types
- [ ] null `max_session_seconds`/`max_output_bytes` 连接前解析为 effective 值
- [ ] 连接前验证 host/port/type/credential(条件化)/tool-router
- [ ] 不因端口开放就断言认证成功
- [ ] SSH 使用 case-scoped `known_hosts`
- [ ] SSH host key 变更时不得自动忽略
- [ ] 不使用无条件 `StrictHostKeyChecking=no`
- [ ] RDP 和 WinRM 预期 footprint 已记录
- [ ] WebUI/DB client 只做低影响确认，深度分析交给 domain skills
- [ ] 时间观察记录本地/远程时间和 clock skew
- [ ] 易失性采集按 Tier 1-4 顺序执行
- [ ] `impact_level=none` 仅用于 skipped 或纯本地处理
- [ ] 凭据不进入命令行、状态文件、Ledger 或日志
- [ ] 远程 footprint 至少记录登录、进程、文件访问痕迹
- [ ] file collection 记录远程路径、Hash 和完整性
- [ ] command event 使用 `output_artifact_refs`，artifact event 使用 `artifact_refs`
- [ ] Session Manifest 和 Action Record 登记为 Artifact，Ledger Event 通过 artifact_refs 引用
- [ ] Ledger Event 不含 schema 未定义的字段
- [ ] Resume 按 session_id/route_id/origin/normalized connection_ids 一致性决定续跑或阻断
- [ ] 冲突状态文件不得改写
- [ ] 凭据失败区分 runtime/端口错误（→executor）、凭据规划错误（→planner）和入口错误（→router）
- [ ] domain handoff 使用 dependency_step_ids 和 parallel_group
- [ ] Windows Server 不路由到 linux-server-forensics
- [ ] execution_gate 仅在超出 scope 时 required
- [ ] 所有结论绑定 Artifact、Ledger Event 或命令输出
- [ ] 不硬编码本机路径
- [ ] Connection Preflight 校验 route_id/handoff.to/step_id/唯一 connection_id/normalized connection_ids
- [ ] null 连接超时/重试参数连接前解析为 effective 值
- [ ] Bounded Retry 仅对允许的 error_class 自动重试
- [ ] `host_key_mismatch` 和 `authentication_failed` 不自动无限 retry
- [ ] 达到 `effective_max_attempts_per_connection` 后停止自动尝试
- [ ] Session State Transitions 不允许 completed/blocked/failed 自动回到 connecting
