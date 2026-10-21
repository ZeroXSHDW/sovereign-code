---
name: cluster-virtualization-forensics
description: 集群、虚拟化和复杂存储取证。用于 PVE/Proxmox、pmxcfs、Corosync、Quorum、Ceph、vSphere/vSAN、mdraid、LVM、ZFS、btrfs、共享存储、VM、Container、Snapshot、虚拟磁盘及镜像候选的证据化拓扑分析。
---

# cluster-virtualization-forensics

## Purpose

本 Skill 负责把集群、虚拟化对象和复杂存储 Artifact 重建为可追溯的 Layer Graph，并生成节点、磁盘、存储、Workload、Snapshot、镜像候选、健康状态和 Timeline Candidate。分析必须先完成作用域与环境验证，再从物理或逻辑提供者映射到 Guest 消费者；不得把配置、历史元数据、文件名或逻辑引用写成当前运行事实或已取得的磁盘内容。

本 Skill 不建立 SSH、PVE API、Ceph API、vCenter 或其他远程连接。所有新增 live 采集必须结构化交回 `remote-server-live-response`。本 Skill 不修复集群、不激活或组装存储、不启动 VM/Container，也不替代 Guest Linux、Web、Database、Docker、Timeline、Answer Gate 或 Report 工作。

## Use When

- PVE/Proxmox、pmxcfs、Corosync、Quorum 或多节点配置需要建立 Cluster/Node 关系。
- Ceph MON、MGR、OSD、Pool、PG、RBD，或 vSphere/vSAN Artifact 需要与虚拟化对象关联。
- mdraid、LVM/LVM-thin、ZFS、btrfs、Directory、NFS、CIFS、iSCSI 等存储层需要映射到 VM Disk 或 Container rootfs。
- 已有离线节点镜像、disk set、配置/日志包、虚拟化导出或获批准的 live/rebuilt Session。
- 需要区分真实镜像内容、descriptor、backing file、snapshot delta、symlink、placeholder、远程逻辑引用和 missing extent。

## Do Not Use When

- 只有独立 NAS、通用 RAID 或加密存储，且没有虚拟化关系证据。
- 需要 Windows Server/Hyper-V 深度分析、Guest 应用层分析或最终报告。
- 需要执行恢复、修复、激活、导入、映射、写入挂载、启动、迁移或删除操作。
- `large-artifact-strategy` 尚未完成必需的大型 Artifact 定位或采样。

## Ownership Boundary

本 Skill 负责 PVE/Proxmox、VMware vSphere、vSAN、通用 Linux 虚拟化、pmxcfs、Corosync、Quorum、Ceph、物理盘、分区、mdraid、LVM、ZFS、btrfs、共享存储、VM、Container、VM Template、Container Template、Snapshot、backing chain、image candidate 及其冲突和缺失关系。

以下职责必须 Handoff：

- 新增远程采集：`remote-server-live-response`
- 大型或高成本 Artifact：`large-artifact-strategy`
- 重建规划：`server-rebuild-planner`
- 仅在已有完成的 Planner Step 和 ready plan 时执行：`server-rebuild-executor`
- Guest OS、容器、数据库、Web：对应 domain Skill
- 正式 Timeline：`timeline-reconstruction`

## Access Modes

| access_mode | Session | 允许的材料 | 新增采集 |
|---|---|---|---|
| `live-cluster` | 必须存在 | 当前批准 Session 的 collection Artifact | 仅生成 targeted collection Handoff |
| `rebuilt-cluster` | 必须存在 | 重建 Artifact、runtime 信息和批准 Session | 仅生成 targeted collection Handoff |
| `offline-node-image` | 必须为空 | 有限 root Artifact 和批准路径 | 禁止 live Action |
| `disk-set` | 必须为空 | 明确列出的 disk set member | 禁止 live Action |
| `artifact-package` | 必须为空 | 配置、日志、导出清单和已有工具输出 | 禁止 live Action |

`observation_mode` 固定为：

- `live`：来自当前批准 Session 和 collection Artifact。
- `configured`：静态配置，不证明当前生效、成员在线或存储健康。
- `metadata-snapshot`：离线或历史元数据，不代表当前运行状态。
- `inferred`：间接推断，`basis` 必须非空。

静态与 live 结果冲突时保留双方观察，生成 conflict；不得覆盖或静默选择其一。

## Request Contract

遵循 `templates/request-envelope.schema.json`。`request.context.route_record` 必须是完整 Route Record；`current_step_id` 独立保存并引用其中一个 `route_step_id`。null、缺失或空批准列表均不表示 wildcard。

<!-- cluster-request-contract:start -->
```yaml
schema_version: "1.0"
request:
  material_info:
    artifact_refs:
      - "artifact-<uuid>"
    material_type: string
    triage_notes:
      - string
    size_summary:
      total_bytes: integer|null
      file_count: integer|null
      largest_file_bytes: integer|null
  objective: string|null
  objective_status: explicit|inferred|unknown
  context:
    route_record:
      schema_version: "1.0"
      route_id: "route-<uuid>"
      triggered_skill: string
      route_basis:
        - string
      mode_decision: string|null
      route_status: active|completed|blocked|failed|cancelled
      route_plan:
        - route_step_id: "step-<uuid>"
          skill: string
          dependency_step_ids:
            - "step-<uuid>"
          parallel_group: string|null
          status: pending|running|completed|blocked|failed|skipped
      handoffs:
        - handoff_id: "hof-<uuid>"
          route_id: "route-<uuid>"
          from_step_id: "step-<uuid>"
          to_step_id: "step-<uuid>"
          from: string
          to: string
          reason: string
          artifact_refs:
            - "artifact-<uuid>"
          finding_refs:
            - "finding-<uuid>"
          visited_skills:
            - string
          hop_count: integer
          status: pending|accepted|completed|rejected|blocked
          priority: critical|high|normal|low
          reentry_reason: string|null
          new_evidence_refs:
            - "led-<uuid>"
      evidence_scope: string
      risk_level: low|medium|high
      next_action: string|null
      execution_gate:
        required: boolean
        reason: string|null
        policy_ref: string|null
      routing_policy:
        max_hops: integer
    current_step_id: "step-<uuid>"
    artifact_refs:
      - "artifact-<uuid>"
    ledger_event_refs:
      - "led-<uuid>"
    finding_refs:
      - "finding-<uuid>"
    upstream_environment:
      plan_id: string|null
      session_id: string|null
      runtime_instance_ref: string|null
    upstream_time_observation:
      remote_timestamp: string|null
      remote_timezone: string|null
      timezone_offset: string|null
      estimated_clock_skew_seconds: integer|null
  payload:
    environment:
      origin_type: direct-remote|rebuilt-runtime|offline-artifact
      plan_id: string|null
      session_id: string|null
      connection_ids:
        - string
      root_artifact_refs:
        - "artifact-<uuid>"
      collection_artifact_refs:
        - "artifact-<uuid>"
    access_mode: live-cluster|rebuilt-cluster|offline-node-image|disk-set|artifact-package
    cluster_scope:
      analysis_scope_id: string
      platform_hints:
        - proxmox-ve|vmware-vsphere|generic-linux-virtualization|unknown
      targeted_questions:
        - string
      allowed_cluster_targets:
        - cluster_scope_id: string
          connection_id: string|null
          target_ref: string
          virtualization_platform: proxmox-ve|vmware-vsphere|generic-linux-virtualization|unknown
          endpoint_role: pve-api|ceph-cli|vcenter-api|ssh|service-client|offline-artifact|other
      allowed_node_targets:
        - cluster_scope_id: string
          node_id: string
      allowed_vm_targets:
        - cluster_scope_id: string
          vm_id: string
      allowed_container_targets:
        - cluster_scope_id: string
          container_id: string
      allowed_storage_targets:
        - cluster_scope_id: string
          storage_id: string
      allowed_disk_targets:
        - cluster_scope_id: string
          disk_id: string
      allowed_paths:
        - path_scope_id: string
          cluster_scope_id: string|null
          owner_node_id: string|null
          artifact_ref: "artifact-<uuid>|null"
          path: string
          recursive: boolean
          max_depth: integer|null
      disk_set_members:
        - cluster_scope_id: string
          member_id: string
          artifact_ref: "artifact-<uuid>"
          expected_role: system-disk|data-disk|raid-member|lvm-pv|zfs-vdev|btrfs-device|ceph-osd|unknown
          required: boolean
      stages:
        include_platform_node_mapping: boolean
        include_quorum_analysis: boolean
        include_disk_mapping: boolean
        include_storage_reconstruction: boolean
        include_distributed_storage_analysis: boolean
        include_vm_mapping: boolean
        include_snapshot_backing_analysis: boolean
        include_health_conflict_analysis: boolean
        include_timeline_candidates: boolean
        include_cross_domain_validation: boolean
      live_collection_limits:
        max_actions: integer|null
        max_output_bytes: integer|null
        max_objects_per_action: integer|null
        max_log_bytes: integer|null
        max_config_bytes: integer|null
        max_session_seconds: integer|null
      archive_limits:
        max_archive_files: integer|null
        max_archive_expanded_bytes: integer|null
      disk_limits:
        max_disk_members: integer|null
        max_bytes_sampled_per_disk: integer|null
        max_image_candidates: integer|null
      traversal_limits:
        max_depth: integer|null
        max_objects: integer|null
        max_paths: integer|null
```
<!-- cluster-request-contract:end -->

### Request Invariants

1. `analysis_scope_id` 标识本次分析，`cluster_scope_id` 标识一个具体 Cluster；两者不是同一 ID。
2. 所有对象跨表引用使用 `(cluster_scope_id, local object ID)`。
3. live/rebuilt 模式要求非空 `session_id`、非空 `connection_ids`；Cluster target 的 `connection_id` 必须属于当前 Session。
4. offline 模式要求 `session_id=null`、空 `connection_ids`、Cluster target 的 `connection_id=null`，不得生成 live Action。
5. 五类对象批准列表相互独立；空列表禁止相应对象操作。`disk_set_members` 和 `disk_map` 不能批准 live Disk Action。
6. `path_scope_id` 在 Request 内唯一。live/rebuilt 路径必须绑定同一 Cluster 下的批准 Node；offline 路径必须有非空 `artifact_ref`。
7. 相关限制取 Request、案件策略、上游 Session 和父 Route 中最小有效正整数；没有有效来源时该限制为 unresolved，不得编造默认值。
8. offline 模式必须由注册 `root_artifact_refs`、`route_record.evidence_scope` 和相应 scoped path 形成有限根；`disk-set` 还必须有至少一个 `disk_set_members`，未枚举 member 不处理。

## Response Contract

遵循 `templates/response-envelope.schema.json`：顶层包含 `schema_version`、`investigation_summary`、`route_record`、`findings`、`ledger_events`、`artifact_refs` 和 `payload`。Route 信息只存在于 `route_record`，Investigation Summary 的 Route Plan 由其渲染。

### 完整冻结 Response

<!-- cluster-response-contract:start -->
```yaml
schema_version: "1.0"
investigation_summary:
  current_assessment: "string"
  key_evidence:
    - "string"
  excluded_routes:
    - "string"

route_record:
  schema_version: "1.0"
  route_id: "route-<uuid>"
  triggered_skill: "cluster-virtualization-forensics"
  route_basis:
    - "string"
  mode_decision: "string|null"
  route_status: "active|completed|blocked|failed|cancelled"
  route_plan:
    - route_step_id: "step-<uuid>"
      skill: "string"
      dependency_step_ids:
        - "step-<uuid>"
      parallel_group: "string|null"
      status: "pending|running|completed|blocked|failed|skipped"
  handoffs:
    - handoff_id: "hof-<uuid>"
      route_id: "route-<uuid>"
      from_step_id: "step-<uuid>"
      to_step_id: "step-<uuid>"
      from: "cluster-virtualization-forensics"
      to: "string"
      reason: "string"
      artifact_refs:
        - "artifact-<uuid>"
      finding_refs:
        - "finding-<uuid>"
      visited_skills:
        - "string"
      hop_count: "integer"
      status: "pending|accepted|completed|rejected|blocked"
      priority: "critical|high|normal|low"
      reentry_reason: "string|null"
      new_evidence_refs:
        - "led-<uuid>"
  evidence_scope: "string"
  risk_level: "low|medium|high"
  next_action: "string|null"
  execution_gate:
    required: "boolean"
    reason: "string|null"
    policy_ref: "string|null"
  routing_policy:
    max_hops: "integer"

findings:
  - schema_version: "1.0"
    finding_id: "finding-<uuid>"
    description: "string"
    confidence: "high|medium|low"
    evidence_refs:
      - "led-<uuid>"
    artifact_refs:
      - "artifact-<uuid>"
    category: "acquisition|analysis|validation|negative|null"
    related_skill: "string|null"
    created_at: "ISO8601|null"

ledger_events:
  - schema_version: "1.0"
    event_id: "led-<uuid>"
    event_type: "command|finding|artifact|handoff|state-transition"
    timestamp: "ISO8601"
    skill: "cluster-virtualization-forensics"
    stage: "string|null"
    artifact_refs:
      - "artifact-<uuid>"
    parent_event_id: "led-<uuid>|null"
    route_id: "route-<uuid>|null"
    handoff_id: "hof-<uuid>|null"
    timeline_event_refs:
      - "tl-<uuid>"
    status: "pending|in_progress|retrying|blocked|completed|failed|skipped"
    command: "string|null"
    started_at: "ISO8601|null"
    ended_at: "ISO8601|null"
    exit_code: "integer|null"
    stdout_path: "string|null"
    stderr_path: "string|null"
    output_artifact_refs:
      - "artifact-<uuid>"
    finding: "string|null"
    confidence: "high|medium|low|null"
    next_action: "string|null"

artifact_refs:
  - "artifact-<uuid>"

payload:
  environment:
    origin_type: "direct-remote|rebuilt-runtime|offline-artifact"
    plan_id: "string|null"
    session_id: "string|null"
    connection_ids:
      - "string"
    root_artifact_refs:
      - "artifact-<uuid>"
    collection_artifact_refs:
      - "artifact-<uuid>"
    artifact_refs:
      - "artifact-<uuid>"
    ledger_event_refs:
      - "led-<uuid>"
    basis:
      - "string"
    confidence: "high|medium|low"

  access_mode: "live-cluster|rebuilt-cluster|offline-node-image|disk-set|artifact-package"

  cluster_profiles:
    - cluster_scope_id: "string"
      cluster_id: "string|null"
      cluster_name: "string|null"
      virtualization_platform: "proxmox-ve|vmware-vsphere|generic-linux-virtualization|unknown"
      platform_version: "string|null"
      control_plane_components:
        - component_id: "string"
          component_type: "pmxcfs|corosync|pve-cluster|vcenter|vsphere-ha|libvirt|other"
          component_version: "string|null"
          status: "present|missing|partial|unknown"
      distributed_storage_components:
        - component_id: "string"
          component_type: "ceph|vsan|other"
          component_version: "string|null"
          status: "present|degraded|missing|partial|unknown"
      configured_node_count: "integer|null"
      observed_node_count: "integer|null"
      observation_mode: "live|configured|metadata-snapshot|inferred"
      observed_at: "ISO8601|null"
      artifact_refs:
        - "artifact-<uuid>"
      ledger_event_refs:
        - "led-<uuid>"
      basis:
        - "string"
      confidence: "high|medium|low"

  node_map:
    - cluster_scope_id: "string"
      node_id: "string"
      hostname: "string|null"
      platform_node_ref: "string|null"
      roles:
        - "pve-node|vsphere-host|corosync-member|ceph-mon|ceph-mgr|ceph-osd-host|storage-node|compute-node|other"
      membership_status: "member|configured-member|missing|removed|unknown"
      management_addresses:
        - "string"
      observation_mode: "live|configured|metadata-snapshot|inferred"
      observed_at: "ISO8601|null"
      artifact_refs:
        - "artifact-<uuid>"
      ledger_event_refs:
        - "led-<uuid>"
      basis:
        - "string"
      confidence: "high|medium|low"

  disk_map:
    - cluster_scope_id: "string"
      disk_id: "string"
      owner_node_id: "string|null"
      layer_node_id: "string"
      device_path: "string|null"
      stable_identifier: "string|null"
      size_bytes: "integer|null"
      sector_size: "integer|null"
      member_role: "system-disk|data-disk|raid-member|lvm-pv|zfs-vdev|btrfs-device|ceph-osd|unknown"
      availability: "present|missing|partial|unreadable|metadata-only"
      observation_mode: "live|configured|metadata-snapshot|inferred"
      artifact_refs:
        - "artifact-<uuid>"
      ledger_event_refs:
        - "led-<uuid>"
      basis:
        - "string"
      confidence: "high|medium|low"

  storage_map:
    - cluster_scope_id: "string"
      storage_id: "string"
      owner_node_ids:
        - "string"
      storage_type: "directory|nfs|cifs|iscsi|mdraid|lvm|lvm-thin|zfs|btrfs|ceph-rbd|cephfs|vsan|other|unknown"
      configured_name: "string|null"
      configured_path_or_target: "string|null"
      shared: "boolean|null"
      content_roles:
        - "vm-disk|container-rootfs|template|iso|backup|snippet|other"
      backing_layer_node_refs:
        - "string"
      health_status: "healthy|degraded|failed|unknown|not-observed"
      observation_mode: "live|configured|metadata-snapshot|inferred"
      artifact_refs:
        - "artifact-<uuid>"
      ledger_event_refs:
        - "led-<uuid>"
      basis:
        - "string"
      confidence: "high|medium|low"

  layer_map:
    nodes:
      - cluster_scope_id: "string"
        layer_node_id: "string"
        node_type: "physical-disk|partition|mdraid-array|lvm-pv|lvm-vg|lvm-lv|lvm-thin-pool|lvm-thin-volume|zfs-vdev|zfs-pool|zfs-dataset|zfs-zvol|btrfs-device|btrfs-filesystem|btrfs-subvolume|ceph-osd|ceph-pool|ceph-rbd|directory-storage|nfs-export|iscsi-target|vsan-object|qcow2-file|raw-file|vmdk-descriptor|vmdk-extent|snapshot-delta|vm-disk|container-rootfs|guest-image-candidate|missing-component|unknown"
        entity_ref: "string|null"
        owner_node_id: "string|null"
        name: "string|null"
        location: "string|null"
        size_bytes: "integer|null"
        availability: "present|missing|partial|unreadable|metadata-only|remote-reference"
        identity_status: "verified|correlated|ambiguous|unverified"
        observation_mode: "live|configured|metadata-snapshot|inferred"
        observed_at: "ISO8601|null"
        artifact_refs:
          - "artifact-<uuid>"
        ledger_event_refs:
          - "led-<uuid>"
        basis:
          - "string"
        confidence: "high|medium|low"

    edges:
      - cluster_scope_id: "string"
        layer_edge_id: "string"
        from_layer_node_id: "string"
        to_layer_node_id: "string"
        relation: "contains|partitions-into|member-of|backs|aggregates-into|allocates|hosts|stores|maps-to|configured-as|snapshot-parent-of|backing-file-of|delta-parent-of|symlink-target-of|remote-reference-to|missing-link-to|conflicts-with"
        observation_mode: "live|configured|metadata-snapshot|inferred"
        artifact_refs:
          - "artifact-<uuid>"
        ledger_event_refs:
          - "led-<uuid>"
        basis:
          - "string"
        confidence: "high|medium|low"

    gaps:
      - cluster_scope_id: "string"
        gap_id: "string"
        expected_from_layer_node_id: "string|null"
        expected_to_layer_node_id: "string|null"
        missing_layer_type: "string"
        reason: "member-missing|metadata-missing|content-unavailable|scope-excluded|parse-failure|unknown"
        impact: "informational|partial-map|blocks-image-identity|blocks-rebuild"
        artifact_refs:
          - "artifact-<uuid>"
        ledger_event_refs:
          - "led-<uuid>"
        basis:
          - "string"
        confidence: "high|medium|low"

    conflicts:
      - cluster_scope_id: "string"
        conflict_id: "string"
        left_ref: "string"
        right_ref: "string"
        conflict_type: "configured-vs-live|identity-mismatch|size-mismatch|membership-mismatch|backing-chain-mismatch|other"
        resolution_status: "unresolved|explained|resolved"
        preferred_ref: "string|null"
        artifact_refs:
          - "artifact-<uuid>"
        ledger_event_refs:
          - "led-<uuid>"
        basis:
          - "string"
        confidence: "high|medium|low"

  vm_map:
    - cluster_scope_id: "string"
      workload_id: "string"
      owner_node_id: "string|null"
      object_type: "vm|container|vm-template|container-template"
      name: "string|null"
      platform: "pve-qemu|pve-lxc|vsphere-vm|libvirt-vm|other|unknown"
      configured_state: "defined|template|disabled|unknown"
      runtime_state: "running|stopped|paused|suspended|unknown|not-observed"
      observation_mode: "live|configured|metadata-snapshot|inferred"
      artifact_refs:
        - "artifact-<uuid>"
      ledger_event_refs:
        - "led-<uuid>"
      basis:
        - "string"
      confidence: "high|medium|low"

  vm_disk_map:
    - cluster_scope_id: "string"
      vm_disk_mapping_id: "string"
      workload_id: "string"
      object_type: "vm|container|vm-template|container-template"
      device_slot: "string|null"
      storage_id: "string|null"
      configured_volume_ref: "string|null"
      terminal_layer_node_id: "string"
      layer_edge_refs:
        - "string"
      image_candidate_refs:
        - "string"
      disk_role: "boot|system|data|efi|tpm|cloud-init|container-rootfs|other|unknown"
      observation_mode: "live|configured|metadata-snapshot|inferred"
      artifact_refs:
        - "artifact-<uuid>"
      ledger_event_refs:
        - "led-<uuid>"
      basis:
        - "string"
      confidence: "high|medium|low"

  snapshot_map:
    - cluster_scope_id: "string"
      snapshot_id: "string"
      owner_type: "vm|container|vm-template|container-template|vm-disk|storage-volume"
      owner_ref: "string"
      parent_snapshot_id: "string|null"
      snapshot_type: "internal|external|storage-native|rbd-snapshot|zfs-snapshot|vmware-delta|pve-snapshot|unknown"
      created_at: "ISO8601|null"
      state: "configured|present|missing|partial|unknown"
      layer_node_refs:
        - "string"
      backing_edge_refs:
        - "string"
      observation_mode: "live|configured|metadata-snapshot|inferred"
      artifact_refs:
        - "artifact-<uuid>"
      ledger_event_refs:
        - "led-<uuid>"
      basis:
        - "string"
      confidence: "high|medium|low"

  quorum_findings:
    - cluster_scope_id: "string"
      quorum_finding_id: "string"
      quorum_state: "quorate|not-quorate|unknown|not-applicable"
      expected_votes: "integer|null"
      observed_votes: "integer|null"
      member_node_ids:
        - "string"
      missing_node_ids:
        - "string"
      split_brain_suspected: "boolean|null"
      observation_mode: "live|configured|metadata-snapshot|inferred"
      artifact_refs:
        - "artifact-<uuid>"
      ledger_event_refs:
        - "led-<uuid>"
      basis:
        - "string"
      confidence: "high|medium|low"

  storage_health_findings:
    - cluster_scope_id: "string"
      health_finding_id: "string"
      target_type: "mdraid|lvm|zfs|btrfs|ceph|vsan|shared-storage|other"
      target_ref: "string"
      health_state: "healthy|degraded|failed|incomplete|unknown"
      missing_component_refs:
        - "string"
      indicators:
        - "string"
      observation_mode: "live|configured|metadata-snapshot|inferred"
      artifact_refs:
        - "artifact-<uuid>"
      ledger_event_refs:
        - "led-<uuid>"
      basis:
        - "string"
      confidence: "high|medium|low"

  image_candidates:
    - cluster_scope_id: "string"
      candidate_id: "string"
      object_type: "full-image|descriptor|backing-file|snapshot-delta|symlink|placeholder|metadata-only-reference|remote-logical-reference|missing-extent"
      location_type: "filesystem-path|artifact|logical-storage|remote-storage|unknown"
      location: "string"
      content_availability: "complete|partial|descriptor-only|metadata-only|remote-not-acquired|missing|unreadable|unknown"
      identity_status: "verified-content|verified-descriptor|correlated|ambiguous|unverified"
      size_bytes: "integer|null"
      format: "raw|qcow2|vmdk|vhd|vhdx|e01|rbd|zvol|lv|filesystem-tree|unknown"
      backing_refs:
        - "string"
      layer_node_refs:
        - "string"
      source_artifact_id: "artifact-<uuid>|null"
      analysis_readiness: "ready|limited|not-ready"
      analysis_readiness_basis:
        - "string"
      large_artifact_status: "required|pending|completed|not-required|unknown"
      artifact_refs:
        - "artifact-<uuid>"
      ledger_event_refs:
        - "led-<uuid>"
      basis:
        - "string"
      confidence: "high|medium|low"

  timeline_candidates:
    - cluster_scope_id: "string"
      candidate_id: "string"
      original_timestamp: "string|null"
      normalized_timestamp: "ISO8601|null"
      timezone_offset: "string|null"
      timezone_name: "string|null"
      timezone_assumption: "string|null"
      clock_skew_seconds: "integer|null"
      time_precision: "exact|second|minute|day|unknown"
      source_type_hint: "pve-log|ceph-log|file-time|unsupported-cluster-log"
      source_artifact_id: "artifact-<uuid>"
      parser_id: "string"
      actor: "string|null"
      action: "string"
      target: "string|null"
      ledger_event_refs:
        - "led-<uuid>"
      basis:
        - "string"
      confidence: "high|medium|low"
      normalization_status: "ready|needs-review|unsupported-source"

  cross_domain_candidates:
    - candidate_id: "string"
      cluster_scope_id: "string"
      skill: "server-rebuild-planner|server-rebuild-executor|remote-server-live-response|linux-server-forensics|docker-container-forensics|database-server-forensics|webapp-server-forensics|timeline-reconstruction|large-artifact-strategy"
      basis:
        - "string"
      confidence: "high|medium|low"
      connection_ids:
        - "string"
      artifact_refs:
        - "artifact-<uuid>"
      finding_refs:
        - "finding-<uuid>"
      ledger_event_refs:
        - "led-<uuid>"
      dependency_step_ids:
        - "step-<uuid>"
      workload_refs:
        - cluster_scope_id: "string"
          workload_id: "string"
          object_type: "vm|container|vm-template|container-template"
      planner_authorization:
        planner_step_id: "step-<uuid>|null"
        plan_id: "string|null"
        plan_status: "ready|blocked|rejected|null"
      targeted_collection_request:
        actions:
          - action_id: "string"
            action_type: "cluster-status|node-list|quorum-status|storage-config|vm-list|vm-config|container-config|ceph-status|ceph-health-detail|ceph-osd-tree|ceph-pool-list|ceph-rbd-list|lvm-metadata|mdraid-detail|zfs-status|btrfs-filesystem-show|bounded-config-copy|bounded-log-collection"
            target_type: "cluster|node|vm|container|storage|disk"
            target_ref: "string"
            cluster_scope_id: "string"
            connection_id: "string"
            source_path: "string|null"
            allowed_path_scope_id: "string|null"
            since: "ISO8601|null"
            until: "ISO8601|null"
            max_objects: "integer"
            max_output_bytes: "integer"
            purpose: "string"
            impact_level: "low|medium|high"
            sensitive_output_expected: "boolean"
            capture_mode: "standard-artifact|protected-raw-and-redacted-derivative|redacted-only"
            expected_footprint:
              - "string"
        paths:
          - action_id: "string"
            path_role: "remote-config-source|remote-log-source"
            path: "string"
        max_output_bytes: "integer"
        reason: "string"

  effective_limits:
    max_actions:
      value: "integer|null"
      status: "resolved|unresolved|not-applicable"
      basis:
        - "string"
    max_output_bytes:
      value: "integer|null"
      status: "resolved|unresolved|not-applicable"
      basis:
        - "string"
    max_objects_per_action:
      value: "integer|null"
      status: "resolved|unresolved|not-applicable"
      basis:
        - "string"
    max_log_bytes:
      value: "integer|null"
      status: "resolved|unresolved|not-applicable"
      basis:
        - "string"
    max_config_bytes:
      value: "integer|null"
      status: "resolved|unresolved|not-applicable"
      basis:
        - "string"
    max_archive_files:
      value: "integer|null"
      status: "resolved|unresolved|not-applicable"
      basis:
        - "string"
    max_archive_expanded_bytes:
      value: "integer|null"
      status: "resolved|unresolved|not-applicable"
      basis:
        - "string"
    max_disk_members:
      value: "integer|null"
      status: "resolved|unresolved|not-applicable"
      basis:
        - "string"
    max_bytes_sampled_per_disk:
      value: "integer|null"
      status: "resolved|unresolved|not-applicable"
      basis:
        - "string"
    max_image_candidates:
      value: "integer|null"
      status: "resolved|unresolved|not-applicable"
      basis:
        - "string"
    max_depth:
      value: "integer|null"
      status: "resolved|unresolved|not-applicable"
      basis:
        - "string"
    max_objects:
      value: "integer|null"
      status: "resolved|unresolved|not-applicable"
      basis:
        - "string"
    max_paths:
      value: "integer|null"
      status: "resolved|unresolved|not-applicable"
      basis:
        - "string"

  blockers:
    - blocker_id: "string"
      cluster_scope_id: "string|null"
      error_class: "environment_mismatch|unsupported_platform|session_unavailable|cluster_scope_mismatch|node_scope_mismatch|vm_scope_mismatch|container_scope_mismatch|storage_scope_mismatch|root_path_invalid|disk_member_missing|metadata_missing|quorum_unknown|split_brain_suspected|raid_degraded|lvm_metadata_incomplete|zfs_metadata_incomplete|ceph_map_incomplete|distributed_storage_health_degraded|backing_chain_incomplete|image_content_unavailable|placeholder_only|large_artifact_incomplete|output_limit_exceeded|parse_failure|timezone_uncertain|evidence_conflict|targeted_collection_required|planner_authorization_missing"
      scope: "cluster|node|disk|storage|layer|vm|snapshot|image|timeline|collection"
      target_ref: "string|null"
      message: "string"
      recoverable: "boolean"
      required_handoff: "server-forensics-router|server-rebuild-planner|server-rebuild-executor|remote-server-live-response|linux-server-forensics|docker-container-forensics|database-server-forensics|webapp-server-forensics|timeline-reconstruction|large-artifact-strategy|null"
      artifact_refs:
        - "artifact-<uuid>"
      ledger_event_refs:
        - "led-<uuid>"
      basis:
        - "string"
      confidence: "high|medium|low"
```
<!-- cluster-response-contract:end -->

### `payload` 同步块

<!-- cluster-payload-contract:start -->
```yaml
payload:
  environment:
    origin_type: direct-remote|rebuilt-runtime|offline-artifact
    plan_id: string|null
    session_id: string|null
    connection_ids:
      - string
    root_artifact_refs:
      - "artifact-<uuid>"
    collection_artifact_refs:
      - "artifact-<uuid>"
    artifact_refs:
      - "artifact-<uuid>"
    ledger_event_refs:
      - "led-<uuid>"
    basis:
      - string
    confidence: high|medium|low
  access_mode: live-cluster|rebuilt-cluster|offline-node-image|disk-set|artifact-package
  cluster_profiles:
    - cluster_scope_id: string
      cluster_id: string|null
      cluster_name: string|null
      virtualization_platform: proxmox-ve|vmware-vsphere|generic-linux-virtualization|unknown
      platform_version: string|null
      control_plane_components:
        - component_id: string
          component_type: pmxcfs|corosync|pve-cluster|vcenter|vsphere-ha|libvirt|other
          component_version: string|null
          status: present|missing|partial|unknown
      distributed_storage_components:
        - component_id: string
          component_type: ceph|vsan|other
          component_version: string|null
          status: present|degraded|missing|partial|unknown
      configured_node_count: integer|null
      observed_node_count: integer|null
      observation_mode: live|configured|metadata-snapshot|inferred
      observed_at: ISO8601|null
      artifact_refs:
        - "artifact-<uuid>"
      ledger_event_refs:
        - "led-<uuid>"
      basis:
        - string
      confidence: high|medium|low
  node_map:
    - cluster_scope_id: string
      node_id: string
      hostname: string|null
      platform_node_ref: string|null
      roles:
        - pve-node|vsphere-host|corosync-member|ceph-mon|ceph-mgr|ceph-osd-host|storage-node|compute-node|other
      membership_status: member|configured-member|missing|removed|unknown
      management_addresses:
        - string
      observation_mode: live|configured|metadata-snapshot|inferred
      observed_at: ISO8601|null
      artifact_refs:
        - "artifact-<uuid>"
      ledger_event_refs:
        - "led-<uuid>"
      basis:
        - string
      confidence: high|medium|low
  disk_map:
    - cluster_scope_id: string
      disk_id: string
      owner_node_id: string|null
      layer_node_id: string
      device_path: string|null
      stable_identifier: string|null
      size_bytes: integer|null
      sector_size: integer|null
      member_role: system-disk|data-disk|raid-member|lvm-pv|zfs-vdev|btrfs-device|ceph-osd|unknown
      availability: present|missing|partial|unreadable|metadata-only
      observation_mode: live|configured|metadata-snapshot|inferred
      artifact_refs:
        - "artifact-<uuid>"
      ledger_event_refs:
        - "led-<uuid>"
      basis:
        - string
      confidence: high|medium|low
  storage_map:
    - cluster_scope_id: string
      storage_id: string
      owner_node_ids:
        - string
      storage_type: directory|nfs|cifs|iscsi|mdraid|lvm|lvm-thin|zfs|btrfs|ceph-rbd|cephfs|vsan|other|unknown
      configured_name: string|null
      configured_path_or_target: string|null
      shared: boolean|null
      content_roles:
        - vm-disk|container-rootfs|template|iso|backup|snippet|other
      backing_layer_node_refs:
        - string
      health_status: healthy|degraded|failed|unknown|not-observed
      observation_mode: live|configured|metadata-snapshot|inferred
      artifact_refs:
        - "artifact-<uuid>"
      ledger_event_refs:
        - "led-<uuid>"
      basis:
        - string
      confidence: high|medium|low
  layer_map:
    nodes:
      - cluster_scope_id: string
        layer_node_id: string
        node_type: physical-disk|partition|mdraid-array|lvm-pv|lvm-vg|lvm-lv|lvm-thin-pool|lvm-thin-volume|zfs-vdev|zfs-pool|zfs-dataset|zfs-zvol|btrfs-device|btrfs-filesystem|btrfs-subvolume|ceph-osd|ceph-pool|ceph-rbd|directory-storage|nfs-export|iscsi-target|vsan-object|qcow2-file|raw-file|vmdk-descriptor|vmdk-extent|snapshot-delta|vm-disk|container-rootfs|guest-image-candidate|missing-component|unknown
        entity_ref: string|null
        owner_node_id: string|null
        name: string|null
        location: string|null
        size_bytes: integer|null
        availability: present|missing|partial|unreadable|metadata-only|remote-reference
        identity_status: verified|correlated|ambiguous|unverified
        observation_mode: live|configured|metadata-snapshot|inferred
        observed_at: ISO8601|null
        artifact_refs:
          - "artifact-<uuid>"
        ledger_event_refs:
          - "led-<uuid>"
        basis:
          - string
        confidence: high|medium|low
    edges:
      - cluster_scope_id: string
        layer_edge_id: string
        from_layer_node_id: string
        to_layer_node_id: string
        relation: contains|partitions-into|member-of|backs|aggregates-into|allocates|hosts|stores|maps-to|configured-as|snapshot-parent-of|backing-file-of|delta-parent-of|symlink-target-of|remote-reference-to|missing-link-to|conflicts-with
        observation_mode: live|configured|metadata-snapshot|inferred
        artifact_refs:
          - "artifact-<uuid>"
        ledger_event_refs:
          - "led-<uuid>"
        basis:
          - string
        confidence: high|medium|low
    gaps:
      - cluster_scope_id: string
        gap_id: string
        expected_from_layer_node_id: string|null
        expected_to_layer_node_id: string|null
        missing_layer_type: string
        reason: member-missing|metadata-missing|content-unavailable|scope-excluded|parse-failure|unknown
        impact: informational|partial-map|blocks-image-identity|blocks-rebuild
        artifact_refs:
          - "artifact-<uuid>"
        ledger_event_refs:
          - "led-<uuid>"
        basis:
          - string
        confidence: high|medium|low
    conflicts:
      - cluster_scope_id: string
        conflict_id: string
        left_ref: string
        right_ref: string
        conflict_type: configured-vs-live|identity-mismatch|size-mismatch|membership-mismatch|backing-chain-mismatch|other
        resolution_status: unresolved|explained|resolved
        preferred_ref: string|null
        artifact_refs:
          - "artifact-<uuid>"
        ledger_event_refs:
          - "led-<uuid>"
        basis:
          - string
        confidence: high|medium|low
  vm_map:
    - cluster_scope_id: string
      workload_id: string
      owner_node_id: string|null
      object_type: vm|container|vm-template|container-template
      name: string|null
      platform: pve-qemu|pve-lxc|vsphere-vm|libvirt-vm|other|unknown
      configured_state: defined|template|disabled|unknown
      runtime_state: running|stopped|paused|suspended|unknown|not-observed
      observation_mode: live|configured|metadata-snapshot|inferred
      artifact_refs:
        - "artifact-<uuid>"
      ledger_event_refs:
        - "led-<uuid>"
      basis:
        - string
      confidence: high|medium|low
  vm_disk_map:
    - cluster_scope_id: string
      vm_disk_mapping_id: string
      workload_id: string
      object_type: vm|container|vm-template|container-template
      device_slot: string|null
      storage_id: string|null
      configured_volume_ref: string|null
      terminal_layer_node_id: string
      layer_edge_refs:
        - string
      image_candidate_refs:
        - string
      disk_role: boot|system|data|efi|tpm|cloud-init|container-rootfs|other|unknown
      observation_mode: live|configured|metadata-snapshot|inferred
      artifact_refs:
        - "artifact-<uuid>"
      ledger_event_refs:
        - "led-<uuid>"
      basis:
        - string
      confidence: high|medium|low
  snapshot_map:
    - cluster_scope_id: string
      snapshot_id: string
      owner_type: vm|container|vm-template|container-template|vm-disk|storage-volume
      owner_ref: string
      parent_snapshot_id: string|null
      snapshot_type: internal|external|storage-native|rbd-snapshot|zfs-snapshot|vmware-delta|pve-snapshot|unknown
      created_at: ISO8601|null
      state: configured|present|missing|partial|unknown
      layer_node_refs:
        - string
      backing_edge_refs:
        - string
      observation_mode: live|configured|metadata-snapshot|inferred
      artifact_refs:
        - "artifact-<uuid>"
      ledger_event_refs:
        - "led-<uuid>"
      basis:
        - string
      confidence: high|medium|low
  quorum_findings:
    - cluster_scope_id: string
      quorum_finding_id: string
      quorum_state: quorate|not-quorate|unknown|not-applicable
      expected_votes: integer|null
      observed_votes: integer|null
      member_node_ids:
        - string
      missing_node_ids:
        - string
      split_brain_suspected: boolean|null
      observation_mode: live|configured|metadata-snapshot|inferred
      artifact_refs:
        - "artifact-<uuid>"
      ledger_event_refs:
        - "led-<uuid>"
      basis:
        - string
      confidence: high|medium|low
  storage_health_findings:
    - cluster_scope_id: string
      health_finding_id: string
      target_type: mdraid|lvm|zfs|btrfs|ceph|vsan|shared-storage|other
      target_ref: string
      health_state: healthy|degraded|failed|incomplete|unknown
      missing_component_refs:
        - string
      indicators:
        - string
      observation_mode: live|configured|metadata-snapshot|inferred
      artifact_refs:
        - "artifact-<uuid>"
      ledger_event_refs:
        - "led-<uuid>"
      basis:
        - string
      confidence: high|medium|low
  image_candidates:
    - cluster_scope_id: string
      candidate_id: string
      object_type: full-image|descriptor|backing-file|snapshot-delta|symlink|placeholder|metadata-only-reference|remote-logical-reference|missing-extent
      location_type: filesystem-path|artifact|logical-storage|remote-storage|unknown
      location: string
      content_availability: complete|partial|descriptor-only|metadata-only|remote-not-acquired|missing|unreadable|unknown
      identity_status: verified-content|verified-descriptor|correlated|ambiguous|unverified
      size_bytes: integer|null
      format: raw|qcow2|vmdk|vhd|vhdx|e01|rbd|zvol|lv|filesystem-tree|unknown
      backing_refs:
        - string
      layer_node_refs:
        - string
      source_artifact_id: "artifact-<uuid>|null"
      analysis_readiness: ready|limited|not-ready
      analysis_readiness_basis:
        - string
      large_artifact_status: required|pending|completed|not-required|unknown
      artifact_refs:
        - "artifact-<uuid>"
      ledger_event_refs:
        - "led-<uuid>"
      basis:
        - string
      confidence: high|medium|low
  timeline_candidates:
    - cluster_scope_id: string
      candidate_id: string
      original_timestamp: string|null
      normalized_timestamp: ISO8601|null
      timezone_offset: string|null
      timezone_name: string|null
      timezone_assumption: string|null
      clock_skew_seconds: integer|null
      time_precision: exact|second|minute|day|unknown
      source_type_hint: pve-log|ceph-log|file-time|unsupported-cluster-log
      source_artifact_id: "artifact-<uuid>"
      parser_id: string
      actor: string|null
      action: string
      target: string|null
      ledger_event_refs:
        - "led-<uuid>"
      basis:
        - string
      confidence: high|medium|low
      normalization_status: ready|needs-review|unsupported-source
  cross_domain_candidates:
    - candidate_id: string
      cluster_scope_id: string
      skill: server-rebuild-planner|server-rebuild-executor|remote-server-live-response|linux-server-forensics|docker-container-forensics|database-server-forensics|webapp-server-forensics|timeline-reconstruction|large-artifact-strategy
      basis:
        - string
      confidence: high|medium|low
      connection_ids:
        - string
      artifact_refs:
        - "artifact-<uuid>"
      finding_refs:
        - "finding-<uuid>"
      ledger_event_refs:
        - "led-<uuid>"
      dependency_step_ids:
        - "step-<uuid>"
      workload_refs:
        - cluster_scope_id: string
          workload_id: string
          object_type: vm|container|vm-template|container-template
      planner_authorization:
        planner_step_id: "step-<uuid>|null"
        plan_id: string|null
        plan_status: ready|blocked|rejected|null
      targeted_collection_request:
        actions:
          - action_id: string
            action_type: cluster-status|node-list|quorum-status|storage-config|vm-list|vm-config|container-config|ceph-status|ceph-health-detail|ceph-osd-tree|ceph-pool-list|ceph-rbd-list|lvm-metadata|mdraid-detail|zfs-status|btrfs-filesystem-show|bounded-config-copy|bounded-log-collection
            target_type: cluster|node|vm|container|storage|disk
            target_ref: string
            cluster_scope_id: string
            connection_id: string
            source_path: string|null
            allowed_path_scope_id: string|null
            since: ISO8601|null
            until: ISO8601|null
            max_objects: integer
            max_output_bytes: integer
            purpose: string
            impact_level: low|medium|high
            sensitive_output_expected: boolean
            capture_mode: standard-artifact|protected-raw-and-redacted-derivative|redacted-only
            expected_footprint:
              - string
        paths:
          - action_id: string
            path_role: remote-config-source|remote-log-source
            path: string
        max_output_bytes: integer
        reason: string
  effective_limits:
    max_actions:
      value: integer|null
      status: resolved|unresolved|not-applicable
      basis:
        - string
    max_output_bytes:
      value: integer|null
      status: resolved|unresolved|not-applicable
      basis:
        - string
    max_objects_per_action:
      value: integer|null
      status: resolved|unresolved|not-applicable
      basis:
        - string
    max_log_bytes:
      value: integer|null
      status: resolved|unresolved|not-applicable
      basis:
        - string
    max_config_bytes:
      value: integer|null
      status: resolved|unresolved|not-applicable
      basis:
        - string
    max_archive_files:
      value: integer|null
      status: resolved|unresolved|not-applicable
      basis:
        - string
    max_archive_expanded_bytes:
      value: integer|null
      status: resolved|unresolved|not-applicable
      basis:
        - string
    max_disk_members:
      value: integer|null
      status: resolved|unresolved|not-applicable
      basis:
        - string
    max_bytes_sampled_per_disk:
      value: integer|null
      status: resolved|unresolved|not-applicable
      basis:
        - string
    max_image_candidates:
      value: integer|null
      status: resolved|unresolved|not-applicable
      basis:
        - string
    max_depth:
      value: integer|null
      status: resolved|unresolved|not-applicable
      basis:
        - string
    max_objects:
      value: integer|null
      status: resolved|unresolved|not-applicable
      basis:
        - string
    max_paths:
      value: integer|null
      status: resolved|unresolved|not-applicable
      basis:
        - string
  blockers:
    - blocker_id: string
      cluster_scope_id: string|null
      error_class: environment_mismatch|unsupported_platform|session_unavailable|cluster_scope_mismatch|node_scope_mismatch|vm_scope_mismatch|container_scope_mismatch|storage_scope_mismatch|root_path_invalid|disk_member_missing|metadata_missing|quorum_unknown|split_brain_suspected|raid_degraded|lvm_metadata_incomplete|zfs_metadata_incomplete|ceph_map_incomplete|distributed_storage_health_degraded|backing_chain_incomplete|image_content_unavailable|placeholder_only|large_artifact_incomplete|output_limit_exceeded|parse_failure|timezone_uncertain|evidence_conflict|targeted_collection_required|planner_authorization_missing
      scope: cluster|node|disk|storage|layer|vm|snapshot|image|timeline|collection
      target_ref: string|null
      message: string
      recoverable: boolean
      required_handoff: server-forensics-router|server-rebuild-planner|server-rebuild-executor|remote-server-live-response|linux-server-forensics|docker-container-forensics|database-server-forensics|webapp-server-forensics|timeline-reconstruction|large-artifact-strategy|null
      artifact_refs:
        - "artifact-<uuid>"
      ledger_event_refs:
        - "led-<uuid>"
      basis:
        - string
      confidence: high|medium|low
```
<!-- cluster-payload-contract:end -->

`targeted_collection_request` 整体允许为 null；非 null 时 `actions`、`paths`、`max_output_bytes`、`reason` 全部存在，`actions` 和 `reason` 非空。每项 `effective_limits` 独立记录 `value`、`status`、`basis`：resolved 要求正整数；unresolved/not-applicable 要求 null。

## Recognition Priorities

### PVE、pmxcfs、Corosync 与 Quorum

优先分析 PVE storage 配置、QEMU/LXC workload 配置、pmxcfs/config.db、Corosync 配置和状态 Artifact、节点成员、votes、Quorum、VMID、storage ID、volume ID、bridge 和网络配置。静态配置只能产生 configured 观察；不得恢复 pmxcfs、修改 Cluster 配置或把配置节点写成当前在线节点。

保留旧版精确识别点：`/etc/pve/storage.cfg`、`/etc/pve/qemu-server/`、`/etc/pve/lxc/`、`/var/lib/pve-cluster/config.db`。这些是检材内或远端运行时证据位置，不是本机路径绑定；分别用于 storage ID/volume、QEMU VM、LXC Container 与 pmxcfs 配置历史的 configured-vs-live 互证。

### Ceph 与 vSAN

分析 Ceph FSID、`ceph.conf`、MON、MGR、OSD、Pool、PG、RBD、cephx 引用、PVE RBD storage 和日志；分析已有 vSphere/vSAN 配置和导出 Artifact。Ceph/vSAN 属于 `distributed_storage_components`，不得写入 `virtualization_platform`。缺少 OSD/RBD/vSAN 对象时建立 gap 和 Hypothesis，不宣称已恢复。

Ceph 还必须检查配置中的 `mon_host` 与检材内 `/var/lib/ceph/` 的 MON/MGR/OSD 身份目录，并与 live map 分开记录；配置存在只证明 configured state，不能替代当前 Ceph health 或 membership。

### mdraid、LVM、ZFS、btrfs 与共享存储

分析已有 mdadm superblock/输出、PV/VG/LV/thin pool/thin volume 元数据、zpool/vdev/dataset/zvol、btrfs device/filesystem/subvolume、Directory/NFS/CIFS/iSCSI 配置。文本输出和配置引用不能证明已访问块内容；不得执行 assemble、activate、import、map 或 writable mount。

## Layer Graph

`layer_map` 是物理设备到 Guest 的唯一拓扑事实源。`disk_map`、`storage_map`、`vm_disk_map` 仅作为带 Layer 引用的投影视图，不得维护另一套父子关系。

Edge 固定从 provider/parent/base/resolved target 指向 consumer/child/delta/symlink representation。合法关系和端点由专项验证器中的 `RELATION_PAIRS` 冻结；`conflicts-with` 仅允许同一 Cluster、相同非空 `entity_ref`、相同 `node_type` 的不同 Node。

`member-of` 仅表示 raw block/file member 到 typed component；`aggregates-into` 仅表示 typed component 到 aggregate container。`backing-file-of`、`delta-parent-of`、`snapshot-parent-of` 子图必须无环；每个 `snapshot-delta` 最多一个立即父节点，缺失父层必须用 `missing-component` 和 gap 表达。

## Workload、Snapshot 与 Image Candidate

`vm_map` 和 `vm_disk_map` 使用 `(cluster_scope_id, workload_id, object_type)`。`vm|vm-template` 引用 `allowed_vm_targets`；`container|container-template` 引用 `allowed_container_targets`。`pve-lxc` 不得标为 `vm-template`；`pve-qemu|vsphere-vm|libvirt-vm` 不得标为 `container-template`。VM Disk、Snapshot 和 Handoff 必须保持完整四值类型一致。

Image Candidate 必须区分 full image、descriptor、backing file、snapshot delta、symlink、placeholder、metadata-only reference、remote logical reference 和 missing extent。文件名、扩展名、配置路径或 `.E01.txt`、`*.qcow2.txt`、`*.vmdk.txt` 不能证明内容存在。

`analysis_readiness=ready` 仅在内容完整、`identity_status=verified-content`、必需 backing/base/extent 完整、`large_artifact_status=completed|not-required` 且没有 scope/损坏/缺失/加密 blocker 时允许。`identity_status=correlated` 最多为 limited，并在 `analysis_readiness_basis` 中说明可回答范围和禁止结论。descriptor、placeholder、symlink、metadata-only、remote-not-acquired 和 missing extent 必须 not-ready。

## Workflow

### Stage 1 — Environment and Scope Validation

始终执行。验证完整 Route Context、`current_step_id`、access mode、Session、Connection、Cluster/Object target、path scope、disk-set member、Artifact 和 effective limits。live/rebuilt 身份与 offline 身份不得混用。完成标准：所有后续读取或 Action 都能落入有限批准范围；否则记录 blocker。

### Stage 2 — Cluster Platform and Node Mapping

由 `include_platform_node_mapping` 控制。识别 virtualization platform、control plane、distributed storage、Cluster 和 Node；覆盖 PVE、pmxcfs、Corosync、vCenter、libvirt、Ceph、vSAN。关闭时 skipped，不输出该范围负面 Finding。

### Stage 3 — Quorum and Membership Analysis

由 `include_quorum_analysis` 控制。分析 Corosync membership、votes、Quorum、缺失节点和 split-brain Hypothesis。没有当前 Session 时只能 configured/metadata-snapshot/inferred 或 unknown，不得写 live。

### Stage 4 — Physical Disk and Block Device Mapping

由 `include_disk_mapping` 控制。建立 scoped `disk_map` 和 physical-disk/partition Layer Node，区分 present、missing、partial、unreadable、metadata-only。缺少部分 member 为 partial；所有 required member 缺失才阻断该路线。

### Stage 5 — Storage Stack Reconstruction

由 `include_storage_reconstruction` 控制。按证据建立 mdraid、LVM、ZFS、btrfs、Directory、NFS、CIFS、iSCSI Layer 和 `storage_map`。不激活、不组装、不导入、不挂载；元数据不完整时产生 gap 和 partial。

### Stage 6 — Distributed Storage Analysis

由 `include_distributed_storage_analysis` 控制。建立 Ceph MON/MGR/OSD/Pool/PG/RBD 或 vSAN 组件、健康 Finding 和 Layer 关系。不适用时 skipped；map 不完整或 degraded 时 partial 并继续可用分析。

### Stage 7 — VM, Container and Disk Mapping

由 `include_vm_mapping` 控制。建立 VM、Container、VM Template、Container Template、owner Node、storage、volume、device slot 和 Layer 终点关系。不得把 Container 使用 VM 身份字段或丢失 object_type。

### Stage 8 — Snapshot, Backing Chain and Image Analysis

由 `include_snapshot_backing_analysis` 控制。建立 Snapshot、backing/delta DAG、missing extent 和 `image_candidates`。缺失 base/extent 时 partial 且 candidate not-ready；大型或高成本内容按 large-Artifact 状态 Handoff。

### Stage 9 — Health, Conflict and Missing Component Analysis

由 `include_health_conflict_analysis` 控制。合并 RAID/LVM/ZFS/btrfs/Ceph/vSAN 健康、缺失组件、孤立对象和 configured-vs-live 冲突。保留冲突双方，不选择性忽略证据。

### Stage 10 — Timeline Candidate Extraction

由 `include_timeline_candidates` 控制。只生成带 `source_artifact_id`、Ledger 引用、basis、时区依据和 confidence 的候选。PVE/Ceph/file-time 可标 ready；其他 Cluster 日志使用 `unsupported-cluster-log` 和 `unsupported-source`，不得生成正式 Timeline Event。

### Stage 11 — Cross-domain Validation and Handoff

由 `include_cross_domain_validation` 控制。验证所有跨表引用、Graph、Image、Action、Planner 依赖和 negative Finding coverage，再创建证据支持的 Handoff。允许 Guest domain 并行，但必须用 `dependency_step_ids` 和 `parallel_group` 表达。

## Live Targeted Collection

本 Skill 不执行 live 命令，只生成给 `remote-server-live-response` 的结构化 Action。允许的 `action_type` 固定为：

`cluster-status|node-list|quorum-status|storage-config|vm-list|vm-config|container-config|ceph-status|ceph-health-detail|ceph-osd-tree|ceph-pool-list|ceph-rbd-list|lvm-metadata|mdraid-detail|zfs-status|btrfs-filesystem-show|bounded-config-copy|bounded-log-collection`

规则：

1. 每个 Action 的 `cluster_scope_id`、`connection_id` 必须匹配当前 Session 的批准 Cluster target。
2. `cluster-status`、`node-list`、`quorum-status`、`storage-config`、`ceph-status`、`ceph-health-detail`、`ceph-osd-tree`、`ceph-pool-list` 只 target Cluster；`vm-list` target Cluster 或批准 Node；`vm-config` target 批准 VM；`container-config` target 批准 Container；`ceph-rbd-list` target 批准 storage；`lvm-metadata` target 批准 Node；mdraid、ZFS、btrfs Action 按固定模板 target 批准 Node、disk 或 storage。`disk_set_members` 和 `disk_map` 不能批准 live Disk Action。
3. bounded copy/log 只能 target 批准 Node，必须有非空 `allowed_path_scope_id`；Action Cluster、Node 和 `source_path` 必须匹配同一批准 path scope。bounded log 还必须有有效 `since < until`。
4. 所有 Action 具有有限 `max_objects`、`max_output_bytes`、purpose、impact、capture mode 和 expected footprint，不得超过 resolved effective limits。
5. 不允许自由 Shell/API/Docker/PVE/Ceph/vCenter 字符串；live-response 只能把 `action_type` 映射到批准模板。
6. 可能含 Secret 的结果使用 protected raw Artifact 和 redacted derivative；普通 Ledger/Summary 不复制原文。

## Evidence Requirements

- 每个关键记录必须有源 `artifact_refs`、`ledger_event_refs`、非空 `basis` 和 `confidence`。
- Finding Record 的 `evidence_refs` 指向 Ledger Event；Ledger 文本不能代替源 Artifact。
- 派生 Artifact 使用 `source_artifact_id` 保持 Chain of Custody。
- command、artifact、finding、state-transition、handoff 事件遵循 `templates/ledger-event.schema.json`，不添加 Schema 未定义字段。
- `inferred` 必须有 basis；`live` 必须来自当前批准 Session 和 collection Artifact。
- negative Finding 必须记录完整检查范围。Stage skipped、数据 missing/unreadable/partial/truncated/out-of-scope 时不得输出相应“未发现”结论。
- 若统一 Finding/Ledger 字段不能证明 negative scope 与 skipped Stage scope 完全不重叠，保守地禁止该 negative Finding；不得用其他 Stage 的事件绕过 skipped 状态。

## Handoff and Reentry

- `large_artifact_status=required`：创建 `large-artifact-strategy` Handoff，状态改为 pending；只有新 Artifact/Ledger 证据返回后改为 completed。
- `server-rebuild-planner`：Layer Graph 已形成有限可重建范围，所需 Image 为 ready 或明确 limited。
- `server-rebuild-executor`：必须存在已完成的 Planner Route Step、非空匹配 plan ID、`plan_status=ready`，且 executor Step 依赖 Planner Step。
- 需要新增 live 采集：返回 `remote-server-live-response`，当前 route_status=active、handoff pending、`reentry_reason` 与 `new_evidence_refs` 非空。
- Linux/Docker/Database/Web Handoff 保留 `(cluster_scope_id, workload_id, object_type)`，可在 Artifact 已取得后并行。
- 正式 Timeline 交给 `timeline-reconstruction`；本轮不开始该 Skill。

防循环：下游返回 Cluster 必须有新的 Cluster Artifact/Ledger、变化的 evidence scope、非空 reentry reason 和 new evidence refs。重复看见已有路径不构成 reentry。

## Failure and Stop Conditions

固定 `error_class`：

`environment_mismatch|unsupported_platform|session_unavailable|cluster_scope_mismatch|node_scope_mismatch|vm_scope_mismatch|container_scope_mismatch|storage_scope_mismatch|root_path_invalid|disk_member_missing|metadata_missing|quorum_unknown|split_brain_suspected|raid_degraded|lvm_metadata_incomplete|zfs_metadata_incomplete|ceph_map_incomplete|distributed_storage_health_degraded|backing_chain_incomplete|image_content_unavailable|placeholder_only|large_artifact_incomplete|output_limit_exceeded|parse_failure|timezone_uncertain|evidence_conflict|targeted_collection_required|planner_authorization_missing`

partial + continue：Session 不可用但已有 Artifact 足够；部分节点/磁盘/元数据缺失；Quorum 未知；存储 degraded；backing 不完整；仅有 placeholder/descriptor；局部超限、解析失败、时区不确定或证据冲突。

当前 Step blocked：环境或 scope 不匹配；live/offline Session 条件错误；所有 required disk 缺失；没有可分析 Artifact；必需 limit unresolved；非法 live Action；缺少 Planner 授权；Image 所需 large-Artifact 仍 required/pending；execution gate 未解决。

存在补采、large-Artifact、Planner 或其他继续路径时 route_status=active。仅在没有继续路径、hop 超限、gate 未解决或所有关键输入缺失时 route_status=blocked。返回上游时不得同时把 Route 标记 blocked。

## Execution Gate

以下动作不属于默认分析，拟执行时必须由拥有该职责的流程进入 `execution_gate`：

- 启动、停止、迁移、快照或删除 VM/Container。
- 修改 Cluster、节点成员、Corosync 或 Quorum。
- Ceph repair/reweight/rebalance/scrub/deep-scrub 或 MON/MGR/OSD 启停激活。
- `zpool import`、`zpool clear`、ZFS scrub。
- `vgchange -ay`、LV/thin pool 激活。
- `mdadm --assemble`、RAID rebuild。
- `rbd map`、证据存储写入挂载。
- repair-mode image check、convert、resize、rebase、commit、backing chain 修改。
- 执行证据程序或服务、安装依赖、权限提升、无范围扫描或全量导出。

## Quality Checklist

- [ ] frontmatter 只有 `name` 和 `description`。
- [ ] Request/Response payload 与 `docs/data-contracts.md` 8.9 完全一致。
- [ ] PVE、pmxcfs、Corosync、Quorum、Ceph、mdraid、LVM、ZFS、btrfs、共享存储均有明确分析步骤。
- [ ] Layer Edge 方向、合法端点和 DAG 通过专项验证。
- [ ] Session/Connection、path scope、Disk target、workload、Image readiness、Planner/Executor 依赖通过验证。
- [ ] skipped Stage 不产生该范围 negative Finding。
- [ ] 不含旧布尔 payload 字段、本机绝对路径、旧 battle summary 或 Route Trace。
- [ ] 不修改统一 Schema、不执行恢复动作、不开始 Timeline。
