---
name: firmware-iot-forensics
description: 对 Router 已确认的固件、IoT 镜像、固件 slice 或嵌套固件 Artifact 做 bounded、read-only 静态分析；识别容器、布局、文件系统和组件，有限提取并检查配置、服务和安全线索，不执行或动态启动固件。
---

# firmware-iot-forensics

## Purpose

在 `forensic-router` 选择本 Skill 后，确认固件容器与边界，建立组件清单，在批准范围内做有限提取和目标化静态检查，并输出可回查的 Artifact、Finding、Evidence 和 `firmware_status`。本 Skill 不执行固件、不处理存储解锁，也不生成最终答案或 Report。

## Use When

- direct route 已由至少两类相互支持的 Evidence 证明，例如 header/length/checksum、partition 或 segment 闭合、文件系统几何、可复现 parser 结果、manifest 或 boot metadata。
- `uncommon-media-triage` 已识别固件式结构并通过 Router 返回 bounded regions 和核心引用。
- `proprietary-format-recovery` 已恢复并验证嵌套固件 Artifact，再通过 Router Handoff。
- 已确认的固件 container、rootfs、kernel 或文件系统需要静态分析。

扩展名、文件名、品牌、设备名、单个 magic、熵值或外部资料只能作为线索。parser 失败、高熵或压缩特征不能直接证明加密。`visited_skills` 已包含本 Skill 时不得再次选择。

## Inputs

复用 Request Envelope；`request.context` 必须包含当前 Route Record。核心 payload 字段及语义见 `docs/data-contracts.md` 8.13：

- `source_artifact_refs`
- `candidate_regions`
- `route_basis`
- `artifact_refs`、`finding_refs`、`ledger_event_refs`
- `analysis_limits`、`extraction_limits`
- 可选 container、filesystem、architecture 和 partition hints

开始前确认：

1. effective source 非空，引用均可解析为 Artifact Record；1GB 以上 source 已经过 `large-artifact-strategy`。
2. 二进制或 container 输入具有非空 bounded regions；offset、length、source size 和归属关系合法。
3. 派生 Artifact 指向直接上游 Artifact，嵌套来源可以逐级回查。
4. Artifact、Finding、Ledger Event 和 route basis 均可回查。
5. direct route 具有两类独立 Evidence；uncommon/proprietary transfer 满足各自 Handoff 要求。
6. 显式 limits 可执行且未超限；需要 Gate 的动作已经批准。

有限提取要求 `extraction_limits` 完整提供以下正整数：

- `max_depth`
- `max_components`
- `max_total_extracted_bytes`
- `max_single_component_bytes`
- `timeout_seconds`

缺少或无法强制这些限制时，只做 container、layout、signature 和 parser capability 的静态识别，不自动提取，并记录 `required_next_action`。

## Outputs

复用 Response Envelope。payload 保留以下核心输出：

- `firmware_assessments`
- `component_inventory`
- `filesystem_candidates`
- `extracted_component_refs`
- `security_finding_refs`
- `validation_checks`
- `counter_evidence`
- `unresolved_questions`
- `required_next_action`
- `firmware_status`

组件清单表达 container、partition、filesystem、bootloader、kernel、rootfs 和其他组件的层级与 Evidence。每个派生 Artifact 记录直接 `source_artifact_id`、完整 Hash 和对应 Ledger Event；`security_finding_refs` 只引用 Response 顶层 Finding。

`firmware_status` 只允许：

| Status | Meaning |
|---|---|
| `candidate_only` | 只有候选，尚无可复现结构 |
| `container_validated` | container 或 header 边界得到验证 |
| `layout_reproduced` | partition、segment 或组件关系可重复重建 |
| `filesystem_validated` | 文件系统由 parser 或独立结构检查验证 |
| `extraction_reproduced` | 有限提取可复现，派生来源和完整 Hash 已验证 |
| `rejected` | 批准范围内所有相关 Hypothesis 均被证伪 |
| `bounded_checks_exhausted` | 批准检查完成，仍有未能验证或证伪的候选 |
| `unknown` | 输入或 Evidence 不足，或检查尚未完成 |

选择当前 Evidence 支持的最高状态；单个 parser 或 Hypothesis 失败不得使整体变为 `rejected`。原始口令、token、私钥和敏感配置只保存在受保护派生 Artifact 中，正文只记录引用、fingerprint 或脱敏摘要。

## Workflow

### Step 1: Confirm Scope

验证 source Artifact、bounded regions、调查目标、Route、limits 和 Evidence 引用。大文件先经过 LAS；弱线索只形成 Hypothesis。

### Step 2: Identify Containers and Boundaries

选择适合当前格式且已安装的静态工具，识别 header、partition、segment、文件系统和嵌套容器。记录 offset、length、格式候选、验证结果和反证；不要强制使用某个工具。

### Step 3: Perform Bounded Extraction

只在批准工作目录中提取，并遵守深度、组件数、总输出大小、单组件大小和超时限制。不得路径越界、跟随链接、在宿主机创建特殊文件或恢复危险权限。工具不能保证这些边界时，只执行静态识别并记录 `required_next_action`。

### Step 4: Build Component Inventory

建立 container、partition、filesystem、bootloader、kernel、rootfs 和其他组件的层级清单。为组件绑定来源、Hash、Artifact 和 Evidence，使结果可浏览、检索和比较。

### Step 5: Run Targeted Static Checks

根据目标检查系统版本与架构、用户与认证配置、凭据线索、证书与信任配置、启动脚本、服务、Web 管理界面、SSH/Telnet/FTP/TFTP/Dropbear、更新机制、可执行文件、共享库、第三方组件和远程端点。把发现写成绑定 Artifact 与 Ledger Event 的 Finding，并对敏感值最小披露。

### Step 6: Validate and Summarize

交叉验证 container、layout、filesystem 和组件关系；保留成功、失败、反证和未决问题。根据全部 Evidence 选择一个 `firmware_status`，不得把提取成功等同于分析完成。

### Step 7: Emit Results and Handoff

输出核心 Artifact、Finding、Ledger Event、组件清单和状态。默认返回 `forensic-autopilot`；只有产生新 Artifact 或 Finding 且出现新的可执行消费者候选时，才按 Handoff 最多一次返回 Router。本 Skill 不直接调用其他消费者。

## Route Matrix

| Input | Minimum Evidence | Action |
|---|---|---|
| direct firmware route | 两类独立验证机制、合法 regions 和引用 | Router 选择本 Skill |
| uncommon firmware candidate | bounded regions、结构 Evidence、Artifact/Finding/本轮 Ledger Event | 经 Router Handoff |
| proprietary nested firmware | 已验证嵌套 Artifact、直接来源、Hash 和结构 Evidence | 经 Router Handoff |
| container/layout/filesystem | 边界闭合或 parser/独立结构检查一致 | 验证并建立组件清单 |
| bounded component extraction | 完整 extraction limits、批准工作目录和安全工具 | 有限提取 |
| 独立 storage candidate | 实际提取的存储镜像、阵列成员或加密卷 Artifact，附 provenance、明确 Hash 状态和本轮 Evidence | 记录 executable candidate，经 Router 重评 |
| malware candidate | 独立样本 Artifact，加明确恶意分析目标或独立可疑上下文及本轮 Evidence | 记录 executable candidate，经 Router 重评；普通 ELF/脚本保持 firmware |
| Evidence 仍不足 | 已保留检查、反证和限制 | 返回 autopilot 并说明下一步 |

## Evidence Requirements

- 每个结论成为引用 Artifact 和 Ledger Event 的 Finding。
- container、region 和组件记录可回查的来源、边界和验证依据。
- 派生 Artifact 记录直接来源、完整 Hash、保存位置和生成它的 Ledger Event。
- malware candidate 记录独立样本来源、Hash、目标/可疑上下文和本轮 Evidence；普通 firmware 组件不自动转出。
- 组件清单保留层级关系、格式/角色 Hypothesis 和反证。
- 静态检查同时保留成功、失败、未执行原因和未决问题。
- 外部资料只提供方法线索，结论必须由当前 Artifact 验证。

## Handoff

正式入口：

- `file-triage` / `large-artifact-strategy` → `forensic-router` → `firmware-iot-forensics`
- `uncommon-media-triage` → `forensic-router` → `firmware-iot-forensics`
- `uncommon-media-triage` → `forensic-router` → `proprietary-format-recovery` → `forensic-router` → `firmware-iot-forensics`

Router 是唯一消费者决策点。uncommon、proprietary 和 LAS 只提供 bounded Evidence 与核心引用，不直接调用本 Skill。Router 验证 source、regions、Route context、limits、Gate、`visited_skills` 和 hop 后才创建完整 Handoff。

本 Skill 默认返回 autopilot。只有本轮产生新 Artifact 或 Finding 且出现新的可执行消费者候选时，才可最多一次返回 Router，并提供 `reentry_reason`、非空 `new_evidence_refs`、本轮新 Ledger Event 和合法 hop。Router 不得重选已访问 Skill；禁止 proprietary → Router → firmware → Router → proprietary、firmware → Router → firmware，以及 uncommon → Router → firmware → Router → uncommon。

firmware 只有实际提取出独立存储镜像、阵列成员或加密卷 Artifact，并记录可回查 provenance、明确 Hash 状态、bounded regions、Finding 和本轮 Ledger Event 时，才可形成 executable storage candidate。已物化且在预算内的组件优先 verified Hash；大型、稀疏、流式或未物化 storage 视图允许 `deferred|unavailable`，其中 `deferred` 记录原因。正式后续链路为 `firmware-iot-forensics` → `forensic-router` → `nas-raid-encrypted-storage`；firmware 不直接调用 storage。禁止 firmware → Router → storage → Router → firmware 和 storage → Router → storage。

firmware 只有提取出独立样本 Artifact，并具有明确恶意分析目标或独立可疑上下文时，才可形成 executable malware candidate。正式链路为 `firmware-iot-forensics` → `forensic-router` → `malware-forensics`；firmware 只传递直接来源、Hash 状态和本轮 Evidence，不执行样本或直接调用 malware。禁止 firmware → Router → malware → Router → firmware 和 malware → Router → malware。

## Execution Gate

批准 regions、工作目录和 limits 内的只读识别、静态 parser、组件 Hash、有限提取和目标化静态读取无需 Gate。

以下动作必须停止并请求批准：

- 无界递归解包、大范围或全盘 carving、全文件 strings、超出 limits。
- 安装工具、联网、在线检索或第三方上传。
- 执行固件程序、脚本、宏或服务。
- QEMU、容器、虚拟机或其他动态启动。
- 修改固件、写入设备、UART、JTAG 或刷写。
- 爆破口令/密钥、长时间解密、RAID/LVM 激活、解锁或 mount。
- 修改 original Artifact、可写挂载或写入未批准路径。

## Stop Conditions

- Route、source、bounded regions 或核心 Evidence 引用无法验证。
- direct route 缺少两类独立 Evidence，且没有合格上游 transfer。
- limits 无效、已达到或工具无法保证安全提取边界。
- `visited_skills`、hop 或防循环条件不合法。
- 下一步需要 Execution Gate 但尚未批准。

停止提取不等于停止调查；仍可完成允许的静态识别、记录反证并返回 `required_next_action`。

## Prohibited Actions

- 不修改 original Artifact，不执行或动态启动固件。
- 不默认联网、上传、安装依赖或调用第三方服务。
- 不无界递归、不全文件 strings、不全盘 carving、不爆破。
- 不跟随链接，不创建宿主机特殊文件，不恢复危险权限。
- 不处理 RAID/LVM/NAS/加密存储，不做 UART/JTAG/刷写。
- 不按品牌、文件名、扩展名、单个 magic、熵值或外部结论确认固件。
- 不直接调用其他消费者，不生成最终答案或 Report。

## Notes

- 参考 [ReFirmLabs/binwalk](https://github.com/ReFirmLabs/binwalk) 的嵌入内容识别与可选提取定位，以及“熵值只作线索”的用法。
- 参考 [onekey-sec/unblob](https://github.com/onekey-sec/unblob) 的准确边界、有限递归、元数据报告与非特权提取思路。
- 参考 [fkie-cad/FACT_core](https://github.com/fkie-cad/FACT_core) 的组件树和可浏览、搜索、比较的结果组织。
- 参考 [craigz28/firmwalker](https://github.com/craigz28/firmwalker) 与 [e-m-b-a/emba](https://github.com/e-m-b-a/emba) 的目标化配置、服务、组件和安全弱点检查；结果仍需人工复核。
- [firmadyne/firmadyne](https://github.com/firmadyne/firmadyne) 用于说明仿真属于独立动态阶段，不在本 Skill 的自动范围内。
- 仅借鉴公开工作流和工具定位，未复制项目代码。实际工具选择取决于环境与检材，不要求安装全部工具。
- `nas-raid-encrypted-storage` 与 `malware-forensics` 已可执行，但只能由 Router 决定。
