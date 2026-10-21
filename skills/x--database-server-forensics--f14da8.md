---
name: database-server-forensics
description: 数据库取证。识别 MySQL、PostgreSQL、Redis、MongoDB、SQLite 实例和版本，分析数据目录、Dump、Snapshot、WAL/Binlog/Redo/AOF 事务日志、用户权限、业务数据和 Secret 暴露，执行经批准的只读查询，将 Web/Linux/Docker 证据交给对应专项 Skill。
---

# database-server-forensics

## Purpose

分析数据库实例、数据目录、导出文件和事务日志，识别数据库类型和版本、Schema 结构、用户权限、业务数据、Secret 暴露和攻击痕迹。支持五种访问模式：`online-query`、`offline-directory`、`dump-file`、`transaction-log`、`snapshot`。

每个关键 Finding 必须同时具有至少一个 Artifact 引用和至少一个 Ledger Event 引用（或有证据价值的命令输出）。只读查询必须通过 Query Safety Gate 验证。本 Skill 不修改数据库内容、不执行写操作、不启动证据数据库、不输出完整 Secret。

## Use When

- `remote-server-live-response` 已建立并批准的 DB client 会话
- `linux-server-forensics` 或 `webapp-server-forensics` 发现数据库配置或数据目录
- Router 或其他 Skill 交接 SQL dump、备份、Snapshot 或事务日志
- 需要分析 MySQL/PostgreSQL/Redis/MongoDB/SQLite 的数据、配置、用户和事务

## Do Not Use When

- 需要 Web 源码和请求链深度分析（交给 `webapp-server-forensics`）
- 需要 Linux 主机账号、sudo、cron、systemd 完整分析（交给 `linux-server-forensics`）
- 需要 Docker image/layer/volume 深度分析（交给 `docker-container-forensics`）
- 需要修改数据库内容、Schema、账号、权限或配置
- 需要执行 INSERT/UPDATE/DELETE/DDL/管理命令或脚本
- 需要恢复生产服务、启动证据数据库或执行证据内二进制
- 需要绕过权限、破解密码或进行暴力认证
- 需要无范围全库导出
- 需要生成最终报告

## Request Contract

遵循 templates/request-envelope.schema.json。`request.payload` 至少包含：

~~~yaml
environment:
  type: remote-live|rebuilt-vm|offline-image|artifact-package
  plan_id: string|null
  session_id: string|null
  connection_ids: array
  connection_results: array
  collection_artifact_refs: array
  root_artifact_ref: string|null
  root_path: string|null
  time_observation: object|null
database_scope:
  db_type_hint: mysql|postgresql|redis|mongodb|sqlite|unknown|null
  access_mode: online-query|offline-directory|dump-file|transaction-log|snapshot
  allowed_instances:
    - instance_scope_id: string
      connection_id: string
      instance_id: string
      db_type: mysql|postgresql|redis|mongodb|sqlite|unknown
      host: string
      port: integer
  allowed_objects:
    - object_scope_id: string
      database: string|null
      schema: string|null
      object_type: database|schema|table|view|collection|keyspace|key-pattern|metadata|other
      name: string
      match_mode: exact|prefix
  allowed_paths: array|null
  targeted_questions: array
  include_structure_analysis: boolean
  include_account_analysis: boolean
  include_business_data_analysis: boolean
  include_transaction_analysis: boolean
  include_secret_analysis: boolean
  max_query_rows: integer|null
  max_query_bytes: integer|null
  query_timeout_seconds: integer|null
  max_queries: integer|null
~~~

`allowed_instances` 和 `allowed_objects` 规则：

1. `online-query` 时 `allowed_instances` 必须非空
2. 每个 online query 必须指向一个明确的 `instance_scope_id`
3. `allowed_objects` 必须形成有限对象范围
4. `null`、缺失或空数组不得解释为"允许全部数据库或全部对象"
5. 空 `allowed_objects` 表示不允许执行对象数据查询；仅可执行项目策略明确批准的有限元数据查询
6. `match_mode=prefix` 只用于确有需要的 Redis key prefix 等场景，并继续受行数、字节数和查询次数限制
7. 不允许任意正则、无边界通配符或全库默认范围
8. offline 模式的文件范围继续由 `allowed_paths` 控制

null 限制必须从项目或案件策略解析为 `effective_max_query_rows`、`effective_max_query_bytes`、`effective_query_timeout_seconds`、`effective_max_queries`。如果请求和策略均无有效值：执行任何 online query 前 `blocked`。

`request.context` 携带：`route_record`、上游 findings、Artifact 和 Ledger 引用、live-response domain candidate、Web/Linux/Docker cross-domain candidate、`credential_reference`、已知实例/端口/数据目录/时区依据。

不得把实际凭据值写入 Request 副本、状态文件、命令行或 Ledger。

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
    type: remote-live|rebuilt-vm|offline-image|artifact-package
    plan_id: string|null
    session_id: string|null
  db_profile:
    db_type: mysql|postgresql|redis|mongodb|sqlite|unknown
    version: string|null
    instance_id: string|null
    server_timezone: string|null
    charset: string|null
    collation: string|null
    read_only_status: confirmed-read-only|reported-read-only|writable|unknown
    profile_artifact_refs: array
    ledger_event_refs: array
    confidence: high|medium|low
  access_mode: online-query|offline-directory|dump-file|transaction-log|snapshot
  data_sources:
    - source_id: string
      source_type: config|data-directory|dump|snapshot|binlog|wal|redo|undo|oplog|aof|rdb|audit-log|slow-query-log|general-log|other
      path: string
      availability: present|missing|partial|unreadable
      source_artifact_id: string|null
      coverage_start: string|null
      coverage_end: string|null
      timezone_hint: object|null
      gap_notes: array
  table_map:
    - object_id: string
      database: string|null
      schema: string|null
      name: string
      object_type: table|view|collection|index|keyspace|other
      estimated_rows: integer|null
      columns_or_fields: array
      artifact_refs: array
      ledger_event_refs: array
      confidence: high|medium|low
  query_plan:
    - query_id: string
      purpose: string
      db_type: mysql|postgresql|redis|mongodb|sqlite|unknown
      target_instance_scope_id: string
      target_object_scope_ids: array
      target_database: string|null
      query_template: string
      parameter_refs: array
      parser_id: string
      parsed_statement_types: array
      safety_status: pending|approved|rejected
      safety_basis: array
      expected_columns: array
      max_rows: integer
      max_bytes: integer
      timeout_seconds: integer
      attempt_count: integer
      termination_status: not-applicable|confirmed-stopped|may-still-be-running|unknown
      impact_level: low|medium|high
      status: pending|running|completed|partial|blocked|failed|skipped
  query_result_refs:
    - query_id: string
      output_artifact_id: string
      row_count: integer|null
      byte_count: integer
      truncated: boolean
      redaction_applied: boolean
      started_at: ISO8601
      ended_at: ISO8601
      ledger_event_refs: array
  account_findings:
    - account_id: string
      principal: string
      account_type: user|role|service-account|application-account|unknown
      authentication_method: string|null
      privilege_summary: array
      superuser_or_admin: boolean|null
      status: active|locked|expired|disabled|unknown
      artifact_refs: array
      finding_refs: array
      ledger_event_refs: array
      confidence: high|medium|low
  privilege_findings:
    - privilege_id: string
      principal: string
      scope: global|database|schema|table|collection|keyspace|unknown
      privilege: string
      grantable: boolean|null
      anomalous: boolean|null
      basis: array
      artifact_refs: array
      finding_refs: array
      ledger_event_refs: array
      confidence: high|medium|low
  business_data_findings:
    - finding_id: string
      data_category: account|transaction|order|message|audit|configuration|identifier|other
      database: string|null
      schema: string|null
      object_name: string
      selection_basis: array
      record_count: integer|null
      sample_artifact_id: string|null
      artifact_refs: array
      redaction_applied: boolean
      minimization_applied: boolean
      finding_refs: array
      ledger_event_refs: array
      confidence: high|medium|low
  secret_findings:
    - secret_id: string
      secret_type: password|token|api-key|connection-string|private-key|encryption-key|other
      source_path: string
      source_artifact_id: string
      key_or_field: string|null
      redacted_value: string
      exposure_context: string
      finding_refs: array
      ledger_event_refs: array
      confidence: high|medium|low
  transaction_findings:
    - transaction_id: string
      source_type: binlog|wal|redo|undo|oplog|aof|audit-log|other
      original_timestamp: string|null
      normalized_timestamp: ISO8601|null
      actor: string|null
      operation: string
      target: string|null
      transaction_identifier: string|null
      artifact_refs: array
      ledger_event_refs: array
      confidence: high|medium|low
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
  effective_limits:
    max_query_rows: integer
    max_query_bytes: integer
    query_timeout_seconds: integer
    max_queries: integer
  blockers: array
~~~

`targeted_collection_request` 整体允许为 null。非 null 时四个字段必须存在，只用于 `remote-server-live-response`。

不要在 payload 中新增 `output_hash`。查询结果 Hash 从 `output_artifact_id` 对应的 Artifact Record 获取。

`read_only_status` 语义：
- `confirmed-read-only`：通过可靠运行态设置或直接证据确认只读
- `reported-read-only`：仅由配置、声明或间接信息报告只读
- `writable`：已有证据表明实例可写
- `unknown`：无法可靠判断

`reported-read-only` 不等于 `confirmed-read-only`。`writable` 不代表允许写操作。即使实例为 `confirmed-read-only`，查询仍必须通过 Query Safety Gate。offline Artifact 一般不能据此断言当前运行实例状态。

## Ownership Boundary

| database-server-forensics 负责 | 不负责 |
|---|---|
| 数据库类型/版本/实例/时区/字符集识别 | Web 源码和请求链深度分析 |
| 数据目录/配置/Dump/Snapshot/事务日志映射 | Linux 主机账号/sudo/cron/systemd 完整分析 |
| Schema/表/集合/索引/视图结构识别 | Docker image/layer/volume 深度分析 |
| 用户/角色/权限/异常高权限账号分析 | 修改数据库内容/Schema/账号/权限/配置 |
| 经批准的只读查询计划与执行 | 执行 INSERT/UPDATE/DELETE/DDL/管理命令 |
| 查询结果 Artifact 化、Hash 和行数记录 | 恢复生产服务/启动证据数据库/执行证据内二进制 |
| 业务数据定位、最小化提取和脱敏 | 绕过权限/破解密码/暴力认证 |
| 数据库 Secret 位置识别 | 无范围全库导出 |
| 事务/审计/慢查询/数据库时间线候选分析 | 输出完整密码/Token/连接串/敏感业务数据 |
| 将 Web/Linux/Docker/Timeline 证据交给对应 Skill | 生成最终报告 |

## Access Modes

### online-query

由 `remote-server-live-response` 已建立并批准的 DB client 会话。规则：

- 只使用上游已批准的 `connection_id`、`session_id` 和 `credential_reference`
- 不建立新的网络路线
- 不切换到未批准主机、端口、实例或数据库
- 不修改凭据
- Session 不可用时不自行重新连接
- 需要重新连接或补充远程采集时，返回 `remote-server-live-response`
- 只允许经 Query Safety Gate 验证的只读查询

### offline-directory / dump-file / transaction-log / snapshot

- 不启动数据库服务
- 不执行证据目录中的数据库二进制或脚本
- 不修改源文件
- 不对源数据目录执行自动恢复、升级或格式迁移
- 需要转换时写入案件工作目录并登记派生 Artifact
- 保留原路径、文件大小、时间和源 Artifact 映射

上游映射：

| 上游来源 | 访问模式 |
|---|---|
| remote-server-live-response DB client 会话 | online-query |
| rebuilt runtime 经 live-response 建立的 DB client | online-query（保留 plan_id 和 rebuild Artifact） |
| Router/Linux/Docker/Web 交接的数据目录 | offline-directory |
| SQL/JSON/BSON/Redis/RDB/AOF 等导出或备份 | dump-file 或 snapshot |
| WAL/Binlog/Redo/Undo/Oplog/AOF 等 | transaction-log |

## Artifact-first

所有模式优先分析已有 Artifact。

- online session 不可用但已有 Artifact 足够：`partial` + continue
- 需要新的连接或额外远程采集：targeted collection handoff，`handoff.status` = `pending`，`route_status` = `active`
- Session 不可用且无任何可分析 Artifact：当前 step `blocked`，无继续路径时 `route_status` = `blocked`
- 单个配置、数据源或日志缺失：对应 Stage `partial`，其他 Stage 继续
- 大型 Dump、Snapshot、数据目录或事务日志：先调用 `large-artifact-strategy`

## Path Safety Rules

`allowed_paths` 非 null：所有读取和解析限制在批准根路径；先规范化路径，再验证仍位于批准根路径；不通过相对路径、符号链接、junction 或 reparse point 越界。

`allowed_paths` 为 null：从 `root_artifact_ref`、`root_path`、`collection_artifact_refs`、`data_sources` 和 `evidence_scope` 解析有限根；无法形成有限根时禁止递归扫描。

压缩 Dump、Snapshot 或备份：只解压到案件工作目录；拒绝绝对路径、`..` 路径穿越和越界符号链接；解压前检查文件数量、声明大小和展开规模；大包先走 `large-artifact-strategy`；派生文件登记 Artifact 并保留源映射。

## Analysis Scope Mapping

| scope 字段 | 对应 Stage | 始终执行 |
|---|---|---|
| — | Stage 1 Environment and Source Validation | 是 |
| — | Stage 2 Database Profile and Source Mapping | 是 |
| `include_structure_analysis` | Stage 3 Structure Mapping | 否 |
| `include_account_analysis` | Stage 4 Accounts and Privileges | 否 |
| `include_business_data_analysis` | Stage 5 Query Planning and Read-only Extraction（online-query） | 否 |
| `include_business_data_analysis` | Stage 6 Offline Data and Dump Analysis（非 online-query） | 否 |
| `include_transaction_analysis` | Stage 7 Transaction and Audit Analysis | 否 |
| `include_secret_analysis` | Stage 8 Secret and Configuration Exposure | 否 |
| — | Stage 9 Cross-source Validation and Handoff | 对已启用 Stage 的结果执行 |

Scope 为 `false`：Stage 标为 `skipped`，生成 `state-transition` event，不输出该范围"未发现异常"，Summary 说明未执行范围。

## Analysis Workflow

### Stage 1 — Environment and Source Validation

验证 `environment.type`、`access_mode`、Artifact 可用性、Session 状态、实例、路径、时区和 `database_scope`。不凭扩展名或目录名直接断言数据库类型。

### Stage 2 — Database Profile and Source Mapping

使用配置、文件头、系统目录、客户端元数据或 Artifact 判断数据库类型、版本和实例。记录时区、字符集、Collation、只读状态。

`read_only_status` 语义：
- `confirmed-read-only`：通过可靠运行态设置或直接证据确认只读
- `reported-read-only`：仅由配置、声明或间接信息报告只读，不等于 `confirmed-read-only`
- `writable`：已有证据表明实例可写，不代表允许写操作
- `unknown`：无法可靠判断

### Stage 3 — Structure Mapping

映射数据库、Schema、表、集合、索引、视图和 Keyspace。结构信息必须回指 Artifact 或安全查询结果。`estimated_rows` 不能伪装成精确行数。

### Stage 4 — Accounts and Privileges

分析用户、角色、认证方式、管理员权限和异常授权。不输出密码 Hash 或认证材料全文。`superuser_or_admin` 必须有权限证据支持。仅账号存在不能断言异常。

### Stage 5 — Query Planning and Read-only Extraction

（online-query 且 `include_business_data_analysis`）

先产生 `query_plan`；Query Safety Gate `approved` 后才执行；每个查询独立记录 command event；查询结果写入 Artifact；不把端口开放或登录成功当成业务查询成功。

### Stage 6 — Offline Data and Dump Analysis

（非 online-query 且 `include_business_data_analysis`）

静态解析 Dump、Snapshot、SQLite、数据目录副本。不启动服务；不在源目录执行恢复；不自动写回 WAL、Journal、Redo 或元数据；解析器失败时保留源 Artifact，记录 `parse_failure`。

### Stage 7 — Transaction and Audit Analysis

分析 Binlog、WAL、Redo、Undo、Oplog、AOF、审计和慢查询。区分事务提交、回滚、缺失和截断。日志缺失不等于事务未发生。原始时间和规范化时间同时保留。

### Stage 8 — Secret and Configuration Exposure

分析配置、连接文件、应用配置和备份中的 Secret 位置。只输出不可逆脱敏值或 Fingerprint。不输出私钥、密码、Token 或完整连接串。

### Stage 9 — Cross-source Validation and Handoff

交叉验证结构、查询、事务日志、账号权限和上游 Web/Linux/Docker 证据。`evidence_conflict` 必须记录。不选择性忽略不一致证据。

## Query Safety Gate

任何 online query 执行前必须通过 Query Safety Gate。

要求：

1. 使用对应数据库方言的解析器或结构化命令分类
2. 不能只用 startswith、正则前缀或字符串包含判断只读性
3. 禁止多语句拼接
4. 禁止未批准的注释混淆、动态 SQL 或存储过程调用
5. 禁止 Shell 管道、重定向和命令拼接
6. 禁止查询中包含明文密码、Token 或 Secret
7. 查询必须限制在 `allowed_instances` 和 `allowed_objects` 范围内
8. 每个查询必须设置 `max_rows`、`max_bytes` 和 `timeout_seconds`
9. 实际执行查询数不得超过 `effective_max_queries`
10. 查询结果达到行数或字节上限时安全截断并标记 `truncated` = `true`
11. 失败或超时不得无上限重试
12. online query 和数据库审计痕迹的 `impact_level` 至少为 `low`

### 参数化查询和 Ledger 记录

1. SQL 值使用数据库客户端的原生 bind parameter
2. MongoDB、Redis 等使用对应客户端的结构化参数机制
3. `parameter_refs` 只保存已批准参数记录、受保护 Artifact 或安全上下文的引用
4. 不在 `parameter_refs`、`query_template`、command、stdout 或 stderr 中写入密码、Token、私钥、完整连接串或无需公开的个人信息
5. 数据库名、Schema、表、集合、字段等标识符必须与 `allowed_objects` 精确匹配，再使用对应方言的安全引用或 quoting 机制
6. command Ledger Event 中记录精确的参数化 `query_template`、`parameter_refs`、`parser_id` 和 `query_id`
7. "exact query"指精确的参数化模板及其引用关系，不要求复制受保护参数明文
8. Ledger Event Schema 没有 `parameter_refs`、`parser_id` 或 `query_id` 字段时：不向 Ledger Event 发明字段；将这些信息放入 Query Plan/Query Execution Record Artifact；command event 通过 `output_artifact_refs` 或 `artifact_refs` 回指该 Artifact

### 服务器端工作量限制

1. 客户端截断不能单独视为查询安全措施
2. 支持时，查询必须使用数据库原生 LIMIT、cursor batch limit、projection、key prefix/range、bounded time range 或其他等价限制
3. Query Safety Gate 必须评估目标对象规模、过滤条件和潜在扫描范围
4. 对明显可能执行全表、全集合或全 keyspace 扫描的查询：默认 `rejected`；除非 targeted question 明确需要、且项目策略明确批准、且存在有效 timeout、字节限制和最小化方案
5. `SELECT COUNT(*)`、聚合或元数据查询也可能扫描大对象，不能因输出只有一行就自动判定安全
6. 如需查询计划评估：优先使用无执行副作用的 EXPLAIN 或等价机制；不默认使用 EXPLAIN ANALYZE；不执行会实际运行目标查询、更新统计或改变缓存/锁状态的分析命令
7. Redis 禁止使用无范围 `KEYS`；使用受限 SCAN、prefix 和 count 策略
8. MongoDB cursor、aggregation 和 find 必须有限制、projection 和批准对象范围
9. SQLite 查询只针对工作副本或只读/immutable 打开方式，不写入 WAL、Journal 或临时状态到源目录
10. 达到 `max_rows` 或 `max_bytes` 后：标记 `truncated` = `true`；不把截断结果解释为完整数据集；Investigation Summary 说明覆盖范围

### Bounded Query Execution Rules

1. 每次实际执行增加 `attempt_count`
2. 默认每个 query plan 只自动执行一次
3. 客户端 timeout 不证明服务器端查询已经停止
4. timeout 后设置：`status` = `partial` 或 `failed`，`termination_status` = `may-still-be-running` 或 `unknown`
5. 不得自动重新执行同一查询
6. 只有满足以下条件之一才允许新尝试：已可靠确认原查询停止、产生了新的范围更小的 query plan、收到明确的新 Handoff 或人工批准
7. 新尝试必须产生独立 command Ledger Event
8. 不得通过提高权限、取消限制、切换管理员账号或改成写操作处理超时
9. 如需执行取消查询、终止后端会话或 kill operation：视为独立动作，先判断是否超出 scope，必要时触发 `execution_gate`，不得默认自动执行

禁止的 SQL/数据库动作至少包括：INSERT、UPDATE、DELETE、MERGE、REPLACE、UPSERT、CREATE、ALTER、DROP、TRUNCATE、GRANT、REVOKE、COPY/LOAD/IMPORT、SELECT INTO OUTFILE、导出到服务器文件、SET 持久配置、VACUUM FULL、REINDEX、ANALYZE（会修改统计或产生明显影响时）、FLUSH、CHECKPOINT、SHUTDOWN、SCRIPT/EVAL、Redis 写命令、MongoDB 写操作、执行存储过程或用户函数、锁表或长事务、启动恢复/修复/升级。

允许的查询也必须经过方言级验证和范围限制。Redis 不能仅凭命令名称看起来像"读取"就放行；使用命令元数据和项目 allowlist 验证。MongoDB 查询不得包含服务端 JavaScript、写阶段或聚合输出阶段。SQLite 离线分析不得修改源数据库、WAL 或 Journal。

## Data Minimization

业务数据和查询结果遵循：

1. 只提取回答 `targeted_questions` 所需的字段和记录
2. 禁止默认 `SELECT *` 或全集合导出
3. 优先 COUNT、聚合、范围筛选和最小样本
4. 涉及个人信息、密码、Token、Cookie、证件号、手机号、地址、聊天内容或业务机密时进行脱敏
5. 完整结果确有取证需要时写入受保护 Artifact
6. 普通 Response、Ledger、stdout、stderr 和 Summary 只使用脱敏摘要或 Fingerprint
7. `query_template` 和 command 不得包含明文 Secret
8. `redaction_applied` 和 `minimization_applied` 必须反映实际处理
9. 不因脱敏修改源 Artifact

Secret 搜索不得将完整匹配行写入普通 stdout、stderr 或 Ledger。

## Time Handling

每个事务、账号变更、查询、业务记录和配置变化候选事件记录：`original_timestamp`、`normalized_timestamp` 或 null、timezone evidence、clock skew、time precision、source Artifact、confidence。不得无依据假设 UTC、+08:00 或数据库服务器本地时间。本 Skill 只生成 `timeline_candidates`，正式 Timeline Event 由 `timeline-reconstruction` 创建。

## Evidence Requirements

| Event type | Required use |
|---|---|
| command | 每个查询执行、配置解析、Dump 解析、事务日志解析 |
| artifact | 每个查询结果、结构映射、配置解析结果、事务分析结果 |
| finding | 每个关键判断（异常账号、高权限、业务数据、Secret、事务） |
| state-transition | 分析阶段完成/跳过/blocked |
| handoff | 交给 domain skills 或返回上游 |

遵循 templates/ledger-event.schema.json。每个关键 Finding 必须同时具有至少一个 Artifact 引用和至少一个 Ledger Event 引用（或有证据价值的命令输出）。Finding Record 的 `evidence_refs` 指向对应 Ledger Event。负面 Finding 必须记录实际检查范围；未检查的数据库、Schema、表、事务日志或时间范围不得输出"未发现异常"。

重点检查以下对象的证据引用：`db_profile`（`profile_artifact_refs` + `ledger_event_refs`）、`table_map`（`artifact_refs` + `ledger_event_refs`）、`account_findings`（`artifact_refs` + `finding_refs` + `ledger_event_refs`）、`privilege_findings`（`artifact_refs` + `finding_refs` + `ledger_event_refs`）、`business_data_findings`（`artifact_refs` + `sample_artifact_id` + `finding_refs` + `ledger_event_refs`）、`secret_findings`（`finding_refs` + `ledger_event_refs`）、`transaction_findings`（`artifact_refs` + `ledger_event_refs`）。

## Route and Handoff Rules

### Domain Handoff

| 发现类型 | 目标 skill |
|---|---|
| Web 请求、应用账号和 SQL 入口 | `webapp-server-forensics` |
| Linux 主机、数据目录权限和服务配置 | `linux-server-forensics` |
| Docker/Compose/container 数据卷 | `docker-container-forensics` |
| 多源时间事件 | `timeline-reconstruction` |
| 额外远程采集或重新连接 | `remote-server-live-response` targeted collection handoff |

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
| `unsupported_db_type` | 未识别的数据库类型 | blocked |
| `source_artifact_missing` | 所有关键输入和 Artifact 均缺失 | blocked |
| `session_unavailable` | online session 不可用 | Artifact 足够→partial+continue；需采集→handoff；无 Artifact→blocked |
| `connection_scope_mismatch` | 连接超出批准范围 | blocked |
| `credential_reference_missing` | online-query 且认证需要凭据时凭据引用缺失 | blocked（offline 模式或 authentication_method=none 时不因缺少凭据阻断） |
| `root_path_invalid` | 离线根路径不可识别 | blocked |
| `permission_insufficient` | 无法读取关键文件或执行查询 | partial |
| `config_source_missing` | 数据库配置文件缺失 | partial+continue |
| `data_source_missing` | 数据源缺失 | partial+continue |
| `transaction_log_missing` | 事务日志缺失 | partial+continue |
| `query_rejected` | 查询被 Safety Gate 拒绝 | finding+continue |
| `query_timeout` | 查询超时 | partial + no-auto-retry |
| `query_limit_exceeded` | 查询数超限 | partial |
| `output_limit_exceeded` | 输出超过限制 | partial |
| `parse_failure` | 解析失败 | partial+continue |
| `timezone_uncertain` | 时区无法确定 | finding+continue |
| `evidence_conflict` | 证据之间矛盾 | finding+continue |
| `targeted_collection_required` | 需要额外远程采集 | `route_status`=active，handoff 返回 live-response |

查询失败不得自动切换为写操作、管理员操作或无限重试。失败本身不自动触发 `execution_gate`。

## Execution Gate

以下动作必须触发 `execution_gate`：任何写查询、修改 Schema/账号/权限/配置、启动/停止/重启数据库、恢复/修复/升级/迁移数据库、创建锁/长事务/明显影响性能的查询、无范围全库导出、访问未批准实例/数据库/Schema/表/路径、权限提升、安装依赖、执行证据内程序、主动利用数据库漏洞、解密或破解凭据。普通日志缺失、解析失败、查询被拒绝和权限不足本身不自动触发 `execution_gate`。

## Stop Conditions

只有以下情况停止整个 Skill：环境或数据库类型无法确认且无替代路径、没有任何可分析 Artifact、`evidence_scope` 不含任何批准实例或路径、Query Safety Gate 无法形成有效限制、route hop 超限、`execution_gate` 未解决。单个数据库/表/日志/Dump/事务日志缺失只影响对应 Stage。

## Investigation Summary

~~~markdown
## Investigation Summary

**Current Assessment**: <一句话总结数据库状态和关键发现>

**Key Evidence**:
1. <实例/结构/账号证据>
2. <查询/业务数据/事务证据>

**Excluded Routes** (if any): <排除的 domain 路线及依据>

**Route Plan**:
- <从 route_record.route_plan 渲染，不独立维护>
~~~

## Quality Checklist

- [ ] Frontmatter 只有 name 与 description
- [ ] 输入/输出使用当前 Request/Response Envelope
- [ ] 支持 online-query/offline-directory/dump-file/transaction-log/snapshot 五种访问模式
- [ ] `allowed_instances` 结构化含 `instance_scope_id`/`connection_id`/`instance_id`/`db_type`/`host`/`port`
- [ ] `allowed_objects` 结构化含 `object_scope_id`/`database`/`schema`/`object_type`/`name`/`match_mode`
- [ ] 空 `allowed_objects` 不解释为允许全部对象
- [ ] online-query 只使用上游已批准的连接，不自行重新连接
- [ ] Artifact-first：优先分析已有 collection_artifact_refs
- [ ] `large-artifact-strategy` 处理大型 Dump/Snapshot/数据目录
- [ ] `allowed_paths` 非 null 时限制在批准根路径内
- [ ] Query Safety Gate 使用方言级解析，不只用字符串匹配
- [ ] 禁止多语句拼接、注释混淆、动态 SQL、存储过程、Shell 管道
- [ ] 禁止的 SQL 动作列表完整覆盖写操作和管理命令
- [ ] Redis/MongoDB/SQLite 有专用安全规则
- [ ] Redis 禁止无范围 `KEYS`，使用受限 SCAN
- [ ] 参数化查询使用 bind parameter，不在 Ledger/命令中写入 Secret
- [ ] 服务器端工作量限制：LIMIT/cursor/projection/bounded range
- [ ] 全表/全集合扫描默认 rejected
- [ ] `SELECT COUNT(*)`/聚合不因输出只有一行自动判定安全
- [ ] EXPLAIN 不默认使用 ANALYZE 变体
- [ ] `query_plan` 含 `target_instance_scope_id`/`target_object_scope_ids`/`parser_id`/`parsed_statement_types`/`attempt_count`/`termination_status`/`impact_level`
- [ ] `safety_status=approved` 同时有 parser_id/parsed_statement_types/safety_basis/target_instance_scope_id
- [ ] 每个查询设置 max_rows/max_bytes/timeout_seconds
- [ ] 查询结果达到上限时安全截断并标记 truncated
- [ ] `query_timeout` 默认 partial + no-auto-retry，不自动重执行
- [ ] timeout 后 `termination_status` 设为 `may-still-be-running` 或 `unknown`
- [ ] `read_only_status` 使用 `confirmed-read-only|reported-read-only|writable|unknown`
- [ ] `reported-read-only` 不等于 `confirmed-read-only`
- [ ] `credential_reference_missing` 仅适用于 online-query 且认证需要凭据
- [ ] `account_findings` 使用 `artifact_refs` 不使用 `source_artifact_ids`
- [ ] `business_data_findings` 含 `artifact_refs` 回指源表结构/查询结果/Dump
- [ ] 数据最小化：优先 COUNT/聚合/范围筛选/最小样本
- [ ] 涉及个人信息时脱敏，`redaction_applied` 和 `minimization_applied` 反映实际
- [ ] 每个关键 Finding 同时有 Artifact 和 Ledger Event 引用
- [ ] `superuser_or_admin` 有权限证据支持
- [ ] 不输出密码 Hash/认证材料/私钥/Token/完整连接串全文
- [ ] `output_hash` 不在 payload 中，Hash 从 Artifact Record 获取
- [ ] `targeted_collection_request` 整体可为 null
- [ ] reentry 时 route_status=active，handoff.status=pending
- [ ] execution_gate 仅在超出 scope 时 required
- [ ] 查询失败不自动切换为写操作或无限重试
- [ ] 不硬编码本机路径
