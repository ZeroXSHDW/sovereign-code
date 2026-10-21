---
name: proprietary-format-recovery
description: 未知或厂商专有封装格式的 bounded 静态恢复。重建 header、目录表、块表、索引表和记录边界，验证有限 transform、key 与 known-plaintext 候选，并生成可重复的 candidate schema、解析步骤和派生 Artifact。
---

# proprietary-format-recovery

## Purpose

proprietary-format-recovery 是 Phase 3 的 bounded 静态恢复消费者。它在 `uncommon-media-triage` 已识别结构候选并由 `forensic-router` 完成消费者决策后，对未知或厂商专有封装格式做更深的布局恢复、字段映射和有限变换验证；负责重建文件头、目录表、块表、索引表和记录边界，在批准 candidate region 内验证请求明确提供的 XOR、简单混淆、字节序、编码、key candidate 与 known-plaintext candidate，按已验证边界执行 bounded carving，并输出可重复的 `candidate_schema`、解析步骤、派生 Artifact、正面 Evidence、反证、排除路线和未决问题。本 Skill 不负责 CAN、NMEA、GPS、传感器或时间序列的首次结构识别，不解包固件或遍历 rootfs，不激活 RAID/LVM、不解锁或挂载加密卷，不执行样本或做动态分析，不做 IOC 深度提取或数据库业务语义查询，不执行无界 keyspace 搜索、全文件爆破或无限制恢复，也不生成最终答案。

## Use When

只有 `forensic-router` 基于 recovery-specific Evidence 选择本 Skill 时才使用。合格入口至少包括以下一种可回查 Evidence，并且必须同时提供非空 `candidate_regions`：

- 可复核的 header 与 directory/block/index table 关系。
- `uncommon-media-triage` 提供的重复记录边界、`candidate_schema` 或结构提示，需要更深布局恢复。
- 请求明确提供的有限 transform、key 或 known-plaintext candidates，可在 bounded region 内验证。
- 已验证表项指向的数据块，需要按已知边界 carving 并登记派生 Artifact。

扩展名、设备名、单个 magic、单独熵值、外部资料或无法回查的断言不能独立触发本 Skill。`request.context` 必须包含当前 Route Record；`visited_skills` 已包含 `proprietary-format-recovery` 时，Router 不得再次选择本 Skill。

## Inputs

本 Skill 复用现有 Request Envelope：

| Field | Required | Description |
|---|---|---|
| `request.material_info.artifact_refs` | Yes | source Artifact 的回退引用列表 |
| `request.objective` | Recommended | 调查目标；缺失时执行中立的 bounded recovery |
| `request.objective_status` | Yes | `explicit`、`inferred` 或 `unknown` |
| `request.context` | Yes | 当前 Route Record、Route Step、Finding 和 Ledger Event 引用 |
| `request.payload` | Yes | 本 Skill 的 recovery payload profile |

`request.payload` 支持：

| Field | Required | Description |
|---|---|---|
| `source_artifact_refs` | Recommended | 非空时作为 effective source；否则回退到 `material_info.artifact_refs` |
| `candidate_regions` | Yes | 非空 bounded region 列表 |
| `upstream_region_assessments` | Recommended | uncommon 或 `large-artifact-strategy` 的 region 评估与 Evidence |
| `upstream_structure_hints` | Recommended | 已验证边界、字段、table 或容器提示 |
| `candidate_schema` | Recommended | 上游候选布局；必须保留不确定项和 Evidence |
| `route_basis` | Yes | Router 选择本 Skill 的 recovery-specific Evidence |
| `artifact_refs` | Yes | 可回查 Artifact 引用 |
| `finding_refs` | Yes | 可回查 Finding 引用 |
| `ledger_event_refs` | Yes | 可回查 Ledger Event 引用，包含本轮上游事件 |
| `header_hints` | Recommended | header offset、字段与验证提示 |
| `directory_table_hints` | Recommended | 目录表位置、项宽和计数提示 |
| `block_table_hints` | Recommended | 块表位置、块边界和长度提示 |
| `index_table_hints` | Recommended | 索引表、记录指针和排序提示 |
| `record_boundary_hints` | Recommended | 已验证或待验证的重复记录边界 |
| `transform_hypotheses` | Recommended | 符合下述 item profile 的 transform 候选 |
| `key_material_candidates` | Recommended | 符合下述 item profile 的 key material 候选；原始 material 只在受保护 Artifact 中 |
| `known_plaintext_candidates` | Recommended | 符合下述 item profile 的 plaintext 候选；敏感明文只在受保护 Artifact 中 |
| `counter_evidence` | Recommended | 上游反证、失败校验和排除路线 |
| `requested_checks` | Recommended | 本轮批准的具体检查 |
| `analysis_limits` | Recommended | region、字节、slice、timeout 与候选检查上限 |

每个 `candidate_regions` 项至少包含 `region_id`、`source_artifact_ref`、`derived_artifact_ref`（不存在时为 `null`）、非负整数 `offset`、正整数 `length` 和 `sampling_method`。

三个候选数组使用以下最小 item profile：

| Array | Required item fields |
|---|---|
| `transform_hypotheses` | `candidate_id`, `transform_type`, `parameters`, `target_region_ids`, `evidence_refs`, `candidate_usability` |
| `key_material_candidates` | `candidate_id`, `candidate_type`, `material_artifact_ref`, `fingerprint`, `target_region_ids`, `evidence_refs`, `candidate_usability` |
| `known_plaintext_candidates` | `candidate_id`, `material_artifact_ref`, `fingerprint`, `encoding`, `target_region_ids`, `evidence_refs`, `candidate_usability` |

`candidate_usability` 只允许 `executable|hint-only`：

- `executable` 候选必须包含实际验证所需的数据，使用非空且唯一的 `candidate_id`，具有非空 `target_region_ids` 和 `evidence_refs`，且每个 target 都解析到本 Request 的 `candidate_regions.region_id`。
- executable transform 的 `transform_type` 和 `parameters` 必须足以重复执行变换；若需要 key 或 plaintext，实际 material 必须来自对应 executable candidate 的受保护 Artifact。
- key/plaintext 的 `material_artifact_ref` 非空时必须解析到 Artifact Record。key 或 plaintext 候选只有 fingerprint、没有可解析 material Artifact 时固定为 `hint-only`。
- executable key/plaintext candidate 的 `material_artifact_ref` 必须非空、可解析，并指向包含实际验证 material 的受保护派生 Artifact；正文仍只保留 Artifact 引用和 fingerprint。
- `hint-only` 可支持 Hypothesis、Finding 或 `required_next_action`，但不得进入自动 transform/key/plaintext validation，也不计入 candidate check 组合。
- `candidate_usability` 缺失或为其他值时，该 item 输入不可执行；不得静默升级为 `executable`。

输入必须逐项验证：

1. 定义 `effective_source_artifact_refs`：非空 `source_artifact_refs` 优先；缺失或空数组时使用 `request.material_info.artifact_refs`。
2. effective source 必须非空，且每个引用都能解析到 Artifact Record。
3. `candidate_regions` 必须存在且非空。
4. `offset` 必须是 `>= 0` 的整数；不接受十六进制字符串、带单位字符串或其他文本。
5. `length` 必须是正整数。
6. 每个 source Artifact Record 的 `size` 必须是已知的非负整数。
7. `offset + length` 只与对应 source Artifact Record 的 `size` 比较，且不得越界。
8. 每个 region 的 `source_artifact_ref` 必须属于 effective source。
9. `derived_artifact_ref` 存在时必须能解析到 Artifact Record，其 `source_artifact_id` 必须匹配 region source，且 `size` 必须可验证。
10. 所有 Artifact、Finding 和 Ledger Event 引用必须存在且可回查。
11. `route_basis`、hints、assessments、candidate schema、有限候选或 validation Evidence 中至少存在一种 recovery-specific Evidence。
12. 扩展名、设备名、单个 magic、单独熵值或外部资料不能独立满足第 11 项。
13. `visited_skills` 已包含 `proprietary-format-recovery` 时输入不可执行。

显式 `analysis_limits` 的非空字段都必须是正整数。沿用 `max_regions`、`max_bytes_per_region`、`max_total_bytes`、`max_slice_bytes` 和 `timeout_seconds`：分别验证 region 数量、单 region 长度、region 总字节数、派生 Artifact Record 的 `size` 和实际运行时间。`max_slice_bytes` 不读取或推断 `slice.length`。任一限制无法强制、字段类型无效或实际值超限时不得开始或继续，必须记录字段、实际值、限制值和 `required_next_action`。

本 payload profile 额外支持 `analysis_limits.max_candidate_checks`。一次 `candidate_check` 固定为一个实际执行组合：一个 `candidate_region`、一个 executable transform candidate、零或一个 executable key candidate、零或一个 executable known-plaintext candidate。每个不同的 `(region_id, transform_candidate_id, key_candidate_id|null, plaintext_candidate_id|null)` 组合计数加一，并对应一个唯一 `check_id`。`hint-only` item 不进入组合，也不得执行。

请求执行 transform/key/plaintext candidate validation 时，`max_candidate_checks` 必须存在且为正整数；执行前枚举的计划组合总数和实际已执行组合数都不得超过该值。无法证明计划组合数量时不得开始候选验证。`max_candidate_checks` 缺失或为 `null` 时仍可执行 header、table、layout、record boundary 和 `candidate_schema` 恢复，但不得执行任何 transform/key/plaintext candidate validation；必须设置 `required_next_action`，要求提供正整数候选检查预算。不得仅凭数组有限自动执行。

`analysis_limits` 整体缺失时使用 `limits_source: implicit-bounded-input`，只读取已提供 regions，不扩大 offset/length、不生成候选、不请求新 slice，并且不执行 transform/key/plaintext candidate validation。提供显式 limits 时使用 `limits_source: explicit`。

## Outputs

本 Skill 复用现有 Response Envelope，并输出 `schema_version`、`investigation_summary`、`route_record`、`findings`、`ledger_events`、`artifact_refs` 和 `payload`。

Response `payload` 支持：

- `region_assessments`
- `format_hypotheses`
- `container_layout_candidates`
- `header_assessments`
- `directory_table_candidates`
- `block_table_candidates`
- `index_table_candidates`
- `record_boundary_candidates`
- `transform_hypotheses`
- `key_hypotheses`
- `key_verification_results`
- `known_plaintext_checks`
- `candidate_schema`
- `field_mappings`
- `validation_checks`
- `counter_evidence`
- `carved_artifact_refs`
- `recovered_artifact_refs`
- `excluded_routes`
- `route_candidates`
- `unresolved_questions`
- `required_next_action`
- `limits_source`
- `recovery_status`

`recovery_status` 只允许以下八个值：

| recovery_status | 判定规则 |
|---|---|
| `candidate_only` | 存在恢复候选，但尚未复现结构或变换 |
| `structure_reproduced` | 布局或字段结构已在多个记录中复现 |
| `key_candidate` | 存在有限 key Hypothesis，尚未通过独立验证 |
| `key_verified` | key 在批准范围内通过至少两类独立验证，但完整恢复尚未复现 |
| `recovery_reproduced` | 恢复步骤可重复执行，且输出经 parser 或独立结构检查验证 |
| `rejected` | 当前批准范围内所有相关 Hypothesis 都已明确证伪，且没有存活候选 |
| `unknown` | 输入或 Evidence 不足，或批准检查尚未全部执行 |
| `bounded_checks_exhausted` | 所有批准检查已完成，仍有无法在当前范围内验证或证伪的存活候选 |

不得创建其他 recovery status。`recovery_status` 只描述恢复验证结果，不得写入 Finding confidence、Route Step status、Handoff status、`route_status` 或 `execution_gate`。Finding、route candidate 与 key Hypothesis 的 `confidence` 继续使用 `high|medium|low`。

`candidate_schema` 必须包含字段 offset、length、type、endianness/encoding 假设、Evidence、反证和复现步骤；不能把未验证字段表述为最终格式。每个 carved/recovered Artifact 必须通过 `artifact_refs` 回查到 Artifact Record。

每个实际执行的 candidate check 必须在 `validation_checks` 中形成一条记录，至少包含：

- `check_id`
- `region_id`
- `transform_candidate_id`
- `key_candidate_id`，未使用时为 `null`
- `plaintext_candidate_id`，未使用时为 `null`
- `started_at`
- `ended_at`
- `result`
- `evidence_refs`

`check_id` 每次执行唯一；candidate ID 必须解析到 Request 中 `candidate_usability: executable` 的对应 item，`region_id` 必须解析到目标 region。candidate check 实际执行数等于本轮此类 `validation_checks` 记录数，并与计划组合总数、`max_candidate_checks` 一并记录。

`key_hypotheses` 每项至少记录：

- `candidate_id`
- `candidate_type`
- `fingerprint`
- `material_artifact_ref`，不存在时为 `null`
- `verification_status`
- `evidence_refs`
- `confidence`

原始 key、口令、recovery key、token、私钥、个人数据、敏感明文和完整敏感配置只能保存在受保护 Artifact，不得写入 Response 正文、Finding、Ledger Event 正文、`investigation_summary`、`required_next_action`、普通 stdout/stderr、日志或摘要。普通输出只记录类型、来源、受保护 Artifact 引用、fingerprint、脱敏摘要和验证结果。工具可能输出完整敏感值时，将原始 stdout/stderr 直接保存为受保护 Artifact，对外暴露或写入普通日志前脱敏；Ledger 只引用该 Artifact 或受控路径，不复制完整值。不能仅凭文件名、外部资料或单个明文命中设置 `key_verified`；该状态至少需要两类独立验证依据，例如 transform 后结构闭合与独立 checksum/parser 验证。

恢复并验证嵌套固件时，按 `docs/data-contracts.md` 8.13 向 Router 传递该派生 Artifact、直接来源、完整 Hash、bounded regions、结构 Evidence、Artifact/Finding 和本轮 Ledger Event。文件名或单个 magic 不足以生成 executable firmware candidate。

整体 `recovery_status` 每轮只能选择一个值。存在正面结果时按以下固定优先级选择最高项：

`recovery_reproduced` > `key_verified` > `structure_reproduced` > `key_candidate` > `candidate_only`

- `recovery_reproduced`：恢复步骤已复现，且输出通过 parser 或独立结构检查。
- `key_verified`：key 通过至少两类独立验证，但完整恢复尚未复现。
- `structure_reproduced`：布局或字段关系已经复现，即使仍存在未验证 key candidate。
- `key_candidate`：尚未复现结构或完整恢复，但存在存活的有限 key Hypothesis。
- `candidate_only`：仅存在恢复候选，尚无更高等级结果。

没有正面状态时，只有当前批准范围内所有相关 Hypothesis 都已明确证伪且没有存活候选，才选择 `rejected`；所有批准检查已完成但仍有无法在当前范围内验证或证伪的存活候选时，选择 `bounded_checks_exhausted`；输入或 Evidence 不足，或批准检查尚未全部执行时，选择 `unknown`。单个 Hypothesis rejected 不得自动导致整体 `rejected`；单项失败写入 `counter_evidence`、`validation_checks` 和 `excluded_routes`。状态选择依据必须写入 `investigation_summary` 或 `validation_checks`。

## Workflow

### Step 1: Validate Envelope, Route and Limits

1. 验证 Request Envelope、当前 Route Record、Route Step、Handoff、`visited_skills`、`hop_count` 和 `routing_policy.max_hops`。
2. 按 Inputs 规则解析 effective source、candidate regions、派生 Artifact、Evidence 引用和边界。
3. 验证 recovery-specific Evidence、所有非空 limits、三个 candidate item profile、candidate usability 和 material Artifact 引用。
4. 任一必要输入缺失时不得创建半完整执行记录；返回 Router 所需的 `required_next_action`。若 uncommon 尚未执行，Router 可选择 uncommon；已完成 uncommon bounded re-entry 后不得再次选择 uncommon，只能在合法 hop/visited 范围内请求 `large-artifact-strategy` 补充 bounded Evidence，否则返回 autopilot。

### Step 2: Register Evidence Scope

1. 登记或复用 source、slice、候选 material 和输出 Artifact Record。
2. 记录 source Artifact、offset、length、sampling method、Hash 状态、工作目录和 preservation status。
3. 为每次读取、parser、checksum、transform 和 carving 记录 Ledger Event；正面 Evidence 与反证都保留。

### Step 3: Reconstruct Container Layout

1. 在批准 regions 内验证 header 字段、长度闭合、字节序、编码和 checksum。
2. 重建 directory/block/index table 的起点、项宽、计数、指针与 region 边界关系。
3. 对 uncommon 提供的记录边界跨多个记录复现字段 mapping。
4. 输出 `container_layout_candidates`、table candidates、record boundaries、`candidate_schema` 和反证。

### Step 4: Validate Bounded Transform and Key Hypotheses

1. `max_candidate_checks` 存在且为正整数时，只用 `candidate_usability: executable` 的 Request candidates 建立实际组合；hint-only item 不执行、不计数。
2. 每个组合固定包含一个 region、一个 transform、零或一个 key、零或一个 plaintext；计划组合总数不得超过 budget，执行每个不同组合时计数加一。
3. 每次执行创建包含全部必需字段的 `validation_checks` 记录；实际记录数不得超过 `max_candidate_checks`。
4. 不生成新候选、不扩展字典、不枚举 keyspace。对每个 Hypothesis 同时记录成功条件、失败条件、输入范围、Evidence、反证和独立验证结果。
5. `max_candidate_checks` 缺失或为 `null` 时跳过本 Step 的 candidate validation，继续布局恢复，并设置要求候选检查预算的 `required_next_action`。
6. 敏感 material 仅写入受保护派生 Artifact；正文只写 fingerprint 和引用。

### Step 5: Perform Bounded Carving

只有同时满足以下条件才自动 carving：

1. 数据块由已验证 header、table、index 或 record boundary 指向。
2. source Artifact、offset 和 length 均可回查。
3. region 完全位于批准的 `candidate_regions` 内。
4. 单个派生 Artifact Record 的 `size <= max_slice_bytes`；该 limit 缺失时不得以 carving 扩大既有 bounded input。
5. 总读取量不超过 `max_total_bytes`。
6. 输出数量和范围有限，且写入批准工作目录。
7. 每个输出生成派生 Artifact Record、Hash 和匹配的 `source_artifact_id`。
8. original Artifact 保持只读。

缺少已验证边界、需要全源 carving、批量恢复或扩大范围时进入 Execution Gate，不先执行。

### Step 6: Reproduce and Falsify

1. 在多个记录或独立 Evidence 点复现 layout、field mapping 或 transform。
2. 用 parser、checksum、跨记录一致性或独立结构检查验证输出。
3. 失败的边界、transform、key、plaintext 与 parser 路线写入 `counter_evidence`、`validation_checks` 和 `excluded_routes`，不得静默删除。
4. 先汇总所有存活 Hypothesis 与已完成检查，再按 Outputs 的正面优先级或 fallback 条件设置本轮唯一 `recovery_status`；单项失败不直接决定整体状态。
5. 在 `investigation_summary` 或 `validation_checks` 记录状态选择依据。

### Step 7: Emit Response and Route Outcome

1. 输出完整 Response Envelope；每个 Finding 至少引用相关 Artifact 和 Ledger Event。
2. 默认返回 `forensic-autopilot`。没有新的当前可执行消费者时进入 Answer Gate。
3. 发现已验证嵌套固件派生 Artifact 时，附核心来源与 Evidence，在 `route_candidates` 记录 executable firmware candidate 后返回 Router；本 Skill 不解包或直接调用 firmware。
4. 发现已验证嵌套存储容器、独立卷或阵列成员 Artifact 时，附可回查 provenance、明确 Hash 状态、布局 Evidence 和本轮引用，记录 executable storage candidate 后返回 Router；本 Skill 不组装、解锁或直接调用 storage。
5. 恢复出独立样本或 payload Artifact，且具有明确恶意分析目标或独立可疑上下文时，附直接来源、Hash 状态、region 和本轮 Evidence，记录 executable malware candidate 后返回 Router；本 Skill 不执行样本或直接调用 malware。
6. 只有本轮产生新 Artifact 或 Finding，且 Handoff 章节全部条件满足时，才可最多一次返回 `forensic-router` 重评。
7. 本 Skill 不直接调用任何下游消费者，也不生成最终答案。

## Route Matrix

| Input Feature | Minimum Evidence | Result / Route | recovery_status | Gate |
|---|---|---|---|---|
| header + directory/block/index table 候选 | 字段、计数、指针和边界可在 region 内交叉验证 | 重建 layout 与 `candidate_schema` | `candidate_only` 或 `structure_reproduced` | No |
| uncommon 提供的重复记录边界 | 非空 region，加 candidate schema 或 structure hints，并有 Artifact/Finding/Ledger 引用 | 深化 field mapping 与跨记录复现 | `structure_reproduced`、`rejected` 或 `unknown` | No |
| executable transform/key/plaintext candidates | item profile 可解析；显式正整数 `max_candidate_checks`；计划与实际组合均不超预算 | bounded candidate validation | 按总体选择规则归约 | No |
| 只有 hint-only candidates | 可支持 Hypothesis 或结构路线，但无可执行 material | 只做布局恢复；设置 candidate budget/material 的 `required_next_action` | `candidate_only`、`structure_reproduced` 或 fallback | No |
| 需要枚举 keyspace 的 XOR 或简单混淆 | 候选不能由 Request 的有限集合表达 | 记录待授权动作 | `candidate_only` 或 `unknown` | Yes |
| 经验证表项指向的数据块 | table/index 与 source offset/length 可回查且满足 carving 条件 | bounded carving + 派生 Artifact | `structure_reproduced` 或 `recovery_reproduced` | No |
| 大范围 plaintext 或全源 encrypted needle | 需要超出 regions 的搜索 | 记录待授权范围与限制 | `candidate_only` 或 `unknown` | Yes |
| 高熵、单个 magic、扩展名或设备名 | 缺少第二类 recovery Evidence | 不触发恢复结论 | `candidate_only` 或 `unknown` | No |
| 固件候选 | 已验证嵌套固件派生 Artifact、container layout、Hash/size/直接来源与本轮 Ledger Event | Executable `firmware-iot-forensics` route candidate，经 Router 重评 | `candidate_only` 或当前更高合法值 | Router re-entry |
| 嵌套 RAID/LVM/加密卷候选 | 合法派生 Artifact、可回查 provenance、明确 Hash 状态、superblock/header 或层级 Evidence | Executable `nas-raid-encrypted-storage` candidate，经 Router 重评 | `candidate_only` 或当前更高合法值 | Router re-entry |
| PE/ELF/Mach-O/脚本/宏/APK/DEX 或 payload | 独立派生 Artifact、直接来源、Hash 状态，加明确目标或独立可疑上下文 | Executable `malware-forensics` candidate，经 Router 重评 | `candidate_only` 或当前更高合法值 | Router re-entry |
| 已识别标准容器或已有消费者 | parser/format Evidence 支持已实现消费者 | `route_candidates`，必要时 Router 重评 | 当前 bounded 检查所得合法值 | No |
| bounded 检查后仍未知 | 已保留所有检查、反证、限制和未决问题 | 返回 autopilot | `unknown` 或 `bounded_checks_exhausted` | No |

firmware candidate 使用 `current_availability: executable`，附 bounded regions、已验证嵌套固件 Artifact、直接来源、完整 Hash、结构 Evidence 和本轮引用。它仍不是 Route Step 或 Handoff。

storage candidate 使用 `current_availability: executable`，附合法嵌套 Artifact、可回查 provenance、明确 Hash 状态、bounded regions、层级 Evidence 和本轮 Ledger Event；大型、稀疏、流式或未物化视图允许 `deferred|unavailable`，region/member Hash 不得冒充其完整 Hash。只有 Router 可以创建正式 Handoff。

malware candidate 使用 `current_availability: executable`，附独立派生 Artifact、直接来源、明确 Hash 状态、适用 region、明确目标或独立可疑上下文，以及 Artifact/Finding/本轮 Ledger 引用。普通恢复文件、单一 magic、高熵、规则命中或 parser failure 不足以形成 executable candidate；只有 Router 可以创建正式 Handoff。

## Evidence Requirements

- 每个结论都必须成为引用 Artifact 和 Ledger Event 的 Finding；没有可回查来源的断言不是 Finding。
- 每个 candidate region 记录 source Artifact、integer offset、integer length、sampling method 与边界验证。
- 每次 header/table/index/record、checksum、parser、transform、key、plaintext 或 carving 检查记录工具、参数、时间、退出状态、输入范围与输出 Artifact。
- 每个 candidate check 的 `validation_checks` 必须记录 `check_id`、region/transform/key/plaintext ID、开始/结束时间、result 和 Evidence；同时记录计划组合总数、实际执行数以及 `max_candidate_checks` 的限制值或缺失状态。
- 正面 Evidence、反证、失败 Hypothesis、排除路线和未决问题都必须保留。
- carved/recovered Artifact 必须包含 Hash、`source_artifact_id`、offset/length provenance 和只读 source 关系。
- 嵌套固件派生 Artifact 必须记录直接来源、完整 Hash 和本轮 Ledger Event；firmware route basis 引用可复核结构 Evidence。
- 嵌套存储派生 Artifact 必须记录可回查 provenance、明确 Hash 状态、bounded regions 和本轮 Ledger Event；`deferred` 包含 `deferred_reason`，Finding/route basis 明示限制，storage route basis 引用可复核成员、header 或层级 Evidence。
- 恢复样本或 payload 必须记录直接来源、Hash 状态、bounded region 和可疑上下文；普通 executable 不自动进入 malware。
- 敏感 material 采用最小披露：正文仅保留 fingerprint 和受保护 Artifact 引用。
- 外部资料只能作为 hint；必须由当前 Artifact 的 bounded 静态检查独立复核。

## Handoff

正式入口链路为：

`uncommon-media-triage` → `forensic-router` → `proprietary-format-recovery`

uncommon 不直接调用本 Skill。它只创建 `current_availability: executable` 的 route candidate，并通过既有的、最多一次的 bounded re-entry 返回 Router。该 candidate 必须附非空 `candidate_regions`、`candidate_schema` 或 `upstream_structure_hints`，以及可回查 Artifact、Finding 和本轮 Ledger Event 引用；同一组字段必须保留在 re-entry 的顶层 `request.payload`，形成完整 proprietary payload profile，Router 不从嵌套 candidate 重建字段。

Router 是唯一消费者决策点。Router 完整验证 input、Route context、`visited_skills`、`hop_count`、limits、candidate item profile、candidate check budget 与 Execution Gate 后，才创建到本 Skill 的 Route Step 和 Handoff。至少一个可解析的 executable candidate，或一个不需要 key/plaintext candidate validation 的可执行布局恢复任务，必须存在；只有 hint-only candidates 时仍可因明确布局任务进入本 Skill，但 Handoff 必须声明不执行 key/plaintext validation。输入不足时，Router 按首次路由或已完成 re-entry 的状态选择 uncommon、`large-artifact-strategy` 或 autopilot，不创建半完整 Handoff。

autopilot 只执行 Router 返回的 proprietary 决策，原样传递 payload 和 Route context，不维护 recovery-specific 阈值。本 Skill 完成且没有新消费者时默认返回 autopilot 进入 Answer Gate。

本 Skill 只有产生新 Artifact 或 Finding 时，才可最多一次返回 Router。该 proprietary → Router Handoff 必须包含：

- 非空 `reentry_reason`
- 非空 `new_evidence_refs`，且每项指向本轮新 Ledger Event
- 本轮新 Ledger Event
- 合法 `hop_count` 和 `routing_policy.max_hops`

Router 重评后不得再次选择 `uncommon-media-triage` 或 `proprietary-format-recovery`。明确禁止 uncommon → Router → proprietary → Router → uncommon，以及 proprietary → Router → proprietary。没有其他当前可执行消费者时返回 autopilot。

当本轮产生已验证嵌套固件派生 Artifact 时，允许的正式后续链路为：

`proprietary-format-recovery` → `forensic-router` → `firmware-iot-forensics`

proprietary 不得直接调用 firmware。它只把已验证嵌套 Artifact 和核心 Evidence 返回 Router；Router 验证 `docs/data-contracts.md` 8.13 的最低输入、limits、Route context、visited/hop 和 Gate 后才创建 firmware Handoff。禁止 proprietary → Router → firmware → Router → proprietary、firmware → Router → firmware，以及 uncommon → Router → firmware → Router → uncommon。

当本轮产生已验证嵌套存储容器、独立卷或阵列成员 Artifact 时，允许的正式后续链路为：

`proprietary-format-recovery` → `forensic-router` → `nas-raid-encrypted-storage`

proprietary 只把派生 Artifact、可回查 provenance、明确 Hash 状态、bounded regions、结构 Evidence 和本轮引用返回 Router；Router 按 `docs/data-contracts.md` 8.14 验证输入、limits、Route context、visited/hop 和 Gate。禁止 storage → Router → proprietary → Router → storage、proprietary → Router → storage → Router → proprietary，以及 storage → Router → storage。

当本轮恢复出独立样本或 payload Artifact，并具有明确目标或独立可疑上下文时，允许的正式后续链路为：

`proprietary-format-recovery` → `forensic-router` → `malware-forensics`

proprietary 只返回直接来源、Hash 状态、region 和本轮 Evidence；Router 按 `docs/data-contracts.md` 8.15 验证输入、limits、Gate 与 visited/hop。禁止 proprietary → Router → malware → Router → proprietary，以及 malware → Router → malware。

## Execution Gate

以下操作在当前授权、批准工作目录、candidate regions 和 `analysis_limits` 内自动执行，`execution_gate.required=false`：

- 已有 candidate region 内的 bounded read。
- header、table、offset、length 和 checksum 验证。
- Request 中 item profile 完整、`candidate_usability: executable` 且有显式 `max_candidate_checks` 预算的 transform/key candidates。
- Request 中 item profile 完整、`candidate_usability: executable` 且有显式 `max_candidate_checks` 预算的 known-plaintext candidates。
- 字节序、编码、字段 offset 和 parser 一致性验证。
- 已验证边界内的 bounded carving。
- 在批准工作目录内创建有限派生 Artifact。
- 当前 limits 内登记 Artifact、Finding 和 Ledger Event。
- 返回 Router 重评。

自动 candidate validation 必须同时满足：候选由 Request 明确提供且 usability 为 executable；material Artifact 可解析；不生成新候选；不扩展字典；不枚举 keyspace；只读批准 regions；`max_candidate_checks` 存在且为正整数；计划组合与实际执行数均不超过该 budget；不超过 `max_total_bytes`、`max_slice_bytes` 和 `timeout_seconds`；输出在批准工作目录；不修改 original Artifact。`max_candidate_checks` 缺失或为 `null` 时不执行 transform/key/plaintext candidate validation，但可继续结构恢复并设置 `required_next_action`。

以下操作必须设置 `execution_gate.required=true` 并填写非空 `reason`，本 Skill 不得先执行：

- 生成、枚举或爆破 keyspace；字典扩展或组合候选。
- 长时间恢复、长时间解密或批量 key 测试。
- 全文件扫描、全量 strings 或全源 known-plaintext 搜索。
- 超出 candidate regions 的读取。
- 大范围 carving、批量恢复或超出 analysis limits。
- 安装工具或依赖。
- 联网、在线检索或上传第三方。
- 执行程序、脚本、宏或固件；动态分析或沙箱。
- RAID/LVM 激活、解锁或 mount。
- 修改 original Artifact。
- 向未批准路径持久化恢复结果。

## Stop Conditions

- Request Envelope、当前 Route Record、Artifact/Finding/Ledger 引用或 recovery-specific Evidence 无法验证。
- effective source 为空、source size 未知或无效、candidate region 为空/越界，或派生 Artifact provenance 不匹配。
- `visited_skills` 已包含本 Skill，或 Route 的 hop/loop 约束不合法。
- 显式 limit 无效、无法强制或已达到；保留已完成结果和 `required_next_action`。
- candidate validation 被请求但 `max_candidate_checks` 缺失、为 `null` 或无效；跳过候选验证，保留结构恢复结果并要求预算，不把该情况自动视为 Gate。
- 候选组合计划无法在预算内闭合，或下一步需要 Execution Gate；记录原因并等待授权。
- 所有批准检查已完成、仍有无法在当前范围内验证或证伪的存活候选时，设置 `bounded_checks_exhausted` 并返回 autopilot。
- 恢复步骤已复现，或当前 Evidence 只能维持 candidate/unknown；输出 Response 并返回 autopilot。

unknown material、目标缺失或单个候选失败本身不是停止条件；仍有批准范围内的安全检查时继续，并保留反证。

## Prohibited Actions

- 不修改 original Artifact，不可写挂载，不向未批准路径写出结果。
- 不生成、扩展、枚举或爆破 keyspace，不执行无限制恢复。
- 不默认全文件扫描、全量 strings、全源 plaintext 搜索、大范围 carving 或批量恢复。
- 不执行程序、脚本、宏、固件或检材内代码，不做动态分析或沙箱。
- 不联网、在线检索或上传第三方，不默认安装依赖。
- 不解包固件或遍历 rootfs。
- 不组装 RAID，不激活 LVM，不解锁或挂载加密卷。
- 不做 CAN、NMEA、GPS、传感器和时间序列的首次结构识别。
- 不做数据库业务语义查询或 IOC 深度提取。
- 不把原始 key、口令、token、个人数据或敏感明文写入 Response、Finding 或 Ledger Event 正文。
- 不把扩展名、设备名、单个 magic、单独熵值或外部资料当作恢复确认。
- 不直接调用其他消费者，不生成最终答案，不绕过 Answer Gate。

## Notes

- 本 Skill 是 bounded 静态恢复消费者，不是通用解密、动态执行或报告生成工具。
- `candidate_schema` 是可复现的候选解释，必须同时保留 Evidence、反证和未决问题。
- `recovery_status` 与 Evidence confidence、Route 状态和 Execution Gate 相互独立。
- `large-artifact-strategy` 只提供 bounded regions 和 Evidence，不能决定或直接调用本 Skill。
- firmware、storage 和 malware 已可执行，但只能由 Router 决定。
