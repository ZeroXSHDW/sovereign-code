---
name: nas-raid-encrypted-storage
description: 对 Router 已确认的独立 NAS、多成员 RAID、LVM、ZFS、Btrfs、Storage Spaces 和 BitLocker、LUKS、FileVault、VeraCrypt 等加密卷做 bounded、read-only 结构识别、有限拓扑验证和只读恢复视图生成；用于独立或尚未暴露文件系统的非平台绑定存储前置层，不负责平台集群拓扑、修复、挂载或爆破。
---

# nas-raid-encrypted-storage

## Purpose

在 `forensic-router` 选择本 Skill 后，识别独立复杂存储的成员、分区、阵列、卷管理、加密和文件系统层，形成有限拓扑 Hypothesis，执行只读结构验证，并输出可回查的成员关系、恢复视图、Artifact、Finding、Ledger Event 和 `storage_status`。

本 Skill 处理独立 NAS、通用多成员 RAID、metadata-less RAID 候选、缺失成员及非平台绑定的 mdraid、LVM、ZFS、Btrfs、Storage Spaces 和加密卷。即使卷内最终包含服务器内容，只要文件系统尚未暴露且存储恢复是前置条件，也先处理本层。PVE/Proxmox/Ceph、vSphere/vSAN、VM/Container/Snapshot/虚拟磁盘及其映射、已有 `cluster-virtualization-forensics` Route 或明确拥有重组任务的 server rebuild plan 继续由 server/cluster 链处理。

本 Skill 不实现 RAID 算法或文件系统 parser，不执行业务层 Web、Database、Docker、Malware 分析，也不生成最终答案或 Report。

## Use When

- Router 已确认独立 NAS、阵列成员、卷管理层、存储池、多设备文件系统或加密卷候选。
- `large-artifact-strategy` 提供了 bounded regions、member candidates 和可回查 Evidence。
- `uncommon-media-triage` 识别出成员、superblock、header 或层级关系，再通过 Router 返回候选。
- `proprietary-format-recovery` 恢复出嵌套存储容器或卷 Artifact，再通过 Router Handoff。
- `firmware-iot-forensics` 实际提取出独立存储镜像、阵列成员或加密卷 Artifact，再通过 Router Handoff。

扩展名、品牌、设备名、文件名、单个 magic、单项 metadata 或外部资料只能作为线索。Router 按当前待解决层级选择消费者：平台/虚拟化拓扑交 server/cluster；独立阵列、卷或加密前置层交本 Skill；可读文件系统产生后再按新 Evidence 决定服务器消费者。

## Inputs

复用 Request Envelope；`request.context` 必须包含当前 Route Record。核心 payload 字段及共享语义见 `docs/data-contracts.md` 8.14：

- `source_artifact_refs`
- `member_artifact_refs`
- `candidate_regions`
- `upstream_storage_hints`、`upstream_layer_hints`、`topology_hints`
- `key_material_refs`
- `route_basis`
- `artifact_refs`、`finding_refs`、`ledger_event_refs`
- `analysis_limits`
- `recovery_scope`

开始前确认：

1. source 和 member 引用非空、可解析为 Artifact Record，size 为已知非负整数；member 必须属于 source scope，单卷把 source 作为唯一 member。
2. `candidate_regions` 非空；1GB 以上材料已经过 `large-artifact-strategy`，所有 region 的 source、整数 offset、正整数 length 和边界合法。
3. 派生 Artifact 的直接来源可逐级回查；Artifact、Finding、Ledger Event 和 route basis 引用均有效。
4. direct route 至少具有两类相互支持的 Evidence；单个 signature、品牌、扩展名或 parser 成功不满足该要求。
5. 显式 limits 的适用字段为正整数且可强制；需要 Gate 的动作已经批准。
6. key material 只来自请求明确提供的受保护 Artifact。原始 key、口令、recovery key、token、私钥、个人数据、敏感明文和完整敏感配置只能保存在受保护 Artifact，不得写入 Response 正文、Finding、Ledger Event 正文、`investigation_summary`、`required_next_action`、普通 stdout/stderr、日志或摘要。普通输出只记录类型、来源、受保护 Artifact 引用、fingerprint、脱敏摘要和验证结果。工具可能输出完整敏感值时，将原始 stdout/stderr 直接保存为受保护 Artifact，对外暴露或写入普通日志前脱敏；Ledger 只引用该 Artifact 或受控路径，不复制完整值。

`analysis_limits` 至少支持：

- `max_members`
- `max_topology_hypotheses`
- `max_bytes_sampled_per_member`
- `timeout_seconds`
- `max_key_candidates`

缺少某项必要预算时，不执行依赖该预算的拓扑或 key validation；只保留候选，并设置 `required_next_action`。不得以候选数组看似有限代替明确预算。

## Outputs

复用 Response Envelope。payload 保留：

- `member_inventory`
- `layer_map`
- `topology_hypotheses`
- `validated_topology`
- `volume_candidates`、`filesystem_candidates`
- `encryption_assessments`
- `assembly_manifest_artifact_ref`
- `virtual_volume_artifact_refs`
- `validation_checks`、`counter_evidence`
- `excluded_routes`、`route_candidates`
- `unresolved_questions`、`required_next_action`
- `storage_status`

`storage_status` 只允许：

| Status | Meaning |
|---|---|
| `candidate_only` | 只有存储或拓扑候选 |
| `topology_validated` | 成员和层级拓扑通过至少两类支持性检查 |
| `volume_readable` | 验证后的只读卷视图可稳定读取 |
| `recovery_reproduced` | 恢复步骤可重复，输出通过文件系统 parser 或独立结构检查 |
| `rejected` | 批准范围内所有相关 Hypothesis 均被证伪，且没有存活候选 |
| `bounded_checks_exhausted` | 批准检查完成，仍有无法验证或证伪的存活候选 |
| `unknown` | 输入或 Evidence 不足，或批准检查尚未完成 |

正面优先级为 `recovery_reproduced > volume_readable > topology_validated > candidate_only`。每轮只选择一个值；单个 Hypothesis 失败不得导致整体 `rejected`。状态依据写入 Investigation Summary 或 `validation_checks`，不得替代 Finding confidence、Route、Handoff 或 Execution Gate 状态。

## Workflow

### Step 1: Confirm Scope

验证 Route、目标、source/member Artifact、size、Hash 状态、regions、Evidence 引用和 limits。记录成员数量与已知线索；弱线索只形成 Hypothesis。

### Step 2: Identify Storage Layers

有界读取分区表、RAID/volume manager metadata、pool/vdev/member label、文件系统候选和加密容器 metadata。建立简洁层级：member → partition → RAID/pool/volume manager → encryption → filesystem。

### Step 3: Build Finite Topology Hypotheses

依据 metadata 形成有限的 member order、role、missing member、RAID level、chunk/stripe/layout、offset、pool 或 volume relationship 候选。计划和实际检查均不得超过适用 limits，不执行无界排列组合。

### Step 4: Validate Candidates

对存活候选使用至少两类相互支持的检查，例如 metadata UUID/role/event 一致性、size/offset/geometry、mirror/parity/stripe 结构、volume header、filesystem parser 或 pool/vdev label。记录成功、失败、反证和未决问题；parser 失败不自动证明加密、损坏或不可恢复。

### Step 5: Handle Encryption

区分格式识别、有限 key candidate validation、用户态只读恢复视图和系统级 unlock。Request 明确提供的 key material 在适用 limits 内，可由可终止的用户态 parser 生成批准目录中的只读视图；不得创建内核映射、mount、修改 original 或系统状态。正文仅保存 Artifact 引用、fingerprint、脱敏摘要和验证结果；禁止生成候选、扩展字典或枚举 keyspace。

### Step 6: Create a Read-Only Recovery View

优先使用用户态 parser、内存映射、批准工作目录中的只读虚拟映射或只读派生文件。工具无法保证只读、有限、可撤销和输出边界时，进入 Execution Gate。

多成员虚拟卷必须先生成 assembly-manifest Artifact，记录有序 member refs、角色、缺失成员、offset、拓扑参数、采用的 Hypothesis 和 validation Evidence，并计算完整 verified Hash。没有单一直接字节父 Artifact 时，虚拟卷的 `source_artifact_id` 为 `null`；生成 Ledger Event 的 `artifact_refs` 引用 manifest 和全部成员，`output_artifact_refs` 引用虚拟卷。只有已经物化的直接中间 Artifact 才能成为后续 `source_artifact_id`。

### Step 7: Emit Results and Handoff

输出成员清单、层级、候选、验证结果、manifest、虚拟卷 Artifact、反证、状态和下一步。默认返回 `forensic-autopilot`；只有产生新 Artifact 或 Finding 且出现新的可执行消费者候选时，才按 Handoff 最多一次返回 Router。本 Skill 不直接调用其他消费者。

## Route Matrix

| Input | Minimum Evidence | Action |
|---|---|---|
| direct independent storage | 两类独立 Evidence、合法 members/regions/refs | Router 选择本 Skill |
| LAS storage candidate | bounded regions、member hints、Artifact/Finding/Ledger refs | 经 Router Handoff |
| uncommon storage candidate | superblock/header/成员或层级 Evidence | 经 Router Handoff |
| proprietary nested storage | 合法派生 Artifact、可回查 provenance、明确 Hash 状态和布局 Evidence | 经 Router Handoff |
| firmware extracted storage | 实际存储镜像、成员或加密卷 Artifact，Hash 状态明确 | 经 Router Handoff |
| metadata-backed array/pool | UUID、角色、generation/geometry 等交叉一致 | 有限拓扑验证 |
| metadata-less RAID | 明确成员集合、有限 topology budget、结构验证目标 | 有限 Hypothesis；缺预算则停止 |
| encrypted volume with key refs | header Evidence、受保护 key Artifact、有限预算 | 用户态只读视图可自动；系统级 unlock 进入 Gate |
| platform-bound storage | PVE/Ceph/vSphere/vSAN、VM/container/snapshot 映射、已有 `cluster-virtualization-forensics` Route 或 rebuild plan ownership | 交 server/cluster 链 |
| insufficient clue only | 品牌、扩展名、设备名、单个 magic 或外部资料 | `candidate_only` 或 `unknown` |
| readable recovered volume | 新 Artifact/Finding 和本轮 Ledger Event | 返回 Router 选择消费者 |
| recovered malware sample | 独立样本 Artifact，加明确恶意分析目标或独立可疑上下文 | 记录 executable candidate，经 Router 重评；普通 executable 不自动转出 |
| bounded checks remain unresolved | 已保留检查、反证和限制 | 返回 autopilot |

## Evidence Requirements

- 每个结论成为同时引用相关 Artifact 和 Ledger Event 的 Finding。
- 成员、region、metadata 和验证检查记录 source、边界、工具、时间、结果与反证。
- `layer_map` 和拓扑 Hypothesis 保留成员关系、缺失项、支持 Evidence、冲突 Evidence 和置信度。
- assembly-manifest 描述多成员拓扑与 provenance，使用完整 verified Hash，但不是虚拟卷的直接字节父 Artifact。
- 已物化且在读取预算内的派生文件优先使用 verified Hash；大型、稀疏、流式或未物化视图可用 `deferred`（含 `deferred_reason`）或 `unavailable`。Finding 和 route basis 明示限制，region/member Hash 不得冒充虚拟卷完整 Hash。
- malware candidate 记录独立样本 Artifact、直接来源、Hash 状态、目标/可疑上下文和本轮 Evidence；普通 executable 不自动进入 malware。
- key material 采用最小披露；外部资料只作方法提示，当前 Artifact 必须独立验证。

## Handoff

正式入口：

- `file-triage` / `large-artifact-strategy` → `forensic-router` → `nas-raid-encrypted-storage`
- `uncommon-media-triage` → `forensic-router` → `nas-raid-encrypted-storage`
- `proprietary-format-recovery` → `forensic-router` → `nas-raid-encrypted-storage`
- `firmware-iot-forensics` → `forensic-router` → `nas-raid-encrypted-storage`

Router 是唯一消费者决策点。上游只提供 candidate、bounded Evidence 和核心引用；Router 验证输入、Route context、limits、Gate、`visited_skills` 和 hop 后才创建完整 Handoff，并把本 Skill加入 `visited_skills`。

恢复结果统一返回 Router 重新选择消费者，不默认进入服务器链。存储前置层可以先完成并产生可读卷；随后只有新 Artifact/Finding 支持服务器目录、应用、数据库、Web、容器、虚拟化或服务器卷上下文时，Router 才选择 `server-forensics-router`。普通共享、个人磁盘、备份卷、媒体卷或通用文件系统按现有消费者能力或 Answer Gate 处理。

本 Skill 默认返回 autopilot。Router re-entry 最多一次，且必须包含 `reentry_reason`、非空 `new_evidence_refs`、本轮新 Artifact 或 Finding、本轮新 Ledger Event，以及合法 hop。Router 不得重选同一 route/evidence scope 的已访问 Skill。

storage 只有恢复出独立样本 Artifact，并具有明确恶意分析目标或独立可疑上下文时，才可形成 executable malware candidate。正式链路为 `nas-raid-encrypted-storage` → `forensic-router` → `malware-forensics`；storage 只传递直接来源、Hash 状态和本轮 Evidence，不执行或直接调用 malware。

明确禁止 storage → Router → storage、storage → Router → proprietary → Router → storage、uncommon → Router → storage → Router → uncommon、proprietary → Router → storage → Router → proprietary、firmware → Router → storage → Router → firmware、storage → Router → malware → Router → storage，以及 malware → Router → malware。

## Execution Gate

在批准 scope、工作目录和 limits 内，工具能够保证边界时，bounded metadata read、有限 Hash、member/partition/layer inventory、用户态 parser、有限 topology validation、bounded filesystem check，以及明确提供 key material 的用户态只读解密/恢复视图无需 Gate；该视图不得创建内核映射、mount、修改 original、系统或设备状态，并且必须有限、可终止。

以下动作必须停止并请求批准：

- 修改 original Artifact，或写入 RAID、LVM、ZFS、文件系统 metadata。
- 内核级 RAID assembly、LVM activation、ZFS import、cryptsetup/device-mapper 系统级 unlock 或 mount。
- repair、rebuild、rewind、resilver、scrub、`fsck`、`chkdsk` 或真实设备写入。
- 无界 topology/member-order/keyspace 枚举、字典扩展、爆破或长时间解密。
- 全盘 carving、全量 strings、安装工具、联网、在线检索、第三方上传或超出 limits。
- 向未批准目录写出结果，或工具无法保证只读、有限、可撤销的恢复动作。

## Stop Conditions

- Route、source/member Artifact、size、regions 或核心 Evidence 引用无法验证。
- 缺少执行当前 topology/key validation 所需的明确预算。
- 当前任务属于平台/虚拟化拓扑，已有 `cluster-virtualization-forensics` Route 或 server rebuild plan 已拥有存储重组任务。
- limits 无效、已达到，或工具无法保证安全边界。
- `visited_skills`、hop 或防循环条件不合法。
- 下一步需要 Execution Gate 但尚未批准。

停止恢复动作不等于停止调查；仍可保留允许的静态识别、反证、`storage_status` 和 `required_next_action`。

## Prohibited Actions

- 不修改 original Artifact，不自动执行内核组装、激活、导入、系统级解锁、挂载、修复或重建。
- 不执行无界 topology 搜索、全盘 carving、全量 strings、口令或 keyspace 爆破。
- 不联网、上传、安装依赖或写入真实 NAS/设备。
- 不处理 PVE、Ceph、VM、Container、Snapshot 或虚拟磁盘拓扑。
- 不按品牌、文件名、扩展名、单个 magic、单项 metadata 或外部结论确认存储类型。
- 不把 parser 成功等同于恢复完成，不把 parser 失败等同于加密或不可恢复。
- 不直接调用消费者，不生成最终答案或 Report。

## Notes

- 借鉴 [sleuthkit/sleuthkit](https://github.com/sleuthkit/sleuthkit) 的分层解析与独立复核方法。
- 借鉴 [md-raid-utilities/mdadm](https://github.com/md-raid-utilities/mdadm) 和 [openzfs/zfs](https://github.com/openzfs/zfs) 的成员、阵列、pool 与 generation metadata 定位。
- 借鉴 [mbroz/cryptsetup](https://github.com/mbroz/cryptsetup)、[libyal/libbde](https://github.com/libyal/libbde) 和 [libyal/libfvde](https://github.com/libyal/libfvde) 的格式识别、key validation 分层和用户态解析。
- 借鉴 [fox-it/dissect](https://github.com/fox-it/dissect) 的组合式虚拟视图，以及 [cgsecurity/testdisk](https://github.com/cgsecurity/testdisk) 的 geometry 与结构交叉验证。
- 只借鉴公开工作流和工具定位，未复制代码。所有工具均为可选能力，实际使用取决于检材、环境和已批准范围。
