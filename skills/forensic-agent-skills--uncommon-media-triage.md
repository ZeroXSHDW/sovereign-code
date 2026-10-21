---
name: uncommon-media-triage
description: 非常见介质结构识别与分流。基于可复核的记录边界、字段关系和反证，对固定记录、TLV、CAN/CAN FD-like、NMEA、GPS、传感器、时间序列和自定义数据库页生成候选结构与路由候选。
---

# uncommon-media-triage

## Purpose

uncommon-media-triage 位于 `file-triage`、按条件触发的 `large-artifact-strategy` 与 `forensic-router` 之后，负责对非常见、未知但显示重复结构的 Artifact 或 bounded candidate region 做只读结构识别。它验证记录边界、字段关系和反证，输出 `candidate_schema`、Finding 和 route candidates；当 Evidence 支持专有格式恢复或固件静态分析时，它只生成对应 executable candidate 并返回 Router，不直接做恢复、固件解包或消费者调用。它不做解密、固件解包、存储激活、恶意样本动态分析、数据库业务语义查询或最终答案生成。

## Use When

只有存在可回指 Artifact 的结构证据时才进入本 Skill，例如：

- 至少三个候选记录边界重复出现，且字段偏移与记录长度具有稳定关系。
- bounded sample 中出现可验证的 TLV、CAN/CAN FD-like、NMEA、GPS、传感器或时间序列模式。
- 自定义数据库候选存在重复 page header、固定页长、slot 或 record directory 线索。
- 低—中熵区域同时具有重复边界、常量字段、长度闭合、checksum 或其他结构证据。
- `large-artifact-strategy` 已提供 candidate region、sampling result 或 bounded slice，需要做结构级验证。

以下信息不能单独触发本 Skill：文件扩展名、设备名称、品牌、单个 magic、单个时间戳、单个坐标、unknown 分类、单独的低熵或高熵结果。

本 Skill 只能由 `forensic-router` 首次选择；Router 调用时必须提供至少一个合法的 bounded candidate region，并在 `request.context` 中包含当前 Route Record。若 `visited_skills` 已包含 `uncommon-media-triage`，Router 不得再次选择本 Skill。

## Inputs

本 Skill 复用现有 Request Envelope：

| Field | Required | Description |
|---|---|---|
| `request.material_info.artifact_refs` | Yes | 输入 Artifact 引用；路径、Hash 和 preservation status 从 Artifact Record 获取 |
| `request.material_info.material_type` | Yes | 上游材料分类，不作为单独路由依据 |
| `request.material_info.triage_notes` | Yes | 结构候选、候选区域、负面验证及其 Evidence 引用 |
| `request.material_info.size_summary` | Recommended | 总字节数、文件数和最大文件大小 |
| `request.objective` | Recommended | 调查目标；缺失时执行中立结构识别 |
| `request.objective_status` | Yes | `explicit`、`inferred` 或 `unknown` |
| `request.context` | Yes | 当前 Route Record、step、Finding 和 Ledger Event 引用；由 Router 调用时必须包含当前 Route Record |
| `request.payload` | Yes | 本 Skill 专用输入 |

`request.payload` 使用以下字段：

| Field | Required | Description |
|---|---|---|
| `source_artifact_refs` | Recommended | 非空时作为 source Artifact 引用列表；缺失或空数组时复用 `request.material_info.artifact_refs` |
| `candidate_regions` | Yes | 非空的 bounded 区域列表；空数组或缺失时不得调用本 Skill |
| `upstream_signature_hits` | Recommended | 已验证的签名命中和验证状态 |
| `upstream_sampling_results` | Recommended | 上游采样结果及其 Ledger Event 引用 |
| `entropy_summary` | Recommended | 区域熵和分布摘要；不得单独作为路由依据 |
| `structure_hints` | Recommended | 重复边界、时间序列、TLV 或其他结构提示 |
| `requested_checks` | Recommended | 本轮允许执行的结构检查 |
| `analysis_limits` | Recommended | 最大读取字节、区域数、slice 大小、运行时间和其他批准上限 |

每个 `candidate_regions` 项至少包含：

- `region_id`
- `source_artifact_ref`
- `derived_artifact_ref`，不存在派生 Artifact 时为 `null`
- `offset`：非负整数
- `length`：正整数
- `sampling_method`

`offset` 只接受整数且必须 `>= 0`；不得接受十六进制字符串、带单位字符串或其他文本格式。`length` 只接受正整数。对应 source Artifact Record 的 `size` 必须是已知的非负整数，才能验证 `offset + length <= source Artifact size`；size 缺失、为 `null` 或类型无效时不得调用本 Skill，并记录 `required_next_action`。

定义 `effective_source_artifact_refs`：`request.payload.source_artifact_refs` 非空时使用该列表；缺失或空数组时使用 `request.material_info.artifact_refs`。有效列表必须非空，每个引用必须能解析到 Artifact Record，每个 `candidate_region.source_artifact_ref` 必须属于该列表。`derived_artifact_ref` 存在时必须能解析到 Artifact Record，且其 `source_artifact_id` 必须等于 region 的 `source_artifact_ref`。任何缺失或冲突都禁止调用本 Skill，并记录原因和 `required_next_action`。

显式 `analysis_limits` 按字段分别检查：

- `candidate_regions` 数量 `<= max_regions`
- 每个 `region.length <= max_bytes_per_region`
- 所有 `region.length` 总和 `<= max_total_bytes`
- `derived_artifact_ref` 非空时，解析派生 Artifact Record，并验证 `derived Artifact Record.size <= max_slice_bytes`
- 实际运行时间 `<= timeout_seconds`

所有非空 limit 字段必须是正整数：`max_regions > 0`、`max_bytes_per_region > 0`、`max_total_bytes > 0`、`max_slice_bytes > 0`、`timeout_seconds > 0`。字段为 `null` 或缺失时，不应用该项限制。非空但非整数或小于等于 0 时输入不可执行。

`max_slice_bytes` 生效且 `derived_artifact_ref` 非空时，必须解析对应派生 Artifact Record，并使用该 Record 的 `size` 校验；不得新增或读取 `slice.length`。派生 Artifact size 为 `null`、类型无效或 Artifact 无法解析时，不能通过该项输入校验。非空 `timeout_seconds` 必须能在调用时强制执行，并持续记录实际运行时间。任一显式限制超出，或无法强制 timeout 时，不得开始或继续本 Skill；记录具体超限字段、实际值、限制值和 `required_next_action`。

`analysis_limits` 缺失时采用隐式 bounded 限制：只读取已提供的 `candidate_regions`，不扩大任何 offset 或 length，不请求新的 slice，不执行全文件扫描，并在输出中记录 `limits_source: implicit-bounded-input`。提供显式限制时记录 `limits_source: explicit`。

## Outputs

本 Skill 复用现有 Response Envelope，并输出 `schema_version`、`investigation_summary`、`route_record`、`findings`、`ledger_events`、`artifact_refs` 和 `payload`。

`payload` 至少支持：

| Field | Description |
|---|---|
| `region_assessments` | 每个 candidate region 的结构评估、Evidence 和反证 |
| `structure_type` | 主要结构类型或 `unknown` |
| `classification_status` | `valid`、`plausible`、`weak_candidate`、`rejected` 或 `unknown` |
| `candidate_record_sizes` | 有 Evidence 支撑的候选记录长度 |
| `candidate_schema` | 候选字段、偏移、类型、字节序、长度和依据 |
| `key_fields` | timestamp、counter、id、tag、length、flags、lat/lon、value 等候选字段 |
| `boundary_evidence` | 重复边界、对齐、sync、长度闭合和 page boundary Evidence |
| `validation_checks` | 已执行检查、输入范围、结果和 Ledger Event 引用 |
| `counter_evidence` | 反例、失败校验、冲突记录和被否定的 Hypothesis |
| `route_candidates` | 有 Evidence 支撑的后续候选路线 |
| `excluded_routes` | 已排除路线及其 Finding/Evidence 引用 |
| `sampling_requests` | 需要 LAS 补充的 bounded region；不得自行扩大范围 |
| `unresolved_questions` | 尚未解决且不能从现有 Evidence 回答的问题 |
| `limits_source` | `explicit` 或 `implicit-bounded-input` |

当输出 proprietary executable candidate 时，Response 顶层 `payload` 还必须原样保留完整 proprietary transfer profile：`source_artifact_refs`、非空 `candidate_regions`、`upstream_region_assessments`、`upstream_structure_hints`、`candidate_schema`、`route_basis`、`artifact_refs`、`finding_refs`、`ledger_event_refs`、所有已存在的 header/table/record/transform/key/plaintext hints、`counter_evidence`、`requested_checks` 和 `analysis_limits`。`route_candidates` 项只声明 candidate skill、availability、Evidence 与 next action，不嵌套或替代该 profile。Router 必须转发这份顶层 payload，不从 candidate 重建字段。

其中三个 candidate arrays 必须保留以下最小 item profile：

- `transform_hypotheses`: `candidate_id`, `transform_type`, `parameters`, `target_region_ids`, `evidence_refs`, `candidate_usability`
- `key_material_candidates`: `candidate_id`, `candidate_type`, `material_artifact_ref`, `fingerprint`, `target_region_ids`, `evidence_refs`, `candidate_usability`
- `known_plaintext_candidates`: `candidate_id`, `material_artifact_ref`, `fingerprint`, `encoding`, `target_region_ids`, `evidence_refs`, `candidate_usability`

`candidate_usability` 只能是 `executable|hint-only`。uncommon 只能把具有实际验证数据、可解析 target regions 和 Evidence 的 item 标成 executable；非空 `material_artifact_ref` 必须可解析到 Artifact Record。只有 fingerprint 的 key/plaintext item 固定为 hint-only。hint-only 只支持 Hypothesis、Finding 或 `required_next_action`，不得表示可自动执行，也不进入 candidate check 组合。原始 key、敏感 plaintext 和 token 继续只存放在受保护派生 Artifact 中，transfer profile 正文只保留引用和 fingerprint。

若 transfer profile 请求 transform/key/plaintext validation，必须同时提供正整数 `analysis_limits.max_candidate_checks`。该字段缺失或为 `null` 时，uncommon 仍可提出明确的布局恢复任务，但必须设置要求候选检查预算的 `required_next_action`，且 route basis 明确禁止候选 validation；不得仅凭数组有限声称候选可执行。只有 hint-only items 时，只有存在无需 key/plaintext validation 的可执行布局恢复任务才可输出 proprietary executable route candidate。

firmware executable candidate 只传递 `docs/data-contracts.md` 8.13 定义的核心字段：bounded regions、结构 Evidence、route basis、Artifact/Finding、本轮 Ledger Event、适用 limits 和已有 container/filesystem/architecture/partition hints。单个 magic、扩展名、品牌、设备名、熵值或外部资料不能生成 executable candidate；输入不足时只记录 Hypothesis 和 `required_next_action`。

Response `region_assessments.offset` 必须继续使用非负整数，并与 Request 中对应 region 的 offset 保持一致；不得序列化为十六进制、带单位字符串或其他文本。

`classification_status` 只描述候选结构的验证状态。Finding、Ledger Event 和 route candidate 的 `confidence` 只能使用 `high`、`medium` 或 `low`。`classification_status` 不得写入 Finding confidence、`route_status`、Route Step status、Handoff status 或 `execution_gate`。

| classification_status | 判定规则 |
|---|---|
| `valid` | 核心结构约束全部通过，可跨多个记录复现，无实质反证 |
| `plausible` | 核心关系成立，但样本数量、checksum 或部分字段仍不足 |
| `weak_candidate` | 存在结构信号，但缺少第二类独立 Evidence |
| `rejected` | 边界、长度、checksum、字段关系或跨记录一致性明确失败 |
| `unknown` | Evidence 不足，既不能支持也不能排除 |

本 Skill 只能输出 `candidate_schema`。任何候选字段都必须保留不确定项和反证，不得表述为已经确认的最终格式。

## Workflow

### Step 1: Validate Scope and References

1. 验证 Request Envelope 和当前 Route Record；按 Inputs 规则计算非空 `effective_source_artifact_refs`，并解析每个 Artifact Record。
2. 要求 `candidate_regions` 非空；验证每个 region 的 source 归属、整数 offset、正整数 length、sampling method、派生 Artifact 关系，以及已知非负 source Artifact size 对应的边界。
3. 验证所有非空显式 limit 均为正整数，再分别执行计数、单 region、总字节、派生 Artifact Record size 和运行时间检查；`null` 或缺失项跳过。
4. 任一引用、归属、边界或显式 limit 检查失败时，记录具体原因和 `required_next_action`，不得开始本 Skill。
5. 确认 1GB+ source 已经过 `large-artifact-strategy`，当前输入为 bounded region 或派生 slice。
6. 若 `analysis_limits` 整体缺失，启用 `implicit-bounded-input`；不得扩大 region、请求新 slice 或扫描完整文件。

### Step 2: Register Evidence Scope

1. 为 source、slice 和派生样本登记或复用 Artifact Record。
2. 派生 slice 使用 `source_artifact_id` 回指来源，并记录 offset、length、sampling method 和保存路径。
3. 解析 Hash 状态；`deferred` 或 `unavailable` 必须保留原因，不阻断安全的 bounded analysis。

### Step 3: Perform Bounded Sampling

1. 只读取已批准的 candidate region；仅当显式 `analysis_limits` 已允许时，才可读取额外头部或尾部区域。
2. 计算 bounded entropy、字节分布、重复块、候选对齐和长度因数。
3. 每个工具或 parser 调用记录命令、时间、退出码、stdout/stderr 与输出 Artifact。
4. 持续检查实际运行时间；达到非空 `timeout_seconds` 时立即停止新的分析动作并保留现有结果。
5. 达到其他显式 `analysis_limits` 或隐式 candidate region 边界时停止扩展并保留现有结果。

### Step 4: Generate and Falsify Structure Hypotheses

1. 为固定记录、TLV、CAN/CAN FD-like、NMEA、GPS、传感器、时间序列和自定义数据库页建立独立 Hypothesis。
2. 对每个 Hypothesis 同时执行正面验证和反证验证。
3. 单个 magic、时间戳、坐标或熵值只能作为 hint，不能独立产生正面 Finding。
4. 只有可跨至少三个记录或多个独立 Evidence 点复核的关系才能进入 `candidate_schema`。

### Step 5: Validate Structure-Specific Invariants

按照 Route Matrix 检查记录边界、length closure、checksum、字段范围、跨记录一致性和容器关系。不得为了使 Hypothesis 成立而丢弃冲突记录；冲突必须进入 `counter_evidence`。

### Step 6: Score Assessments

1. 根据正面 Evidence、反证和未决问题设置 `classification_status`。
2. 使用 `high|medium|low` 表达 Finding 和 route candidate 的 Evidence 置信度。
3. `unknown` 表示当前证据不足，不是自动停止或失败状态。

### Step 7: Build Route Candidates

1. 结构验证已完成，且没有新的当前可执行消费者路线时，返回 `forensic-autopilot` 进入 Answer Gate。
2. 发现 Server、Web、Database 或 Docker 的当前可执行路线时，返回 `forensic-router` 重评；不得由本 Skill直接调用这些消费者。
3. 发现专有封装、table/layout、XOR/key-like 或 known-plaintext recovery Evidence 时，先按 transfer profile 校验 item usability、material Artifact 和 candidate budget。至少存在一个可解析 executable candidate，或存在无需 key/plaintext validation 的可执行布局恢复任务时，才在 `payload.route_candidates` 记录 `current_availability: executable` 的 `proprietary-format-recovery` 候选并返回 Router；只有 hint-only 且没有布局任务时仅记录 Hypothesis/Finding/`required_next_action`。本 Skill 不直接调用该消费者。
4. 发现经验证 firmware container、rootfs、partition、segment、boot metadata 或 component relationship 时，附 bounded regions、结构 Evidence 和核心引用，在 `payload.route_candidates` 记录 executable firmware candidate 后返回 Router。本 Skill 不解包或直接调用 firmware。
5. 发现独立 RAID/LVM/pool/多成员文件系统或加密卷结构时，附 bounded regions、member/layer Evidence 和核心引用，记录 executable `nas-raid-encrypted-storage` candidate 后返回 Router。存在 PVE、Proxmox、Ceph、vSphere、vSAN、VM、Container、Snapshot、虚拟磁盘映射、已有 `cluster-virtualization-forensics` Route，或已有 server rebuild plan 明确拥有该存储任务时，保持 server/cluster 路线优先；普通服务器内容尚未暴露时，如果独立 RAID、加密卷或卷管理层是前置条件，仍可形成 executable storage candidate，经 Router 决策。本 Skill 不组装、解锁或直接调用 storage。
6. 发现有效样本或 bounded payload，且具有明确恶意分析目标或独立可疑上下文时，附 source/region、Hash 状态和本轮核心引用，记录 executable malware candidate 后返回 Router。本 Skill 不执行、反混淆或深入提取 IOC。
7. PCAP、浏览器历史和完整移动设备取证写入 `excluded_routes`，并生成同时引用相关 Artifact 和本轮 Ledger Event 的 scope-limitation Finding。随后返回 `forensic-autopilot`；只有新 Evidence 需要重新判断消费者时，才按 Handoff 规则返回 `forensic-router`。

### Step 8: Emit Response and Handoff

1. 输出完整 Response Envelope，所有 Finding 绑定 Ledger Event 和 Artifact。
2. 默认返回 `forensic-autopilot`，由 `answer-gate` 校验证据和范围限制，再由 `report-writer` 输出结果。
3. 仅满足 Handoff 章节全部条件时，创建一次 uncommon → `forensic-router` bounded re-entry。

## Route Matrix

| Input Feature | Minimum Evidence | Result / Candidate Route | Counter-Evidence / Exclusion | Gate |
|---|---|---|---|---|
| 固定长度记录 | 至少三个重复边界；字段偏移稳定；记录长度和对齐闭合 | `fixed_record` assessment | 只有文件大小可整除，或记录间关键偏移漂移 | No |
| TLV | tag 重复；length 不越界；value 消耗闭合 | `tlv` assessment | length 越界、尾部长期不闭合、tag 仅单次出现 | No |
| Classic CAN / CAN FD-like | ID 编码、控制字段、DLC 映射、payload 长度和跨帧关系一致 | `can_like` assessment | 不硬编码采集记录总长；任意 8 字节块不能视为 CAN | No |
| CAN 采集容器记录 | 容器 timestamp/header 与内层 Classic CAN 或 CAN FD 字段可区分且跨帧稳定 | `can_container` assessment | 容器长度不能代替总线 payload 长度 | No |
| NMEA | 多条 sentence；talker/type 合理；checksum 可复核 | `nmea` assessment | 单个 `$GP`、单条未校验 sentence 或随机文本碰撞 | No |
| GPS 轨迹 | 多个点；时间和坐标连续；范围合理；字段格式稳定 | `gps_track` assessment | 单个坐标、无时间关联或超出合法范围 | No |
| 传感器记录 | 采样间隔、counter/timestamp、字段布局和数值分布跨记录一致 | `sensor_record` assessment | 单个看似合理的数值或无稳定采样关系 | No |
| 时间序列 | 多个事件按可解释间隔排列，时间编码和相邻差值一致 | `time_series` assessment | 单个时间戳或需要无依据时区假设 | No |
| 自定义数据库页 | 重复 page header、固定页长、slot 或 record directory 可复核 | `custom_database_page` assessment | 标准数据库已识别时交 Router；本 Skill 不做业务语义查询 | No |
| 低—中熵结构二进制 | 重复边界，加上常量字段、长度闭合、checksum 或其他独立结构 Evidence | 对应结构 assessment | 熵值本身、品牌或扩展名不足以触发 | No |
| Server/Web/Database/Docker 证据 | 当前 Artifact/Finding 支持已实现消费者 | `forensic-router` re-evaluation | 必须产生新 Evidence；由 Router 按当前未解决层级决定 | No |
| 专有 header/table/layout 或 XOR/key-like/known-plaintext 路线 | 可回指的 region、结构或变换 Evidence；附 candidate schema/structure hints 与本轮引用 | Executable `proprietary-format-recovery` route candidate，经 Router 决策 | unknown、高熵、单个 magic、扩展名或设备名本身不足 | Router re-entry |
| 固件容器/rootfs | 经验证结构、bounded regions、Artifact/Finding/本轮 Ledger Event | Executable `firmware-iot-forensics` candidate，经 Router 决策 | 单个 magic、品牌、设备名或熵值不足 | Router re-entry |
| 独立 RAID/LVM/pool/加密存储 | superblock/header/成员或层级 Evidence、bounded regions 和本轮引用 | Executable `nas-raid-encrypted-storage` candidate，经 Router 决策 | PVE/Proxmox/Ceph、vSphere/vSAN、VM/Container/Snapshot/虚拟磁盘映射、已有 `cluster-virtualization-forensics` Route 或 server rebuild plan 明确拥有该存储任务时仍由 server/cluster 负责；普通服务器存储前置层不排除本 candidate | Router re-entry |
| PE/ELF/Mach-O/脚本/宏/APK/DEX/独立 payload | 有效样本或 bounded region，加明确恶意分析目标或独立可疑上下文 | Executable `malware-forensics` candidate，经 Router 决策 | 普通 executable、固件组件、单一规则命中、高熵或 parser failure 不自动转出 | Router re-entry |
| PCAP/浏览器历史/完整移动设备 | 来源类型得到确认 | 写入 `excluded_routes`；生成带 Artifact 和 Ledger Event 引用的 scope-limitation Finding；返回 autopilot，或需要重评时返回 Router | 不得退化为结构化二进制路线 | No |
| unknown | 已保留 Artifact、bounded sample、负面 Finding、排除路线和未决问题 | 继续有限测试；无新 Evidence 时返回 autopilot | unknown 本身不是停止条件 | No |

CAN 识别不得把采集容器记录总长度固定为 16、32 或 64 字节，也不得把 DLC 简化为固定小于等于 8。必须区分 Classic CAN、CAN FD 与外层采集记录，并依据实际控制字段和 DLC 映射验证 payload 长度。

`uncommon-media-triage` 自身不得设置 `route_decision: no-compatible-skill`。只有 `forensic-router` 可以产生该路由决策；本 Skill 只记录 `excluded_routes`、scope-limitation Finding 和必要的 Router 重评 Handoff。

所有 Recovery route candidate 必须包含：

- `candidate_skill`
- `route_basis`
- `artifact_refs`
- `finding_refs`
- `confidence`
- `current_availability: executable|pending`
- `required_next_action`

`proprietary-format-recovery` candidate 使用 `current_availability: executable`，并且其同层顶级 `payload` 必须附非空 `candidate_regions`、`candidate_schema` 或 `upstream_structure_hints`、三个候选数组的完整 item profile、可回查 Artifact/Finding 引用，以及 uncommon 本轮 Ledger Event 引用。它仍不是消费者 Route Step 或调用记录；只有 Router 完成完整输入、Route context、candidate usability、budget、limits、Gate 和防循环校验后才能创建正式 Handoff。

`firmware-iot-forensics` candidate 使用 `current_availability: executable`，附 bounded regions、结构 Evidence、Artifact/Finding 和本轮 Ledger Event；详细共享字段引用 `docs/data-contracts.md` 8.13。candidate 不是 Route Step 或 Handoff，只有 Router 可以创建正式调用。

`nas-raid-encrypted-storage` candidate 使用 `current_availability: executable`，附 source/member refs、bounded regions、storage/layer/topology hints、Artifact/Finding 和本轮 Ledger Event；共享字段引用 `docs/data-contracts.md` 8.14。candidate 不是 Route Step 或 Handoff，只有 Router 可以创建正式调用。

`malware-forensics` candidate 使用 `current_availability: executable`，附 source Artifact、适用 bounded regions、明确 Hash 状态、目标或独立可疑上下文、Artifact/Finding 和本轮 Ledger Event；共享字段引用 `docs/data-contracts.md` 8.15。candidate 不是 Route Step 或 Handoff，只有 Router 可以创建正式调用。

## Evidence Requirements

- 每个 source、slice 和派生样本必须登记 Artifact；派生 slice 使用 `source_artifact_id` 回指来源。
- 精确记录 source Artifact、offset、length、sampling method 和保存路径。
- Hash 使用现有 Artifact Record 的 `verified|provided|deferred|unavailable` 状态；未完成时记录原因。
- 每次结构检查记录工具、命令、开始/结束时间、退出码、stdout/stderr 和输出 Artifact。
- 正面 Evidence 与反证都必须记录；被否定的 Hypothesis 不能静默删除。
- 每个 Finding 至少引用一个 Ledger Event 和相关 Artifact。
- Route 决策记录支持依据、排除依据、Artifact/Finding 引用和 `high|medium|low` confidence。
- 文件扩展名、设备名、品牌、单个 magic、单个时间戳、单个坐标或熵值不得作为独立 Finding 依据。
- GPS、健康和个人数据仅保留完成 objective 所需的最小 Evidence；报告中不复制无关原始记录。

## Handoff

主链为：

`file-triage` → `large-artifact-strategy`（按条件）→ `forensic-router` → `uncommon-media-triage` → `forensic-autopilot` → `answer-gate` → `report-writer`

`proprietary-format-recovery` 是当前可执行 Recovery 消费者，但正式链路只能是：

`uncommon-media-triage` → `forensic-router` → `proprietary-format-recovery`

本 Skill 不得直接调用 proprietary。它只输出满足上述字段要求的 executable route candidate，并通过下述 bounded re-entry 返回 Router。

`firmware-iot-forensics` 也是当前可执行 Recovery 消费者，正式链路只能是：

`uncommon-media-triage` → `forensic-router` → `firmware-iot-forensics`

本 Skill 不得直接调用 firmware，只输出 bounded regions、结构 Evidence、核心引用和 executable candidate，再通过同一次 bounded re-entry 返回 Router。

`nas-raid-encrypted-storage` 也是当前可执行 Recovery 消费者，正式链路只能是：

`uncommon-media-triage` → `forensic-router` → `nas-raid-encrypted-storage`

本 Skill 只形成独立存储 candidate 并返回 Router，不直接调用、组装或解锁。

`malware-forensics` 也是当前可执行 Recovery 消费者，正式链路只能是：

`uncommon-media-triage` → `forensic-router` → `malware-forensics`

本 Skill 只形成样本 candidate 并返回 Router，不执行样本、不反混淆或直接调用 malware。

允许一次 bounded re-entry。这里的 re-entry 仅指本 Skill 发出的单向 Router 重评 Handoff：

`uncommon-media-triage` → `forensic-router`

必须同时满足：

1. 本 Skill 产生了新的 Artifact 或 Finding。
2. Handoff 的 `new_evidence_refs` 非空，并且每个引用都指向本轮新 Ledger Event。
3. `reentry_reason` 明确说明新 Evidence 如何改变候选路线。
4. `visited_skills` 和 `hop_count` 符合 Route Record，且未超过 `routing_policy.max_hops`。
5. 同一 route 和 evidence scope 最多执行一次 uncommon → Router re-entry。
6. 没有新 Evidence 时禁止 re-entry。
7. Router 重评时 `visited_skills` 已包含 `uncommon-media-triage`，因此不得再次选择 uncommon；输入完整且 proprietary、firmware、storage 或 malware candidate 通过对应 input gate 时，Router 才可选择该消费者并加入 `visited_skills`。输入不足时只能在合法 hop/visited 范围内请求 `large-artifact-strategy` 补充 bounded Evidence，否则返回 `forensic-autopilot`；任何分支都不创建半完整 Handoff。

`forensic-router` → uncommon → Router → uncommon、uncommon → Router → firmware → Router → uncommon，以及 uncommon → Router → malware → Router → uncommon 的循环属于禁止路线。

## Execution Gate

以下操作在显式 `analysis_limits` 或 `implicit-bounded-input` 和现有授权范围内可只读自动执行，`execution_gate.required=false`：

- stat 和 Hash 策略判断。
- bounded read，以及已批准头部、尾部和 candidate region 读取。
- bounded sampling、熵和字节分布计算。
- 固定记录、TLV、CAN/CAN FD-like、NMEA checksum、GPS、时间和传感器字段验证。
- 对数据文件运行静态 parser，但不执行检材内代码。
- 在既定工作区和限制内生成小型 slice、日志、Ledger Event 和 Finding。
- 请求 Router 重评。
- 仅在存在显式 `analysis_limits` 且其允许补充采样时，请求 LAS 在现有分析范围内补充 bounded slice；隐式限制下不得请求新 slice。

以下操作改变状态或扩张授权范围，必须设置 `execution_gate.required=true` 并填写非空 `reason`，本 Skill 不得先执行：

- 执行样本、脚本、宏或固件程序。
- 动态分析、沙箱、联网或上传第三方。
- RAID assembly、LVM activation、解锁加密卷或 mount。
- 可写挂载或修改原始检材。
- 全文件盲扫、全量 strings、递归解包或大范围 carving。
- 超过显式 `analysis_limits`，或超出 `implicit-bounded-input` 已提供 region 的读取、导出或 slice 扩展。
- 爆破、长时间解密、批量恢复或安装工具。
- 任何超出当前用户授权范围的操作。

Gate 只表达待授权操作，不得使用 `classification_status` 作为 Gate 状态或原因。

## Stop Conditions

- source Artifact 无法读取，且不能取得任何元数据、bounded sample 或有效引用。
- candidate region 越界或来源不可回指，且上游不能提供修正后的 Artifact/Finding。
- 达到显式 `analysis_limits` 或隐式 candidate region 边界；保留已完成结果。只有显式限制允许时才能提出 bounded sampling request，隐式限制下不得请求新 slice。
- 下一步需要 execution gate；记录原因并等待授权。
- 已识别 proprietary、firmware、storage 或 malware executable candidate；停止越界深入，返回候选、Evidence 和范围限制，由 Router 决策。
- 结构验证完成；返回 `forensic-autopilot` 进入 Answer Gate。
- 连续有限检查没有新 Evidence；保留 `unknown`、负面 Finding、排除路线和未决问题，返回 autopilot 生成限制报告。

unknown material、unknown `structure_type` 或 objective 缺失本身都不是停止条件。仍有安全 bounded test 时继续；只有没有安全路径、达到限制或需要新授权时才停止。

## Prohibited Actions

- 不修改 original Artifact，不进行可写挂载。
- 不执行样本、脚本、宏、固件程序或解包后的内容。
- 不推导 XOR key，不解密或做 known-plaintext recovery。
- 不解包固件，不遍历 rootfs。
- 不组装 RAID，不激活 LVM，不解锁或挂载加密卷。
- 不做动态分析、沙箱、联网、第三方上传或 IOC 深度提取。
- 不做数据库业务语义查询。
- 不分析 PCAP、浏览器历史或完整移动设备取证材料。
- 不默认全文件扫描、全量 strings、递归解包、大范围 carving 或批量恢复。
- 不按扩展名、设备名称、品牌或单一弱信号确认结构。
- 不生成最终答案，不绕过 `answer-gate` 和 `report-writer`。

## Notes

- 本 Skill 是结构识别与分流层，不是恢复、解密、执行或报告生成工具。
- `candidate_schema` 必须保留 Evidence、反证和未决问题。
- 1GB+ Artifact 必须先经过 `large-artifact-strategy`；较小 Artifact 也必须遵守 bounded read，以及显式 `analysis_limits` 或 `implicit-bounded-input`。
- Server、Web、Database 和 Docker 的现有路线保持不变，由 `forensic-router` 决定。
- `proprietary-format-recovery`、`firmware-iot-forensics`、`nas-raid-encrypted-storage` 和 `malware-forensics` 已可执行，但只能由 Router 决定并调用。
