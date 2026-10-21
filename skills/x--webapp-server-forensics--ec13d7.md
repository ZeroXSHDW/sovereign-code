---
name: webapp-server-forensics
description: Web 和 API 服务取证。识别 Web 服务器、框架和部署结构，分析源码、配置、路由、访问日志、上传目录、WebShell 候选和 Secret 暴露，要求源码与日志交叉验证，将数据库/Docker/Linux 证据交给对应专项 Skill。
---

# webapp-server-forensics

## Purpose

分析 Web 和 API 服务的源码、配置、路由、日志和部署结构，识别入口点、可疑 IP、请求链、攻击痕迹、WebShell 候选和 Secret 暴露。支持四种环境：`remote-live`、`rebuilt-vm`、`offline-image` 和 `source-package`。

每个关键 Finding 必须同时具有至少一个 Artifact 引用和至少一个 Ledger Event 引用（或有证据价值的命令输出）。访问日志与源码必须互证；运行态发现必须回证到源码、配置或日志。本 Skill 不执行样本、不主动利用漏洞、不修改源检材。

## Use When

- `remote-server-live-response` 已识别 Web/API 服务入口并生成 domain candidate
- `linux-server-forensics` 发现 Web 组件并生成 cross-domain candidate
- `server-forensics-router` 决定 `offline-image` 且检材包含 Web 服务
- Router 或其他 Skill 交接源码包、部署包或 Web 项目目录
- 需要分析 Nginx/Apache/IIS/Tomcat 配置、路由、access/error log、WebShell 候选

## Do Not Use When

- 需要主机账号、sudo、cron、systemd 的完整分析（交给 `linux-server-forensics`）
- 需要数据库业务数据和事务日志深度分析（交给 `database-server-forensics`）
- 需要 Docker image/layer/volume 深度分析（交给 `docker-container-forensics`）
- 需要执行或动态分析 WebShell、脚本或可疑文件；本 Skill 只保留静态 Artifact 和证据，不执行样本
- 需要主动利用漏洞、暴力扫描或目录爆破
- 需要修改源码、配置、日志、数据库或远程服务
- 需要安装依赖、启动应用或重建服务器
- 需要生成最终报告

## Request Contract

遵循 templates/request-envelope.schema.json。以下代码块仅展示 `request.payload` fragment，不是完整 Request Envelope：

~~~yaml
environment:
  type: remote-live|rebuilt-vm|offline-image|source-package
  plan_id: string|null
  session_id: string|null
  connection_ids: array
  connection_results: array
  root_artifact_ref: string|null
  root_path: string|null
  collection_artifact_refs: array
  time_observation: object|null
web_scope:
  time_range: object|null
  allowed_paths: array|null
  targeted_questions: array
  include_component_detection: boolean
  include_config_analysis: boolean
  include_route_analysis: boolean
  include_access_log_analysis: boolean
  include_webshell_analysis: boolean
  include_secret_analysis: boolean
~~~

`request.context` 携带：`route_record`、上游 findings、Artifact 和 Ledger 引用、live-response domain candidate、Linux cross-domain candidate、remote footprint、已知 Web 路径/端口/服务/时间依据。

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
    type: remote-live|rebuilt-vm|offline-image|source-package
    plan_id: string|null
    session_id: string|null
  web_profile:
    server_software: array
    frameworks: array
    languages: array
    document_roots: array
    deployment_model: string|null
    timezone: string|null
  detected_components:
    - component_id: string
      name: string
      component_type: web-server|reverse-proxy|framework|runtime|application|waf|other
      version: string|null
      artifact_refs: array
      ledger_event_refs: array
      confidence: high|medium|low
  source_paths:
    - path_id: string
      path: string
      role: document-root|source-root|public-assets|upload-directory|template-directory|dependency-directory|other
      artifact_ref: string|null
      availability: present|missing|partial|unreadable
  config_paths:
    - config_id: string
      path: string
      config_type: virtual-host|reverse-proxy|application|framework|environment|routing|security|other
      artifact_ref: string|null
      availability: present|missing|partial|unreadable
  log_source_map:
    - source_id: string
      source_type: access-log|error-log|application-log|proxy-log|waf-log|audit-log|other
      path: string
      availability: present|missing|partial|unreadable
      coverage_start: string|null
      coverage_end: string|null
      timezone_hint: object|null
      artifact_ref: string|null
      gap_notes: array
  route_map:
    - route_entry_id: string
      method: string|null
      path_pattern: string
      handler: string|null
      source_path: string|null
      authentication_required: boolean|null
      artifact_refs: array
      confidence: high|medium|low
  secret_findings:
    - secret_id: string
      secret_type: password|token|api-key|private-key|database-credential|cookie-secret|encryption-key|other
      redacted_value: string
      source_path: string
      source_artifact_id: string
      line_or_key: string|null
      exposure_context: string
      finding_refs: array
      ledger_event_refs: array
      confidence: high|medium|low
  access_log_findings:
    - finding_id: string
      original_timestamp: string|null
      normalized_timestamp: ISO8601|null
      source_ip: string|null
      forwarded_for: array
      attributed_client_ip: string|null
      method: string|null
      raw_path: string|null
      normalized_path: string|null
      status_code: integer|null
      user_agent: string|null
      request_id: string|null
      indicators: array
      redaction_applied: boolean
      normalization_steps: array
      client_ip_basis: socket-peer|trusted-proxy-chain|untrusted-forwarded|unknown
      artifact_refs: array
      ledger_event_refs: array
      confidence: high|medium|low
  suspected_entrypoint:
    entrypoint_id: string
    method: string|null
    path: string|null
    route_entry_id: string|null
    source_path: string|null
    first_seen: ISO8601|null
    basis: array
    artifact_refs: array
    finding_refs: array
    ledger_event_refs: array
    confidence: high|medium|low
  suspect_ip: string|null
  suspect_ip_basis:
    - basis_type: direct-log|trusted-proxy-chain|cross-log-correlation|request-chain|other
      description: string
      artifact_refs: array
      finding_refs: array
      ledger_event_refs: array
  suspect_ip_confidence: high|medium|low|null
  webshell_candidate:
    - candidate_id: string
      path: string
      language: string|null
      source_artifact_id: string
      indicators: array
      execution_observed: boolean|null  # true 仅限访问日志/进程/审计/运行时直接证据；静态特征时 null；检查相关范围后才允许 false
      artifact_refs: array
      finding_refs: array
      ledger_event_refs: array
      confidence: high|medium|low
  source_log_crosscheck:
    status: matched|partial|unmatched|not-applicable
    # matched: 源码/配置/日志间存在直接可追溯链接
    # partial: 只有部分数据源存在或只完成部分映射
    # unmatched: 所需数据源均已实际检查但未找到支持关系
    # not-applicable: 对应 Stage 被 scope 跳过或材料类型不具备该类数据源
    links:
      - route_entry_id: string|null
        source_path: string|null
        log_finding_ids: array
        basis: array
    gaps: array
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
        actions: array        # 明确的已命名采集动作或命令模板
        paths: array          # 只能包含申请采集的具体路径
        max_output_bytes: integer|null
        reason: string        # 必须说明现有 Artifact 为什么不足
  blockers: array
~~~

`suspected_entrypoint` 整体允许为 null：无足够证据确定入口时不强行选择；多个候选无法收敛时保持 null 并在 findings 或 gaps 中说明。非 null 时必须包含文档中列出的全部字段。

`targeted_collection_request` 整体允许为 null：不需要补充采集时；非 null 时四个字段必须存在；只用于交给 `remote-server-live-response`。

`cross_domain_candidates.skill` 只允许填写当前已实现的 `linux-server-forensics`、`database-server-forensics`、`docker-container-forensics`、`timeline-reconstruction` 或 `remote-server-live-response`。可疑脚本、WebShell 和载荷保存在 `webshell_candidate`、`suspected_entrypoint` 或 Finding 中，并记录需要后续专项分析；不得为其创建未实现 Skill 的 Route Step、Handoff 或 cross-domain target。

## Ownership Boundary

| webapp-server-forensics 负责 | 不负责 |
|---|---|
| Web 服务器/中间件/框架/部署结构识别 | 主机账号/sudo/cron/systemd 完整分析 |
| Document root/虚拟主机/反向代理/应用入口 | 数据库业务数据和事务日志深度分析 |
| 源码/配置/日志目录映射 | Docker image/layer/volume 深度分析 |
| 路由/Controller/Handler/源码路径映射 | 执行 WebShell/脚本/可疑文件 |
| Access/Error/Application/Proxy/WAF 日志分析 | 主动利用漏洞 |
| 请求入口/可疑 IP/请求链/攻击痕迹 | 暴力扫描/目录爆破/无范围递归扫描 |
| WebShell/可疑脚本静态候选识别 | 修改源码/配置/日志/数据库/远程服务 |
| Secret 位置识别与脱敏 | 安装依赖/启动应用/重建服务器 |
| 源码/配置/日志交叉验证 | 输出完整 Secret |
| 生成时间线候选事件 | 生成最终报告 |

## Environment Modes

上游类型映射：

| 上游来源 | 上游 origin.type | 本 Skill environment.type |
|---|---|---|
| `remote-server-live-response`（direct-remote） | `direct-remote` | `remote-live` |
| `remote-server-live-response`（from executor） | `rebuilt-runtime` | `rebuilt-vm` |
| `server-forensics-router` offline-image 路线 | — | `offline-image` |
| Router 或其他 Domain Skill 直接交接源码/包 | — | `source-package` |

### remote-live

由 `remote-server-live-response` 交接。优先分析 `collection_artifact_refs`、`connection_results`、`time_observation`、`domain_candidates` 和已有日志/配置/源码 Artifact。需要补充远程文件或命令时：创建 targeted collection handoff 返回 `remote-server-live-response`，本 Skill 不自行新建连接或执行未批准远程命令。

### rebuilt-vm

统一调用链：`server-rebuild-executor` → `remote-server-live-response` → `webapp-server-forensics`。保留 `plan_id`、`runtime_instance`、`connection_ids`、rebuild Artifact 和 collection Artifact。不得直接消费 Executor `connection_info` 建立连接。

### offline-image

分析只读挂载的系统或应用目录。不得执行证据内程序、启动 Web 服务、chroot 启动应用、写入挂载内容或将当前主机状态当成证据系统状态。

### source-package

由 Router 或其他 Domain Skill 交接的源码、部署包、配置包或 Web 项目目录。只做静态分析，不安装依赖、不构建、不启动项目。

## Path Safety Rules

### allowed_paths 非 null

所有读取、搜索、解析和派生操作必须限制在批准根路径内。先解析规范路径，再检查是否仍位于批准根路径。不通过相对路径、符号链接、junction 或 reparse point 越出范围。

### allowed_paths 为 null

从 `root_artifact_ref`、`root_path`、`collection_artifact_refs`、`source_paths` 和 `route_record.evidence_scope` 解析有限分析根。如果无法形成明确、有限的分析根，不得开始递归扫描；记录 blocker 或请求补充 scope。

### source-package 和压缩部署包

- 不在源 Artifact 内原地解压
- 只解压到案件工作目录
- 拒绝绝对路径、`..` 路径穿越和越界符号链接
- 在解压前检查文件数量、声明大小和实际展开规模
- 大包或大量文件先调用 `large-artifact-strategy`
- 不安装依赖、不构建、不启动项目
- 派生文件必须登记 Artifact 并保留源 Artifact 映射

## Artifact-first

remote-live 和 rebuilt-vm 优先分析已有 Artifact。

1. Session 不可用但 Artifact 足够：`partial` + continue
2. Session 不可用且需要补充采集：targeted collection handoff，`handoff.status` = `pending`，`route_status` = `active`
3. Session 不可用且无任何可分析 Artifact：当前 step `blocked`，无继续路径时 `route_status` = `blocked`
4. 单个日志或配置缺失：对应阶段 `partial`，其他阶段继续
5. 大日志、大源码树或大量文件：先调用 `large-artifact-strategy`，不进行无范围递归扫描

## Analysis Scope Mapping

| scope 字段 | 对应 Stage | 始终执行 |
|---|---|---|
| — | Stage 1 Environment Validation | 是 |
| `include_component_detection` | Stage 2 Web Baseline and Component Detection | 否 |
| `include_config_analysis` | Stage 3 Configuration and Deployment Mapping | 否 |
| `include_route_analysis` | Stage 4 Route and Source Mapping | 否 |
| `include_access_log_analysis` | Stage 5 Log Analysis | 否 |
| `include_access_log_analysis` + `include_route_analysis` | Stage 6 Entrypoint and Request-chain Analysis | 否 |
| `include_webshell_analysis` | Stage 7 WebShell and Suspicious File Candidates | 否 |
| `include_secret_analysis` | Stage 8 Secret and Deployment Exposure | 否 |
| — | Stage 9 Source–Config–Log Crosscheck | 对已启用 Stage 的结果执行 |

Scope 为 `false`：Stage 标为 `skipped`，生成 `state-transition` event，不输出该范围"未发现异常"，Investigation Summary 说明未执行范围。

## Analysis Workflow

### Stage 1 — Environment Validation

确认 `environment.type`、Artifact 可用性、Session 状态、root/source path、`allowed_paths`、`time_range`、timezone evidence、`web_scope`。不得只凭目录名称判断框架或 Web 服务。

### Stage 2 — Web Baseline and Component Detection

识别：

- Nginx、Apache、Tomcat、IIS 或其他 Web Server
- Reverse Proxy
- PHP、Java、Python、Node.js、Go、.NET 等运行环境
- 常见框架和版本证据
- Document root、静态资源、上传目录
- WAF、代理和负载均衡痕迹

版本结论必须引用配置、响应、包清单或源码 Artifact。不得仅凭文件名猜测版本。每个 `detected_components` 必须有 `artifact_refs` 和 `ledger_event_refs`。

### Stage 3 — Configuration and Deployment Mapping

分析：

- Nginx/Apache/IIS/Tomcat 配置
- Virtual Host、Reverse Proxy 和 upstream
- TLS/证书引用
- 环境配置（`.env`）、应用配置、框架配置
- 日志路径、上传和临时目录
- 数据库连接配置位置
- 容器或 Compose 部署线索

不得输出完整 Secret。

### Stage 4 — Route and Source Mapping

识别：

- 路由文件、Controller、Handler、Servlet、Endpoint
- Middleware 和鉴权边界
- 文件上传入口、管理后台入口、API 路由
- 路由到源码文件的映射

不得把字符串搜索结果直接写成可访问路由。必须有框架结构、配置或日志证据支持。

### Stage 5 — Log Analysis

分析：Access Log、Error Log、Application Log、Reverse Proxy Log、WAF Log、Audit Log。保留原始请求路径、解码/规范化路径、Method、Status、Source IP、User-Agent、Referer、Request ID、Upstream 信息、原始时间和时区依据。

规则：

1. 不得仅凭 HTTP 200 判断攻击成功
2. 不得默认信任 X-Forwarded-For
3. 只有代理配置和链路证据支持时，才将 forwarded IP 作为来源候选
4. 编码路径和解码路径同时保留
5. 日志缺失不等于请求未发生
6. 日志轮转、清理和时间覆盖缺口必须记录
7. Response 中 `raw_path` 必须脱敏查询参数内的密码、Token、API Key、Session ID、签名和其他 Secret；精确原始请求保留在源日志 Artifact 中
8. `normalization_steps` 记录每一步解码、大小写处理、路径折叠或分隔符处理；不进行未记录的反复解码
9. `redaction_applied` 在 Response 字段发生脱敏时为 `true`；不得因脱敏而修改源 Artifact

### Stage 6 — Entrypoint and Request-chain Analysis

**执行条件**：`include_access_log_analysis` 和 `include_route_analysis` 都为 `true` 时完整执行。只有其中一个为 `true` 时标记 `partial` 或 `skipped`，只输出当前证据允许的候选，不得声称完成了完整请求链映射，记录缺少的源码/Route 或日志范围。

结合 Route Map、Source Code、Config、Access/Error/Application Log、文件时间、上传目录和下游数据库/容器线索，分析可能的上传入口、未授权接口、Traversal、Command Injection、Deserialization、Template Injection、SQL Injection 入口、WebShell 访问、异常管理接口、可疑 API 调用。只记录有证据支持的候选。不得主动发送利用 Payload 验证。

### Stage 7 — WebShell and Suspicious File Candidates

只进行静态识别：文件路径和时间、Hash、语言和扩展名、高风险函数、编码和混淆、动态执行、外部命令、上传痕迹、日志访问证据。

不得：执行文件、在证据系统中包含或运行文件、自动删除或隔离源文件、将单个高风险函数直接定性为 WebShell。

`execution_observed` 语义：
- `true`：只有访问日志、进程、审计、运行时记录或其他直接执行证据支持时允许
- `null`：仅静态代码特征时
- `false`：只有实际检查了相关运行和日志范围后才允许

`source_artifact_id` 引用包含该文件的 Artifact Record。Hash 的算法、值和状态从 Artifact Record 获取，不在 payload 中使用未定义的 `hash_ref`。

可疑文件保留为本 Skill 的 `webshell_candidate`、`suspected_entrypoint` 或 Finding，记录后续专项分析 limitation；不创建跨域可执行目标。

### Stage 8 — Secret and Deployment Exposure

识别位置和暴露风险。不得输出密码/Token/API Key/私钥/Cookie Secret/数据库凭据全文或未脱敏环境变量。只记录：Secret 类型、来源路径、键名或行号、脱敏值或 Fingerprint、Artifact 引用、暴露上下文、访问限制。

额外规则：

- Secret 搜索不得把完整匹配行直接写入 stdout、stderr、Ledger Event、Investigation Summary 或普通解析结果
- 工具默认输出完整匹配值时：使用只输出文件路径、键名、行号或 Fingerprint 的安全模式；或将完整结果写入受访问控制的保护 Artifact，再生成脱敏分析 Artifact
- `redacted_value` 必须是不可逆脱敏表示或 Fingerprint，不能只遮挡少数字符后保留大部分 Secret
- private key 只记录类型、Fingerprint 和来源路径
- Access Log、Referer、User-Agent、配置和异常日志中的 Token、Cookie、Authorization 值也适用相同规则
- command event 中的 `command`、`stdout_path` 和 `stderr_path` 不得间接暴露 Secret

### Stage 9 — Source–Config–Log Crosscheck

**状态语义**：

- `matched`：源码、配置和日志之间存在直接可追溯链接
- `partial`：只有部分数据源存在或只完成部分映射
- `unmatched`：所需数据源均已实际检查，但未找到支持关系
- `not-applicable`：对应 Stage 被 scope 跳过，或材料类型本身不具备该类数据源

不得因数据源缺失而错误写 `unmatched`。

至少交叉验证：

- Route 是否在源码和配置中存在
- 日志请求是否能映射到 Route
- Route 是否能映射到 Handler 或源码
- 上传文件是否有请求和文件 Artifact 支撑
- WebShell 候选是否有访问记录
- 可疑 IP 是否在多个日志源出现
- 时间是否在日志覆盖范围内

证据冲突时记录 `evidence_conflict`，不得选择性忽略不一致证据。

## Time Handling

每个访问、错误、部署、上传、WebShell 和配置变化候选事件记录：`original_timestamp`、`normalized_timestamp` 或 null、timezone evidence、clock skew 依据、time precision、source Artifact、confidence。不得无依据假设 UTC、+08:00 或系统本地时间。本 Skill 只生成 `timeline_candidates`，正式 Timeline Event 由 `timeline-reconstruction` 创建。

## Evidence Requirements

| Event type | Required use |
|---|---|
| command | 每个文件读取、配置解析、日志解析、源码搜索 |
| artifact | 每个分析产物（路由表、组件列表、日志解析结果、交叉验证结果） |
| finding | 每个关键判断（入口点、WebShell 候选、Secret 暴露、攻击痕迹） |
| state-transition | 分析阶段完成/跳过/blocked |
| handoff | 交给 domain skills 或返回上游 |

遵循 templates/ledger-event.schema.json。每个关键 Finding 必须同时具有至少一个 Artifact 引用和至少一个 Ledger Event 引用（或有证据价值的命令输出）。Finding Record 的 `evidence_refs` 指向对应 Ledger Event。负面 Finding 必须记录实际检查范围；未检查的路径、Route 或日志不能输出"未发现"。

重点检查以下对象的证据引用：`detected_components`（`artifact_refs` + `ledger_event_refs`）、`suspected_entrypoint`（`artifact_refs` + `finding_refs` + `ledger_event_refs`）、`webshell_candidate`（`artifact_refs` + `finding_refs` + `ledger_event_refs`）、`access_log_findings`（`artifact_refs` + `ledger_event_refs`）、`secret_findings`（`finding_refs` + `ledger_event_refs`）。

## Route and Handoff Rules

### Domain Handoff

| 发现类型 | 目标 skill |
|---|---|
| Linux 主机级问题 | `linux-server-forensics` |
| 数据库配置/查询/业务数据 | `database-server-forensics` |
| Docker/Compose/container | `docker-container-forensics` |
| 多源时间事件 | `timeline-reconstruction` |
| 可疑脚本/WebShell/载荷 | 保留 Artifact、Finding、Ledger 和静态 candidate，记录后续专项分析 limitation；本 Skill 不执行样本 |
| 额外远程采集 | `remote-server-live-response` targeted collection handoff |

允许并行 handoff，使用 `dependency_step_ids` 和 `parallel_group`。

### Failure and Reentry

仍有继续路径时：

- 当前 `step.status` = `blocked` 或 `failed`
- reentry `step.status` = `pending`
- `handoff.status` = `pending`
- `route_status` = `active`
- `reentry_reason` 非空
- `new_evidence_refs` 非空

只有以下情况 `route_status` = `blocked`：无任何继续路径、hop 超限、`execution_gate` 未解决、所有关键输入均缺失、无任何可分析 Artifact。

## Failure Classification

| error_class | 含义 | 默认动作 |
|---|---|---|
| `environment_mismatch` | 环境类型与实际不符 | blocked |
| `source_artifact_missing` | 所有关键输入和 Artifact 均缺失 | blocked |
| `session_unavailable` | remote-live session 不可用 | Artifact 足够→partial+continue；需采集→handoff；无 Artifact→blocked |
| `root_path_invalid` | offline root 不可识别 | blocked |
| `permission_insufficient` | 无法读取关键文件 | partial |
| `config_source_missing` | Web 配置文件缺失 | partial+continue |
| `log_source_missing` | 日志源缺失 | partial+continue |
| `route_mapping_incomplete` | 路由映射不完整 | partial+continue |
| `unsupported_framework` | 未识别的框架 | partial+continue |
| `parse_failure` | 日志或配置解析失败 | partial+continue |
| `timezone_uncertain` | 时区无法确定 | finding+continue |
| `output_limit_exceeded` | 输出超过限制 | partial |
| `evidence_conflict` | 证据之间矛盾 | finding+continue |
| `targeted_collection_required` | 需要额外远程采集 | `route_status`=active，handoff 返回 live-response |

失败本身不自动触发 `execution_gate`。

## Execution Gate

只有拟执行动作超出既有分析或 live-response scope 时触发：新增远程命令、权限提升、访问未批准路径、大规模采集、修改源检材、启动应用、安装依赖、主动利用漏洞、执行可疑文件、修改 Web 配置或日志。普通日志缺失、解析失败和权限不足不自动触发 `execution_gate`。

## Stop Conditions

只有以下情况停止整个 Skill：环境无法确认且无替代路径、没有任何可分析 Artifact、`evidence_scope` 不含任何可分析路径、route hop 超限、`execution_gate` 未解决。单个日志/配置/源码目录/Route 缺失只影响对应 Stage，不得阻断其他已有 Artifact 的分析。

## Investigation Summary

~~~markdown
## Investigation Summary

**Current Assessment**: <一句话总结 Web 服务状态和关键发现>

**Key Evidence**:
1. <组件/路由/入口点证据>
2. <日志/WebShell/Secret 证据>

**Excluded Routes** (if any): <排除的 domain 路线及依据>

**Route Plan**:
- <从 route_record.route_plan 渲染，不独立维护>
~~~

## Quality Checklist

- [ ] Frontmatter 只有 name 与 description
- [ ] 输入/输出使用当前 Request/Response Envelope
- [ ] 支持 `remote-live`、`rebuilt-vm`、`offline-image` 和 `source-package` 四种环境
- [ ] rebuilt-vm 统一通过 live-response 交接
- [ ] Artifact-first：优先分析已有 collection_artifact_refs
- [ ] Session 不可用时按 Artifact 可用性决定 partial/continue/blocked
- [ ] `large-artifact-strategy` 处理大日志/大源码树/大部署包
- [ ] `allowed_paths` 非 null 时限制在批准根路径内，解析规范路径后检查
- [ ] source-package 不在源 Artifact 内原地解压，拒绝绝对路径和路径穿越
- [ ] 每个关键 Finding 同时有 Artifact 和 Ledger Event 引用
- [ ] 负面 Finding 记录实际检查范围
- [ ] `detected_components` 使用 `artifact_refs` + `ledger_event_refs`，不使用 `source_refs`
- [ ] `webshell_candidate` 使用 `source_artifact_id`，不使用 `hash_ref`
- [ ] `execution_observed=true` 仅限直接执行证据
- [ ] `suspected_entrypoint` 整体可为 null，不强行选择
- [ ] `suspect_ip` 有归因依据，单个 X-Forwarded-For 不能直接成为 suspect_ip
- [ ] `access_log_findings` 包含 `redaction_applied`、`normalization_steps`、`client_ip_basis`
- [ ] `raw_path` 脱敏查询参数内的 Secret
- [ ] `normalization_steps` 记录每步解码/规范化操作
- [ ] `targeted_collection_request` 整体可为 null，非 null 时四字段必须存在
- [ ] Stage 6 需要 `include_access_log_analysis` + `include_route_analysis` 都为 true 才完整执行
- [ ] Stage 9 `unmatched` 仅限所有数据源均已实际检查
- [ ] Secret 搜索不把完整匹配行写入 stdout/stderr/Ledger/Summary
- [ ] `redacted_value` 为不可逆脱敏或 Fingerprint
- [ ] 不仅凭 HTTP 200 判断攻击成功
- [ ] 不默认信任 X-Forwarded-For
- [ ] 编码路径和解码路径同时保留
- [ ] 日志缺失不等于请求未发生
- [ ] WebShell 只做静态识别，不执行
- [ ] 不输出完整 Secret
- [ ] 源码与日志交叉验证覆盖 route/handler/upload/webshell/IP
- [ ] 证据冲突不选择性忽略
- [ ] reentry 时 route_status=active，handoff.status=pending
- [ ] execution_gate 仅在超出 scope 时 required
- [ ] 不硬编码本机路径
- [ ] access_log_findings 包含 attributed_client_ip
- [ ] client_ip_basis 与 attributed_client_ip 语义一致
- [ ] untrusted-forwarded 和 unknown 时 attributed_client_ip 为 null
- [ ] suspect_ip_basis 使用结构化证据引用
- [ ] suspected_entrypoint.first_seen 为 ISO8601|null
- [ ] data-contracts.md 8.6 使用完整闭合的 yaml 代码块
