---
name: docker-container-forensics
description: Docker 容器取证。识别 Engine、Compose、Container、Image、Layer、Volume、Bind Mount、Network 和 Port 映射，分析容器配置安全、文件系统变化、日志、Secret 暴露和可疑载荷，将 Web/Database/Linux 证据交给对应专项 Skill。
---

# docker-container-forensics

## Purpose

分析 Docker Engine、Compose、Container、Image、Layer、Volume、Bind Mount、Network 和 Port 配置及元数据，识别容器安全风险、文件系统变化、日志异常、Secret 暴露和可疑载荷。支持四种访问模式：`live-daemon`、`offline-directory`、`image-archive`、`compose-project`。

每个关键 Finding 必须同时具有至少一个 Artifact 引用和至少一个 Ledger Event 引用（或有证据价值的命令输出）。本 Skill 不直接执行 Docker CLI 命令，不启动/停止/修改容器，不执行容器内文件，不输出完整 Secret。

## Use When

- `remote-server-live-response` 已建立并批准的 Docker 入口
- `linux-server-forensics` 发现 Docker data-root 或容器配置
- Router 或其他 Skill 交接 docker save、OCI archive、container export 或镜像包
- 需要分析 Compose/Dockerfile/.env、容器配置安全、镜像层、Volume、Network、日志

## Do Not Use When

- 需要深度 Web 源码分析（交给 `webapp-server-forensics`）
- 需要数据库业务数据分析（交给 `database-server-forensics`）
- 需要 Linux 主机账号/sudo/cron/systemd 完整分析（交给 `linux-server-forensics`）
- 需要启动/停止/重启/暂停/删除/修改容器
- 需要 docker run/exec/build/pull/push/commit/load/import/prune
- 需要修改镜像/Volume/Network/Compose/Daemon 配置
- 需要执行容器内文件、Entrypoint、Command 或脚本
- 需要主动利用容器逃逸或 Docker API 漏洞
- 需要生成最终报告

## Request Contract

遵循 templates/request-envelope.schema.json。以下代码块仅展示 `request.payload` fragment，不是完整 Request Envelope：

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
docker_scope:
  access_mode: live-daemon|offline-directory|image-archive|compose-project
  allowed_daemon_targets:
    - daemon_scope_id: string
      connection_id: string
      daemon_id: string
      host: string
      context_name: string|null
  allowed_container_ids: array
  allowed_image_refs: array
  allowed_volume_names: array
  allowed_network_names: array
  allowed_paths: array|null
  allowed_container_paths:
    - container_id: string
      path: string
      recursive: boolean
      max_depth: integer|null
  targeted_questions: array
  include_compose_analysis: boolean
  include_container_analysis: boolean
  include_image_analysis: boolean
  include_layer_analysis: boolean
  include_volume_analysis: boolean
  include_network_analysis: boolean
  include_log_analysis: boolean
  include_secret_analysis: boolean
  max_log_lines: integer|null
  max_log_bytes: integer|null
  max_archive_files: integer|null
  max_archive_expanded_bytes: integer|null
  max_objects: integer|null
~~~

`allowed_container_paths` 规则：container-copy-out 的 `container_id` 和 `source_path` 必须匹配一项。为 null/缺失/空数组时不允许 container-copy-out。`path` 必须是容器命名空间内的规范绝对路径。拒绝 `..` 路径穿越、规范化后越出、越界符号链接、设备文件、socket、FIFO。`recursive=false` 时只能复制明确文件；`recursive=true` 时必须有有限 `max_depth`、对象数量和输出字节上限。宿主机/案件工作目录继续由 `allowed_paths` 控制。

null 限制必须从项目或案件策略解析为 `effective_max_log_lines`、`effective_max_log_bytes`、`effective_max_archive_files`、`effective_max_archive_expanded_bytes`、`effective_max_objects`。请求和策略均无有效值时：live-daemon 的日志/event/大对象采集前 `blocked`；image archive 或大型离线目录展开前 `blocked`；已有小型 Artifact 的静态分析仍可继续。

范围规则：live-daemon 时 `allowed_daemon_targets` 必须非空；每项远程采集必须指向明确 `daemon_scope_id`；container/image/volume/network 范围不得将 null 或空数组解释为允许全部对象；空对象数组表示不允许采集或深度分析；仅 Daemon 基础元数据采集需要项目策略明确批准；offline 模式继续受 `allowed_paths` 和 `evidence_scope` 限制。

`request.context` 携带：`route_record`、上游 findings、Artifact 和 Ledger 引用、live-response domain candidate、Linux/Web/Database cross-domain candidate、已知 Docker 路径/容器/镜像/端口/Volume/时间依据、remote footprint。

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
  access_mode: live-daemon|offline-directory|image-archive|compose-project
  docker_profile:
    engine_version: string|null
    api_version: string|null
    storage_driver: string|null
    docker_root_dir: string|null
    rootless: boolean|null
    cgroup_driver: string|null
    logging_driver: string|null
    swarm_state: inactive|active|pending|unknown
    observation_mode: live|metadata-snapshot|inferred
    observed_at: ISO8601|null
    artifact_refs: array
    ledger_event_refs: array
    confidence: high|medium|low
  archive_profile:
    archive_format: docker-save|oci-layout|oci-archive|container-export|rootfs-tar|unknown
    flattened_filesystem: boolean|null
    manifest_present: boolean|null
    config_present: boolean|null
    layer_history_available: boolean|null
    source_artifact_id: string|null
    artifact_refs: array
    ledger_event_refs: array
    confidence: high|medium|low
  source_paths:
    - source_id: string
      source_type: docker-root|container-metadata|image-archive|oci-layout|compose-file|dockerfile|volume-data|container-log|daemon-event|other
      location_type: filesystem-path|artifact|daemon-api|logical|unknown
      path: string|null
      logical_location: string|null
      availability: present|missing|partial|unreadable
      source_artifact_id: string|null
      coverage_start: string|null
      coverage_end: string|null
      timezone_hint: object|null
      gap_notes: array
  compose_service_map:
    - service_id: string
      project_name: string|null
      service_name: string
      image_ref: string|null
      build_context: string|null
      dockerfile_path: string|null
      command_summary: string|null
      environment_keys: array
      env_file_paths: array
      volume_refs: array
      network_refs: array
      port_refs: array
      depends_on: array
      resolution_status: resolved|partial|unresolved
      unresolved_variables: array
      configured_user: string|null
      privileged: boolean|null
      capabilities_added: array
      capabilities_dropped: array
      security_opt: array
      pid_mode: string|null
      network_mode: string|null
      read_only: boolean|null
      restart_policy: string|null
      docker_socket_mount: boolean|null
      secret_refs: array
      config_refs: array
      artifact_refs: array
      ledger_event_refs: array
      confidence: high|medium|low
  container_map:
    - container_id: string
      name: string|null
      image_ref: string|null
      image_id: string|null
      state: created|running|paused|restarting|exited|dead|unknown
      state_observation: live|metadata-snapshot|inferred
      security_observation_status: complete|partial|unobserved
      security_gap_notes: array
      created_at: ISO8601|null
      started_at: ISO8601|null
      finished_at: ISO8601|null
      restart_policy: string|null
      privileged: boolean|null
      configured_user: string|null
      capabilities_added: array
      capabilities_dropped: array
      security_opt: array
      pid_mode: string|null
      network_mode: string|null
      readonly_rootfs: boolean|null
      docker_socket_mount: boolean|null
      mount_refs: array
      network_refs: array
      port_refs: array
      log_source_refs: array
      artifact_refs: array
      ledger_event_refs: array
      confidence: high|medium|low
  image_map:
    - image_id: string
      repo_tags: array
      repo_digests: array
      created_at: ISO8601|null
      architecture: string|null
      os: string|null
      config_entrypoint: array
      config_cmd: array
      exposed_ports: array
      layer_refs: array
      identity_basis: engine-image-id|manifest-digest|repo-digest|tag-only|unknown
      source_artifact_id: string|null
      artifact_refs: array
      ledger_event_refs: array
      confidence: high|medium|low
  layer_map:
    - layer_id: string
      digest: string|null
      diff_id: string|null
      parent_layer_id: string|null
      order_index: integer|null
      media_type: string|null
      size_bytes: integer|null
      source_artifact_id: string|null
      whiteout_entries: array
      opaque_directories: array
      artifact_refs: array
      ledger_event_refs: array
      confidence: high|medium|low
  filesystem_changes:
    - change_id: string
      container_id: string|null
      path: string
      change_type: added|modified|deleted|opaque-directory|unknown
      change_source: image-layer|runtime-upper|volume|bind-mount|metadata|unknown
      layer_id: string|null
      source_artifact_id: string
      artifact_refs: array
      ledger_event_refs: array
      confidence: high|medium|low
  volume_map:
    - volume_id: string
      name: string|null
      volume_kind: named|anonymous|tmpfs|other|unknown
      management_scope: docker-managed|external|unknown
      driver: string|null
      mountpoint: string|null
      container_ids: array
      destination_paths: array
      observation_mode: live|configured|metadata-snapshot|inferred
      basis: array
      source_artifact_id: string|null
      data_hints: array
      artifact_refs: array
      ledger_event_refs: array
      confidence: high|medium|low
  bind_mount_map:
    - mount_id: string
      source_path: string
      destination_path: string
      read_only: boolean|null
      propagation: string|null
      container_ids: array
      observation_mode: live|configured|metadata-snapshot|inferred
      basis: array
      source_artifact_id: string|null
      artifact_refs: array
      ledger_event_refs: array
      confidence: high|medium|low
  network_map:
    - network_id: string
      name: string|null
      driver: string|null
      scope: local|swarm|global|unknown
      internal: boolean|null
      attachable: boolean|null
      subnets: array
      gateways: array
      container_ids: array
      observation_mode: live|configured|metadata-snapshot|inferred
      basis: array
      artifact_refs: array
      ledger_event_refs: array
      confidence: high|medium|low
  port_map:
    - mapping_id: string
      service_id: string|null
      container_id: string|null
      protocol: tcp|udp|sctp|unknown
      container_port: integer
      host_ip: string|null
      host_port: integer|null
      mapping_type: published|exposed-only|host-network|unknown
      observation_mode: live|configured|metadata-snapshot|inferred
      basis: array
      artifact_refs: array
      ledger_event_refs: array
      confidence: high|medium|low
  log_source_map:
    - source_id: string
      container_id: string|null
      driver: json-file|local|journald|syslog|fluentd|gelf|awslogs|splunk|etwlogs|none|other
      path: string|null
      availability: present|missing|partial|remote-only|unreadable
      coverage_start: string|null
      coverage_end: string|null
      timezone_hint: object|null
      source_artifact_id: string|null
      gap_notes: array
  log_findings:
    - finding_id: string
      container_id: string|null
      original_timestamp: string|null
      normalized_timestamp: ISO8601|null
      stream: stdout|stderr|event|daemon|application|unknown
      message_redacted: string
      indicators: array
      truncated: boolean
      artifact_refs: array
      ledger_event_refs: array
      confidence: high|medium|low
  secret_findings:
    - secret_id: string
      secret_type: password|token|api-key|registry-credential|private-key|connection-string|cookie-secret|encryption-key|other
      source_path: string|null
      source_location: string
      source_artifact_id: string
      key_or_field: string|null
      redacted_value: string
      exposure_context: compose|dockerfile|environment|image-history|container-config|registry-config|log|volume|other
      finding_refs: array
      ledger_event_refs: array
      confidence: high|medium|low
  suspicious_artifacts:
    - candidate_id: string
      path: string|null
      source_location: string
      origin: image-layer|runtime-upper|volume|bind-mount|container-log|container-config|other
      source_artifact_id: string
      indicators: array
      execution_observed: boolean|null
      artifact_refs: array
      finding_refs: array
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
        actions:
          - action_id: string
            action_type: daemon-version|daemon-info|container-inspect|image-inspect|volume-inspect|network-inspect|container-logs|daemon-events|container-diff|container-copy-out|image-history|compose-config
            daemon_scope_id: string
            connection_id: string
            object_type: daemon|container|image|volume|network|compose-project
            object_ref: string|null
            source_path: string|null
            since: ISO8601|null
            until: ISO8601|null
            max_lines: integer|null
            max_objects: integer|null
            max_output_bytes: integer
            purpose: string
            impact_level: low|medium|high
            sensitive_output_expected: boolean
            capture_mode: standard-artifact|protected-raw-and-redacted-derivative|redacted-only
            expected_footprint: array
        paths:
          - action_id: string
            path_role: container-source|remote-host-source
            path: string
        max_output_bytes: integer|null
        reason: string
  effective_limits:
    max_log_lines: integer
    max_log_bytes: integer
    max_archive_files: integer
    max_archive_expanded_bytes: integer
    max_objects: integer
  blockers: array
~~~

`targeted_collection_request` 整体允许为 null。非 null 时四个顶层字段全部存在。

`archive_profile` 在非归档模式允许整体为 null。

`cross_domain_candidates.skill` 只允许填写当前已实现的 `webapp-server-forensics`、`database-server-forensics`、`linux-server-forensics`、`timeline-reconstruction` 或 `remote-server-live-response`。可疑脚本、二进制和载荷保存在 `suspicious_artifacts`、Layer/Volume Finding 或其他本 Skill 证据结构中，并记录需要后续专项分析；不得为其创建未实现 Skill 的 Route Step、Handoff 或 cross-domain target。

`source_paths.path` 可以为 null：无真实文件路径时（daemon API、container config、image history、remote log、逻辑对象）`path=null`，`logical_location` 提供脱敏后的逻辑位置（如 `container-config:<container-id>`、`image-history:<image-id>`）。`logical_location` 不得包含完整 Secret。注意：`source_paths` 使用 `logical_location`，而 `secret_findings` 和 `suspicious_artifacts` 使用 `source_location`，两者不得混淆。

`secret_findings.source_path` 可以为 null，`source_location` 为脱敏逻辑位置。`suspicious_artifacts.path` 可以为 null，`source_location` 为脱敏逻辑位置。不得把 URI、对象标签或描述伪装成文件路径。`location_type=artifact` 时必须有 `source_artifact_id`。

## Ownership Boundary

| docker-container-forensics 负责 | 不负责 |
|---|---|
| Engine/Compose/存储驱动/日志驱动识别 | 启动/停止/重启/暂停/删除/修改容器 |
| Container/Image/Layer/Volume/Bind Mount/Network/Port 映射 | docker run/exec/build/pull/push/commit/load/import/prune |
| Compose Service 与容器/镜像/挂载/网络关联 | 修改镜像/Volume/Network/Compose/Daemon 配置 |
| Dockerfile/Compose/镜像配置/容器元数据静态分析 | 将证据目录挂载到活动 Docker Daemon |
| 镜像层/运行时 upper layer/whiteout/文件系统变化分析 | 执行容器内文件/Entrypoint/Command/脚本 |
| 容器日志/Docker event/时间线候选分析 | 直接进入容器运行命令 |
| privileged/capabilities/security_opt/host network/PID/Socket/危险挂载分析 | 深度 Web/Database/Linux 分析 |
| 环境变量/Compose/Docker 配置/镜像历史中的 Secret 定位 | 主动利用容器逃逸或 Docker API 漏洞 |
| 容器内 Web/Database/Linux 数据定位 | 输出完整 Secret |
| 可疑脚本/二进制/持久化载荷静态候选识别 | 生成最终报告 |

## Access Modes

### live-daemon

由 `remote-server-live-response` 已建立并批准的 Docker 入口。规则：

- 只使用上游批准的 `session_id`、`connection_id` 和 daemon target
- 优先分析已有 `collection_artifact_refs`
- 本 Skill 不自行建立新连接，不直接执行 docker 命令
- 需要 inspect、logs、events、diff、copy-out 或其他采集时，生成 targeted collection handoff 返回 `remote-server-live-response`
- 不使用 docker exec 进行领域分析，不启动已停止容器，不修改 Daemon/容器/镜像/Volume/Network

### offline-directory

- 不启动 Docker Daemon 指向证据目录，不把证据目录作为 Docker data-root
- 不挂载 overlay upperdir 或 writable layer 为可写，不修改 overlay2/containerd/volumes/metadata 文件
- 重建文件系统视图时使用案件工作副本
- 保留源路径、层顺序、whiteout 和 Artifact 映射

### image-archive / compose-project

- 不执行 Entrypoint、CMD、脚本或二进制，不 build/load/import/run 镜像
- 只在案件工作目录安全解包，派生文件登记 Artifact，不安装依赖或启动项目
- `archive_profile` 必须区分 docker-save/OCI（含 manifest/config/layer）与 container-export/rootfs-tar（扁平文件系统，无 layer history）
- container-export 和 rootfs-tar：`flattened_filesystem=true`、`layer_history_available=false`，不得伪造 layer order、diff ID、RepoDigest 或镜像历史
- 单个 rootfs tar 不得仅凭目录结构被断言为 docker save archive

上游映射：

| 上游来源 | 访问模式 |
|---|---|
| remote-server-live-response Docker 入口 | live-daemon |
| rebuilt runtime 经 live-response 建立的 Docker 入口 | live-daemon（保留 plan_id、runtime_instance 和 rebuild Artifact） |
| Router/Linux Skill 交接的 Docker 数据目录 | offline-directory |
| docker save、OCI archive | image-archive |
| container export、rootfs tar | image-archive（archive_profile 区分扁平格式） |
| Compose、Dockerfile、.env 和部署目录 | compose-project |

## Artifact-first

所有模式优先分析已有 Artifact。

- live-daemon Session 不可用但 Artifact 足够：`partial` + continue
- 需要新命令、日志、event、inspect 或 copy-out：targeted collection handoff，`handoff.status` = `pending`，`route_status` = `active`
- Session 不可用且无任何可分析 Artifact：当前 step `blocked`，无继续路径时 `route_status` = `blocked`
- 单个容器、镜像、日志、Volume 或配置缺失：对应 Stage `partial`，其他 Stage 继续
- 大镜像、大 Layer、大 Volume、大日志或大型归档：先调用 `large-artifact-strategy`

## Live Daemon Collection Safety

本 Skill 不直接执行 Docker CLI。所有新增 live-daemon 采集返回 `remote-server-live-response`。

允许申请的低影响采集动作必须：指向批准 `daemon_scope_id`；指向批准 container/image/volume/network 范围；有明确 purpose；有日志行数、字节数、时间范围或对象数量上限；记录预期 Docker audit、daemon event、进程和文件访问 footprint。

可申请但必须有明确范围的动作：daemon/version/info 基础元数据、container/image/volume/network inspect、bounded container logs、bounded Docker events、bounded docker diff、container 文件 copy-out、image/config/history 元数据、Compose config 静态结果。

默认禁止申请或执行：docker run、docker exec、docker start/stop/restart/pause/unpause/kill、docker rm/rmi、docker build、docker pull/push、docker commit、docker load/import、docker prune、docker cp 写入容器、修改 label/network/volume/restart policy 或 daemon config、`docker logs --follow`、无界 `docker events`、无界日志/对象/文件系统导出。

`docker logs` 必须使用批准的 container ID、`--tail`、`--since`/`--until` 和输出字节上限。`docker events` 必须有有限 `--since` 和 `--until`，不得持续跟随。copy-out 只允许容器到本地案件工作目录；不覆盖已有 Artifact；路径必须位于 `allowed_container_paths` 批准范围；大文件先走 `large-artifact-strategy`；记录源容器、源路径、方法、大小和 Hash。

### Sensitive Output Protection

container inspect、image inspect、compose config、image history、logs 和 events 可能包含完整环境变量、Token、Registry 信息、Cookie、Authorization 或连接串。`sensitive_output_expected=true` 时：不把原始内容直接写普通 stdout/stderr/Ledger/Summary；原始结果进入受访问控制的 protected raw Artifact；生成独立的 redacted derivative Artifact；普通分析只引用脱敏派生 Artifact；protected raw Artifact 仍保留来源、Hash 和采集映射。`capture_mode=redacted-only` 只能在案件策略明确不需要保留原始输出时使用。`capture_mode=standard-artifact` 仅用于预期不包含敏感信息的输出（如 daemon-version），输出仍必须登记 Artifact、Hash 和来源，不能用于 inspect/compose-config/image-history/logs/events 等默认可能包含 Secret 的动作，除非已有明确字段级过滤方案。`sensitive_output_expected=false` 时可使用 `standard-artifact`，也可在风险不确定时使用 `protected-raw-and-redacted-derivative`。采集过程中意外发现 Secret 时：立即停止向普通 stdout/stderr/Ledger/Summary 写入原文；将输出重新分类为 protected raw Artifact；生成 redacted derivative Artifact；更新 action 或采集结果中的敏感输出状态；不得因请求最初填写 false 而继续公开完整内容。command Ledger Event 记录动作类型和 Artifact 引用，不复制完整敏感输出。`message_redacted`、`command_summary`、`logical_location`、`source_location` 均不得泄露完整 Secret。

### Targeted Collection Action Validation

`targeted_collection_request` 非 null 时的机器可校验规则：

1. **请求级**：actions 必须非空；reason 必须非空；每个 `action_id` 在当前请求内唯一；不允许将任意 Docker CLI 字符串直接作为 action；`remote-server-live-response` 只能根据 `action_type` 映射到批准的采集模板。

2. **daemon_scope_id 和 connection_id**：`daemon_scope_id` 必须引用 `request.payload.docker_scope.allowed_daemon_targets.daemon_scope_id`；`connection_id` 必须等于同一 daemon target 中记录的 `connection_id`；不允许跨 daemon 拼接。

3. **action_type 与对象范围**：

| action_type | object_type | object_ref 要求 |
|---|---|---|
| daemon-version / daemon-info | daemon | null |
| container-inspect / container-logs / container-diff / container-copy-out | container | 必须存在于 `allowed_container_ids` |
| image-inspect / image-history | image | 必须存在于 `allowed_image_refs` |
| volume-inspect | volume | 必须存在于 `allowed_volume_names` |
| network-inspect | network | 必须存在于 `allowed_network_names` |
| compose-config | compose-project | `source_path` 非 null，位于 `allowed_paths` 或 `evidence_scope` 内 |

null/缺失/空的批准对象数组不得解释为允许全部对象。

4. **container-logs**：`max_lines` 正整数；`since`/`until` 有效 ISO8601 且 since 早于 until；`max_output_bytes` 正整数；禁止 follow；达到限制时停止并标记 truncated。

5. **daemon-events**：`since`/`until` 均非 null 且 since 早于 until；`max_objects`/`max_output_bytes` 正整数；禁止持续跟随。

6. **container-diff**：`max_objects` 正整数；`max_output_bytes` 正整数；必须评估文件系统遍历范围；大型容器不得默认 `impact_level=low`。

7. **container-copy-out**：`object_ref` 匹配 `allowed_container_paths.container_id`；`source_path` 位于批准路径内；`recursive=false` 只复制明确文件；`recursive=true` 时 `max_depth`/`max_objects`/`max_output_bytes` 均为正整数；不允许写回容器或覆盖已有 Artifact；拒绝设备文件/socket/FIFO/越界符号链接。

8. **输出限制关系**：`action.max_output_bytes` 不得超过 `targeted_collection_request.max_output_bytes`；container-logs 的限制不超过 effective limits；所有对象型动作的 `max_objects` 不超过 `effective_max_objects`；`targeted_collection_request.max_output_bytes` 为 null 时不允许执行需要输出的 action；达到限制后安全停止。

9. **impact_level 语义**：`low`（有限只读元数据，规模较小）、`medium`（有限日志/较大 inspect/受限 diff，可能明显 I/O）、`high`（大型遍历/大文件/递归复制/未知规模）。daemon-version 通常至少 `low`；container-diff 必须根据容器规模判断；container-copy-out 根据文件大小/递归/max_depth/max_objects 判断。`expected_footprint` 必须解释依据。超出 scope 时不执行。不向 Ledger Event 添加 `impact_level`；保存在 Action Record 或分析 Artifact 中。

10. **paths 结构**：`action_id` 引用同一 `actions.action_id`；container-copy-out 必须有 `path_role=container-source`；compose-config 必须有 `path_role=remote-host-source`；两类路径不得混淆；paths 不保存本地输出路径。

## Path and Archive Safety

`allowed_paths` 非 null：所有读取、搜索、解析和派生操作限制在批准根路径；规范化后验证仍位于批准根路径；不通过相对路径、符号链接、junction 或 reparse point 越界。

`allowed_paths` 为 null：从 `root_artifact_ref`、`root_path`、`collection_artifact_refs`、`source_paths` 和 `evidence_scope` 解析有限根；无法形成有限根时禁止递归扫描。

归档解包安全规则：

1. 只解压到案件工作目录
2. 拒绝绝对路径、`..` 路径穿越、越界符号链接
3. 拒绝越出解包根目录的硬链接目标
4. 拒绝 socket、FIFO、字符设备和块设备
5. 规范化路径后检查重复条目
6. 在 Windows 案件工作目录中检查大小写折叠冲突
7. 不允许后续条目覆盖已生成的派生 Artifact
8. 识别并限制 sparse file 的实际展开规模
9. 文件数量上限按实际处理的 archive entry 计数
10. 展开字节上限按实际写入字节计数
11. 达到限制前安全停止，不先完整展开再检查
12. 生成 archive-entry manifest Artifact，记录：原始条目名、规范路径、entry type、声明大小、实际写入大小、跳过或拒绝原因、源归档 Artifact
13. `partial`/`truncated` 结果不得支持完整性负面结论

派生文件登记 Artifact 并保留源映射。

## Analysis Scope Mapping

| scope 字段 | 对应 Stage | 始终执行 |
|---|---|---|
| — | Stage 1 Environment and Source Validation | 是 |
| — | Stage 2 Docker Profile and Source Mapping | 是 |
| `include_compose_analysis` | Stage 3 Compose and Deployment Mapping | 否 |
| `include_container_analysis` | Stage 4 Container Configuration and Security | 否 |
| `include_image_analysis` / `include_layer_analysis` | Stage 5 Image, Layer and Filesystem Analysis | 否 |
| `include_volume_analysis` | Stage 6 Volume and Bind Mount Analysis | 否 |
| `include_network_analysis` | Stage 7 Network and Port Analysis | 否 |
| `include_log_analysis` | Stage 8 Logs, Events and Timeline | 否 |
| `include_secret_analysis` | Stage 9 Secrets（仅 Secret 搜索） | 否 |
| — | Stage 10 Cross-source Validation and Handoff | 对已启用 Stage 的结果执行 |

Scope 为 `false`：Stage 标为 `skipped`，生成 `state-transition` event，不输出该范围"未发现异常"，Summary 说明未执行范围。

Suspicious artifact 候选不依赖 `include_secret_analysis`：可由已启用的 Compose、Container、Image、Layer、Volume、Bind Mount 或 Log Stage 产生；只基于已批准且已实际分析的范围；不得为了寻找可疑载荷而额外扩大扫描范围。`include_secret_analysis=false` 时：不执行额外 Secret 搜索；不妨碍已启用 Stage 生成静态 `suspicious_artifacts` candidate。

## Analysis Workflow

### Stage 1 — Environment and Source Validation

验证 `environment.type`、`access_mode`、Artifact、live Session、`daemon_scope_id`、allowed object scope、root/source path、time range、effective limits。`image-archive` 模式必须识别归档格式并填充 `archive_profile`。不得仅凭目录名、文件扩展名或镜像标签断言 Docker 类型和版本。

### Stage 2 — Docker Profile and Source Mapping

使用 daemon metadata、Docker data-root metadata、OCI manifest/index、image config、Compose 文件、Artifact 文件头识别 Engine/API version、storage driver、data-root、rootless、cgroup driver、logging driver、Swarm 状态。记录 `observation_mode` 和 `observed_at`。offline Artifact 不得被描述成当前实时 Daemon 状态。`archive_profile` 为 container-export 或 rootfs-tar 时：`flattened_filesystem=true`、`layer_history_available=false`，不得伪造 layer order 或镜像历史。

### Stage 3 — Compose and Deployment Mapping

分析 compose.yaml/docker-compose.yml、override 文件、project/service、image/build context、Dockerfile、Entrypoint/CMD、environment key、env_file、ports、volumes、networks、depends_on、privileged、capabilities、security_opt、pid/network mode、Docker socket 挂载。

规则：Compose 多文件合并顺序必须有证据；未解析的环境变量替换必须标记 `unresolved`（`resolution_status` 非 `resolved` 时 `unresolved_variables` 必须列出）；不将未解析变量擅自填入宿主机当前环境值；`command_summary` 和环境变量值必须脱敏；只记录 environment key，Secret 值进入受保护 Artifact 或脱敏 Finding；`docker_socket_mount=true` 表示存在相关挂载配置，不自动证明容器已利用 Docker socket；`secret_refs`/`config_refs` 只保存引用，不保存完整 Secret 值。

### Stage 4 — Container Configuration and Security

分析 image、`image_id`（不可变镜像身份）、state observation、restart policy、configured user、privileged、added capabilities、dropped capabilities、security_opt、host PID/network、readonly rootfs、Docker socket mount、mounts、published ports。

规则：`metadata-snapshot` 或 `inferred` 状态不得写成当前 live 状态；`privileged=true` 只表示高风险配置，不自动证明容器逃逸；Docker socket 挂载是高风险证据，需要记录路径和权限；`docker_socket_mount=true` 必须有 mount_refs、Artifact 和 Ledger 证据，true 只表示存在挂载不证明已被利用，false 只有在完整检查相关 Mount/Binds 范围后允许，无法判断时为 null；`capabilities_dropped` 来自当前 Daemon inspect 或可靠容器元数据，空数组只能表示已检查且未配置额外 drop，未检查时不得用空数组伪装完整结论；不执行容器来验证配置；`image_id` 非 null 时应能关联 `image_map.image_id`；只有 tag 而无法解析镜像身份时 `image_id=null`；可变 tag 不能单独作为强镜像身份结论。

**Container Security 覆盖状态**：

- `security_observation_status=complete`：已检查 Config、HostConfig、Mounts/Binds、CapAdd/CapDrop、SecurityOpt、PidMode、NetworkMode、ReadonlyRootfs 和 Docker Socket 挂载。`security_gap_notes` 应为空；空数组可以表示已检查且未配置；`docker_socket_mount=false` 可以支持“完整检查后未发现挂载”的结论。
- `security_observation_status=partial`：只检查了部分来源或部分字段。`security_gap_notes` 必须非空。不得输出“未添加危险能力”“未挂载 Docker Socket”等完整负面结论。
- `security_observation_status=unobserved`：尚未执行容器安全配置检查。安全数组为空或布尔值为 false 时不得解释为不存在；对应范围必须记录为 skipped、not-applicable 或 gap。
- `docker_socket_mount=false` 只允许在 `security_observation_status=complete` 时作为负面结论。
- `capabilities_added`、`capabilities_dropped`、`security_opt` 为空数组时：complete 表示已检查且为空；partial/unobserved 时不能解释为未配置。

### Stage 5 — Image, Layer and Filesystem Analysis

分析 OCI/Docker manifest、config、RepoTags/RepoDigests、layer order、diff IDs、image history、Entrypoint/CMD、exposed ports、files added/modified/deleted、runtime upper layer。`archive_profile` 为 container-export/rootfs-tar 时只能输出扁平文件系统和可验证元数据。

whiteout 规则：`.wh.<name>` 表示后续视图中的删除语义；`.wh..wh..opq` 表示 opaque directory；必须按 manifest/config 指定的层顺序重建；不能仅凭最终视图缺少文件就断言文件从未存在；不能把 whiteout 文件当成普通业务文件；截断或缺少 Layer 时只能输出 partial 结论。

Hash：Layer digest、diff ID 和 image digest 保留各自语义；不把 Registry digest、压缩 Layer digest、diff ID 和本地 Artifact Hash 混为一谈；本地文件完整性从 Artifact Record 获取。`identity_basis` 标识镜像身份依据：`tag-only` 只能作为可变定位信息；无可靠不可变身份时不得强行关联多个同名 tag。

### Stage 6 — Volume and Bind Mount Analysis

区分 named volume、bind mount、tmpfs、anonymous volume、Docker managed volume。规则：mountpoint 是宿主机路径证据，不能直接当成容器内路径；bind source 和 container destination 分开记录；tmpfs 数据可能不存在于静态 Artifact；Volume 数据中的 Web/Database/Linux 证据分别建立 cross-domain candidate；不将 Volume 挂载到活动容器进行分析；大 Volume 先走 `large-artifact-strategy`。

**volume_kind**：`named`（明确名称的命名卷）、`anonymous`（Docker 创建但无稳定用户定义名称）、`tmpfs`（内存文件系统，静态 Artifact 中可能无数据内容）、`other`/`unknown`（其他或证据不足，必须说明 basis）。

**management_scope**：`docker-managed`（Docker 管理宿主机存储位置）、`external`（Docker 外部或外部系统管理）、`unknown`（无法可靠判断）。不得仅根据 mountpoint 目录名称判断。

**observation_mode**（volume_map 和 bind_mount_map 统一）：`live`（当前批准 Daemon 运行态证据，container_ids 必须引用 `container_map.container_id`）、`configured`（Compose 或静态配置，不证明已创建或当前挂载）、`metadata-snapshot`（离线或历史容器元数据，不代表当前状态）、`inferred`（多项间接证据推断，basis 必须非空）。configured/metadata-snapshot/inferred 不得写成当前实时挂载。`volume_map.mountpoint` 是宿主机侧位置；`destination_paths` 是容器侧位置。`bind_mount_map.source_path` 是宿主机路径；`destination_path` 是容器路径。宿主机路径和容器路径不得混用。tmpfs 缺少静态数据文件时只能记录证据缺口，不得断言其中从未存在数据。`basis` 至少说明证据来源类型、对应 Artifact 和直接观察或推断依据。

### Stage 7 — Network and Port Analysis

区分 exposed port、published port、host network、internal network、bridge/overlay/macvlan 等 Driver、host_ip/host_port/container_port。记录 `observation_mode`。`port_map` 中 `service_id` 引用 `compose_service_map.service_id`，`container_id` 引用 `container_map.container_id`，两者至少一个非 null。`observation_mode=configured` 必须有 `service_id`，`container_id` 可以为 null，不得描述为已实际发布或当前可达；`observation_mode=live` 必须有 `container_id`；Compose 中只有 EXPOSE 时 `mapping_type=exposed-only`、`host_port` 通常为 null。规则：EXPOSE 只表示镜像元数据，不等于端口已发布；published port 不等于服务认证成功或攻击成功；offline 配置不证明端口当前可达；代理、NAT 和多网络连接必须保留证据来源。不得把 configured、metadata-snapshot 或 inferred 描述为当前实时状态。

**Network/Port basis 规则**：所有 network_map 和 port_map 条目都应记录 basis。`observation_mode=inferred` 时 basis 必须非空。basis 应引用 Compose/Dockerfile 配置、Container metadata、Daemon inspect 结果、Network inspect 结果、Port mapping Artifact 或其他可验证证据。`observation_mode=live` 必须来自当前批准 Daemon，port_map 必须有非 null container_id，basis 必须指向运行态 Artifact 或 Ledger Event。`observation_mode=configured` 来源于 Compose/Dockerfile/静态配置，port_map 必须具有 service_id，不得描述为端口已实际发布或当前可达。`observation_mode=metadata-snapshot` 来源于历史或离线容器元数据，不得描述为当前状态。空 basis 不得支持网络当前连接、端口当前发布、服务当前可达、认证成功或攻击成功的结论。

### Stage 8 — Logs, Events and Timeline

分析 json-file、local、journald、syslog、fluentd、gelf、awslogs、splunk、Windows etwlogs、daemon event、应用 stdout/stderr。

规则：remote logging driver 可能没有本地完整日志；`availability=remote-only` 时记录 gap；不默认假设日志时间为宿主机本地时区；原始和规范化时间同时保留；截断日志必须标记 `truncated`；缺少日志不等于事件未发生；`message_redacted` 不得包含 Token、Cookie、Authorization、密码或完整 Secret；精确原始内容保留在源 Artifact。daemon API 和 remote log 来源的 `source_paths` 使用 `location_type=daemon-api` 或 `logical`，`path=null`，`logical_location` 提供脱敏位置。

### Stage 9 — Secrets and Suspicious Artifacts

**Secret 分析**（受 `include_secret_analysis` 控制）：检查 Compose environment/env_file、Dockerfile ARG/ENV、image config、image history、container config、registry config、Docker auth config、logs、Volume、bind mount。规则：不输出完整密码、Token、Registry Auth、私钥、连接串或 Cookie Secret；`redacted_value` 必须为不可逆脱敏或 Fingerprint；Secret 搜索不把完整匹配行写入 stdout/stderr/Ledger/Summary；Docker config auth 字段不得解码后直接输出。

**Suspicious Artifact 候选**（不依赖 `include_secret_analysis`，可由已启用的 Compose/Container/Image/Layer/Volume/Bind Mount/Log Stage 产生）：只做静态识别；不执行脚本或二进制；`execution_observed=true` 需要日志、进程、审计或直接运行证据；只有静态特征时为 `null`；实际检查相关运行证据范围后才允许 `false`；单个高风险函数或文件名不能直接定性为恶意。可疑载荷保存在 `suspicious_artifacts`、Layer/Volume Finding 或其他本 Skill 证据结构中，并记录后续专项分析 limitation；不创建跨域可执行目标。`source_location` 提供脱敏逻辑位置（如 `image-history:<image-id>`、`container-config:<container-id>`）。

### Stage 10 — Cross-source Validation and Handoff

至少交叉验证：Compose service 与 Container metadata、Container 与 Image、Image manifest 与 Layer order、Container mount 与 Volume/Bind source、Port mapping 与 Web/Database 线索、Log event 与 Container/Image/Volume Artifact、Secret Finding 与配置或镜像 Artifact、suspicious artifact 与 Layer/upperdir/Volume/日志。证据冲突时记录 `evidence_conflict`，不选择性忽略。

Stage 10 额外检查：

1. Compose Volume 配置与 container/volume metadata 是否一致。
2. Bind Mount 的宿主机 source 与容器 destination 是否一致。
3. configured、metadata-snapshot、inferred 与 live 结果是否冲突。
4. network_map 和 port_map 的 basis 是否能支撑 observation_mode。
5. container security 的 `security_observation_status`、`security_gap_notes`、capabilities、security_opt、`docker_socket_mount` 是否与 Config/HostConfig/Mounts/Binds 证据一致。
6. 同一对象的静态配置与运行态证据冲突时：记录 `evidence_conflict`，保留两套证据来源，不无依据选择其中一项作为事实。
7. partial/unobserved 不得被汇总为完整负面结论。

## Time Handling

每个容器创建、启动、停止、重启、镜像生成、Layer、日志、Event、文件变化和 Secret 暴露候选记录：`original_timestamp`、`normalized_timestamp` 或 null、timezone evidence、clock skew、time precision、source Artifact、confidence。不得无依据假设 UTC、+08:00、宿主机本地时区或容器时区。本 Skill 只生成 `timeline_candidates`，正式 Timeline Event 由 `timeline-reconstruction` 创建。

## Evidence Requirements

| Event type | Required use |
|---|---|
| command | 每个容器/镜像 inspect、日志采集、event 采集、diff、copy-out、归档解包 |
| artifact | 每个分析产物（Compose 解析、配置摘要、日志提取、文件系统变化、交叉验证结果） |
| finding | 每个关键判断（安全风险、Secret 暴露、可疑载荷、异常配置） |
| state-transition | 分析阶段完成/跳过/blocked |
| handoff | 交给 domain skills 或返回上游 |

遵循 templates/ledger-event.schema.json。每个关键 Finding 必须同时具有至少一个 Artifact 引用和至少一个 Ledger Event 引用（或有证据价值的命令输出）。Finding Record 的 `evidence_refs` 指向对应 Ledger Event。负面 Finding 必须记录实际检查范围；未检查的容器、镜像、Layer、Volume、Network、日志或时间范围不得输出"未发现异常"。

如果 Ledger Schema 没有 `daemon_scope_id`、`container_id`、`image_id` 等字段：不向 Ledger Event 发明字段；将其写入 Action Record 或分析 Artifact；Ledger Event 通过 `artifact_refs` 或 `output_artifact_refs` 回指。

### Container Security

`security_observation_status=complete` 必须回指：Container Config/HostConfig Artifact、Mounts/Binds 证据、CapAdd/CapDrop/SecurityOpt 证据、至少一个 Ledger Event。`partial` 必须有非空 `security_gap_notes`。`unobserved` 必须有 Stage 状态或 gap 记录。

### Volume and Bind Mount

每个关键 Volume 或 Bind Mount 结论必须具有：Artifact 引用、Ledger Event 引用、非空 basis、observation_mode、宿主机路径和容器路径的明确区分。

### Network and Port

每个关键 Network 或 Port 结论必须具有：Artifact 引用、Ledger Event 引用、非空 basis、observation_mode。`inferred` 条目没有 basis 时不得输出。

### Targeted Collection Action

Action Record 或分析 Artifact 必须记录：action_id、action_type、daemon_scope_id、connection_id、object_type、object_ref、limits、impact_level、expected_footprint、capture_mode。不要向 Ledger Event 发明 Schema 中不存在的字段。Ledger Event 通过 `artifact_refs` 或 `output_artifact_refs` 回指 Action Record Artifact。

## Route and Handoff Rules

### Domain Handoff

| 发现类型 | 目标 skill |
|---|---|
| Web/API、源码、访问日志和 WebShell | `webapp-server-forensics` |
| 数据库目录、Dump、事务日志和连接配置 | `database-server-forensics` |
| Linux 主机、账号、systemd、cron 和 Docker data-root 权限 | `linux-server-forensics` |
| 多源时间事件 | `timeline-reconstruction` |
| 可疑脚本、二进制和载荷 | 保留 Artifact、Finding、Ledger 和静态 candidate，记录后续专项分析 limitation；本 Skill 不执行样本 |
| 额外远程采集 | `remote-server-live-response` targeted collection handoff |

允许并行 handoff，使用 `dependency_step_ids` 和 `parallel_group`。

### Failure and Reentry

仍有继续路径时：当前 `step.status` = `blocked` 或 `failed`；reentry `step.status` = `pending`；`handoff.status` = `pending`；`route_status` = `active`；`reentry_reason` 非空；`new_evidence_refs` 非空；保留已完成分析结果。

只有以下情况 `route_status` = `blocked`：无任何继续路径、hop 超限、`execution_gate` 未解决、所有关键输入均缺失、无任何可分析 Artifact。

## Failure Classification

| error_class | 含义 | 默认动作 |
|---|---|---|
| `environment_mismatch` | 环境类型与实际不符 | blocked |
| `unsupported_runtime` | 未识别的容器运行时 | blocked |
| `source_artifact_missing` | 所有关键输入和 Artifact 均缺失 | blocked |
| `session_unavailable` | live-daemon session 不可用 | Artifact 足够→partial+continue；需采集→handoff；无 Artifact→blocked |
| `daemon_scope_mismatch` | Daemon 范围不匹配 | blocked |
| `object_scope_mismatch` | container/image/volume/network 超出范围 | blocked |
| `root_path_invalid` | 离线根路径不可识别 | blocked |
| `permission_insufficient` | 无法读取关键文件 | partial |
| `metadata_missing` | 容器/镜像/Volume 元数据缺失 | partial+continue |
| `compose_parse_failure` | Compose 解析失败 | partial+continue |
| `image_manifest_missing` | 镜像 manifest 缺失 | partial+continue |
| `layer_missing` | Layer 缺失 | partial+continue |
| `layer_order_uncertain` | Layer 顺序不确定 | partial+continue |
| `whiteout_parse_failure` | whiteout 解析失败 | partial+continue |
| `volume_source_missing` | Volume 数据源缺失 | partial+continue |
| `log_source_missing` | 日志源缺失 | partial+continue |
| `remote_log_unavailable` | 远程日志不可用 | partial+continue |
| `output_limit_exceeded` | 输出超过限制 | partial |
| `archive_limit_exceeded` | 归档超过限制 | partial+truncated |
| `archive_entry_rejected` | 归档条目被安全规则拒绝 | skip entry + continue |
| `parse_failure` | 解析失败 | partial+continue |
| `timezone_uncertain` | 时区无法确定 | finding+continue |
| `evidence_conflict` | 证据之间矛盾 | finding+continue |
| `targeted_collection_required` | 需要额外远程采集 | `route_status`=active，handoff 返回 live-response |

失败本身不自动触发 `execution_gate`。

## Execution Gate

以下动作必须触发 `execution_gate`：启动/停止/重启/暂停/删除容器、docker run/exec/build/pull/push/commit/load/import/prune、修改 Daemon/Container/Image/Volume/Network/Compose、写入容器或证据目录、将证据目录作为 Docker data-root、把证据 Volume 挂载到活动容器、权限提升、大规模无范围导出、执行证据内程序、主动利用 Docker API 或容器逃逸、解密或破解 Registry/Container 凭据。普通日志缺失、解析失败和权限不足本身不自动触发 `execution_gate`。

## Stop Conditions

只有以下情况停止整个 Skill：环境或运行时无法确认且无替代路径、没有任何可分析 Artifact、`evidence_scope` 不含任何批准 Daemon/对象/路径、无法形成有效对象和输出限制、archive 安全限制无法建立、route hop 超限、`execution_gate` 未解决。单个 Container/Image/Layer/Volume/Network/Log/Compose 文件缺失只影响对应 Stage。

## Investigation Summary

~~~markdown
## Investigation Summary

**Current Assessment**: <一句话总结容器环境和关键发现>

**Key Evidence**:
1. <Compose/容器/镜像/安全配置证据>
2. <日志/Volume/Network/Secret 证据>

**Excluded Routes** (if any): <排除的 domain 路线及依据>

**Route Plan**:
- <从 route_record.route_plan 渲染，不独立维护>
~~~

## Quality Checklist

- [ ] Frontmatter 只有 name 与 description
- [ ] 输入/输出使用当前 Request/Response Envelope
- [ ] 支持 live-daemon/offline-directory/image-archive/compose-project 四种访问模式
- [ ] live-daemon 不直接执行 Docker CLI，采集返回 live-response
- [ ] `allowed_daemon_targets` 结构化含 `daemon_scope_id`/`connection_id`/`daemon_id`/`host`
- [ ] `allowed_container_paths` 控制 container-copy-out 的容器内部路径范围
- [ ] container/image/volume/network 范围不将 null/空数组解释为允许全部
- [ ] `targeted_collection_request.actions` 展开为结构化对象（action_id/action_type/daemon_scope_id/purpose/sensitive_output_expected/capture_mode）
- [ ] `sensitive_output_expected=true` 时原始结果进入 protected raw Artifact，普通分析只引用脱敏派生
- [ ] `archive_profile` 区分 docker-save/OCI 与 container-export/rootfs-tar
- [ ] container-export/rootfs-tar 不伪造 layer order/diff ID/镜像历史
- [ ] Artifact-first：优先分析已有 collection_artifact_refs
- [ ] `large-artifact-strategy` 处理大镜像/Layer/Volume/归档
- [ ] 归档解包拒绝绝对路径/路径穿越/设备文件/硬链接越界/socket/FIFO
- [ ] 归档解包生成 archive-entry manifest，达到限制前安全停止
- [ ] whiteout 按层顺序重建，不把 whiteout 当普通文件
- [ ] Layer digest/diff ID/image digest 各自保留语义
- [ ] `identity_basis` 标识镜像身份依据，tag-only 不作为强身份
- [ ] `observation_mode` 区分 live/configured/metadata-snapshot/inferred
- [ ] EXPOSE 不等于端口已发布
- [ ] `metadata-snapshot`/`inferred` 不写成当前 live 状态
- [ ] `privileged=true` 不自动证明容器逃逸
- [ ] `compose_service_map` 含 `resolution_status`/`unresolved_variables`/安全字段
- [ ] `source_paths.path` 可以为 null，`logical_location` 提供脱敏逻辑位置
- [ ] `secret_findings.source_path`/`suspicious_artifacts.path` 可以为 null
- [ ] `message_redacted` 不包含 Token/Cookie/密码/Secret
- [ ] Secret 搜索不把完整匹配行写入 stdout/stderr/Ledger/Summary
- [ ] Docker config auth 不解码后直接输出
- [ ] `execution_observed=true` 需要直接运行证据
- [ ] 可疑载荷只保留本 Skill 的静态 Artifact/Finding/candidate，不创建未实现跨域目标
- [ ] `suspicious_artifacts` 不依赖 `include_secret_analysis`，可由已启用 Stage 产生
- [ ] 每个关键 Finding 同时有 Artifact 和 Ledger Event 引用
- [ ] Ledger Event 不发明 schema 未定义的字段
- [ ] `targeted_collection_request` 整体可为 null
- [ ] `archive_profile` 非归档模式可为 null
- [ ] reentry 时 route_status=active，handoff.status=pending
- [ ] execution_gate 仅在超出 scope 时 required
- [ ] 不硬编码本机路径
- [ ] `source_paths` 使用 `logical_location`，`secret_findings`/`suspicious_artifacts` 使用 `source_location`
- [ ] `capture_mode` 三值：`standard-artifact`（无敏感）/`protected-raw-and-redacted-derivative`（默认）/`redacted-only`（策略允许）
- [ ] 采集意外发现 Secret 时立即停止公开并重新分类
- [ ] `port_map` 中 `service_id` 和 `container_id` 至少一个非 null
- [ ] `observation_mode=configured` 有 service_id，不得描述为已实际发布
- [ ] action `impact_level` 反映 Daemon API/日志/文件系统/copy-out 影响
- [ ] `container_map` 含 `capabilities_dropped` 和 `docker_socket_mount`
- [ ] `docker_socket_mount` 必须有 mount_refs/Artifact/Ledger 证据
- [ ] action_type/object_type/object_ref 依赖已校验
- [ ] daemon_scope_id 与 connection_id 引用同一批准 daemon target
- [ ] container-logs/events/diff/copy-out 均有动作特定上限
- [ ] action 上限不超过 targeted request 和 effective limits
- [ ] paths 结构化并与 action.source_path 一致
- [ ] impact_level 有 expected_footprint 依据
- [ ] volume_map 区分 named/anonymous/tmpfs 和 managed/external
- [ ] Volume/Bind Mount 使用 observation_mode，configured 不写成 live
- [ ] network_map/port_map 的 inferred 结果具有非空 basis
- [ ] container_map 使用 security_observation_status 区分未检查与已检查为空
- [ ] security_observation_status 非 complete 时不输出完整负面安全结论
