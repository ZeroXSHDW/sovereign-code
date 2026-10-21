---
name: file-triage
description: 文件分流入口。对 incoming material 做第一轮只读排查：文件识别、hash 计算、分类、路由。大文件进入 Large Artifact Mode。
---

# file-triage

## Purpose

file-triage 是所有检材的第一轮只读分流。识别文件类型、计算 hash、建立工作目录并生成分类结果和路由建议，最终路径由 `forensic-router` 决定。

本 skill 只负责通用文件级初筛；结构识别与最终路径判断分别由下游 Triage Skill 和 `forensic-router` 承担。

## Use When

- forensic-autopilot 的 Step 3（Triage）
- 用户提供新的检材需要初步分析
- 需要判断检材类型和大小以决定后续路径

## Inputs

| Input | Required | Description |
|-------|----------|-------------|
| `material` | Yes | 检材路径（文件、目录、压缩包、镜像） |
| `objective` | Recommended | 分析目标（影响分类优先级） |

## Outputs

| Output | Description |
|--------|-------------|
| `material_type` | 检材类型（文件/目录/压缩包/镜像/固件/PCAP） |
| `file_list` | 文件清单（如目录或压缩包） |
| `hash` | 检材的 SHA256 hash |
| `size` | 检材大小 |
| `triage_notes` | 分类结论和路由建议 |
| `request.payload.candidate_regions` | 发现结构候选时必须输出的非空 bounded region 列表 |
| `large_artifact_mode` | 是否触发大文件模式 |

## Workflow

### Step 1: Artifact Precheck

- 确认检材存在
- 读取大小和 mtime
- 判断是单文件还是目录
- 如果 >= 1GB，标记 `large_artifact_mode: true`

**Evidence**: 记录检材路径、大小、mtime

### Step 2: Hash (Conditional)

- < 1GB: 默认计算 MD5 + SHA256
- 1GB–10GB: 可计算但记录耗时
- 10GB+: 不默认完整 hash，不阻塞后续分析

**Evidence**: 记录 hash 值

### Step 3: File Identification

- 对单文件：`file` 命令识别类型
- 对目录：生成轻量 manifest，找最大文件
- 对压缩包：`7z l` 列出内容
- 对镜像：识别文件系统类型

**Evidence**: 记录 file 命令输出和文件类型

### Step 4: Classification

根据文件类型分类：

| Type | Category | Next Step |
|------|----------|-----------|
| 压缩包 (zip/tar/7z/rar) | archive | 安全列表；如需解包，仅在工作副本中解包后重新 triage |
| 磁盘镜像 (E01/VHD/VMDK/qcow2/raw) | disk-image | → forensic-router（最终路径判断） |
| 固件 (SquashFS/CramFS/JFFS2/UBIFS) | firmware | → forensic-router（最终路径判断） |
| PE/ELF 二进制 | binary | → forensic-router（最终路径判断） |
| PCAP/网络流量 | network | → forensic-router（最终路径判断） |
| 数据库文件 | database | → forensic-router（最终路径判断） |
| Web 源码/配置 | webapp | → forensic-router（最终路径判断） |
| 文本/JSON/XML/CSV | text | → forensic-router（最终路径判断） |
| 图片/音频/视频 | media | → forensic-router（最终路径判断） |
| 未知 | unknown | → forensic-router |

**Evidence**: 记录分类结果和路由建议

Classification 表只生成分类结果和路由建议。`file-triage` 不直接调用领域 Skill；所有普通分类都交给 `forensic-router` 做最终路径决策。

PCAP/网络流量的 `triage_notes` 必须保留 `network` 分类、`pcap` 标记、识别出的文件格式和 Artifact 引用。
本 Skill 不直接调用 `timeline-reconstruction`；由 `forensic-router` 判断当前是否存在兼容消费者。

### Step 4a: Lightweight Structural Triage Notes

对普通文件头和已批准的 bounded sample，只记录供 Router 复核的轻量结构候选，不建立 `candidate_schema`，不解释字段业务语义，也不直接调用 `uncommon-media-triage`。

`triage_notes` 可包含：

| Note | Minimum recorded basis |
|---|---|
| `repeated-boundary-candidate` | 候选边界数量、候选间隔、sample offset 和 Artifact 引用 |
| `time-series-candidate` | 多个候选时间值、原始字节位置、相邻差值及不确定项 |
| `tlv-candidate` | 重复 tag、候选 length 字段位置、bounded closure 结果 |
| `structured-low-medium-entropy-candidate` | 熵摘要，加上重复边界、常量字段、长度闭合、checksum 或其他独立结构 Evidence |
| `candidate-region` | source Artifact、offset、length、sampling method 和派生 Artifact 引用（如有） |
| `verified-negative` | 已测试并失败的签名、边界或字段 Hypothesis 及 Ledger Event 引用 |

发现任何准备交给 Router 判断的结构候选时，`file-triage` 必须同时在 `request.payload.candidate_regions` 输出非空列表。每个 region 必须包含：

- `region_id`
- `source_artifact_ref`
- `derived_artifact_ref`；没有派生 slice 时显式使用 `null`
- 非负整数 `offset`；不得使用十六进制、带单位或其他文本格式
- 正整数 `length`，且 `offset + length` 不超过 source Artifact size
- 非空 `sampling_method`

定义 `effective_source_artifact_refs`：非空 `request.payload.source_artifact_refs` 优先；缺失或空数组时使用 `request.material_info.artifact_refs`。有效列表必须非空且每个引用都能解析到 Artifact Record。每个 region 的 `source_artifact_ref` 必须属于该列表；`derived_artifact_ref` 存在时必须能解析到 Artifact Record，且其 `source_artifact_id` 等于 region 的 `source_artifact_ref`。

没有合法 bounded candidate region、有效 source Artifact 列表或派生关系存在冲突时，不得建议 `uncommon-media-triage` 路线；记录具体缺失或冲突原因、required next action、原始观察和 verified negative，由 Router 决定返回 `file-triage` 或 `large-artifact-strategy`。

unknown、文件扩展名、设备名称、品牌、单个 magic、单个时间戳、单个坐标或单独熵值不能独立生成 `uncommon-media-triage` 路由建议。`file-triage` 只把原始观察和负面验证交给 `forensic-router`。

### Step 5: Workspace Setup

建立标准工作目录和文件：

| Directory/File | Purpose |
|----------------|---------|
| `original/` | 保存原始检材引用或只读副本 |
| `work/` | 保存分析副本、采样片段、索引 |
| `output/` | 保存导出结果 |
| `scripts/` | 保存本次调查使用的脚本 |
| `logs/` | 保存命令输出 |
| `evidence-ledger.md` | 人工审查主视图 |
| `evidence-ledger.jsonl` | 机器校验日志 |
| `investigation-log.md` | 记录调查过程 |
| `notes.md` | 记录分析笔记 |

**Evidence**: 记录工作目录结构

## Large Artifact Mode

触发条件（满足任一）：
- 单文件 >= 1GB
- 目录内存在 >= 1GB 的主文件
- 扩展名或 file 结果属于 raw/bin/img/dd/E01/vmdk/vhd/qcow2

触发后：
- 调用 `large-artifact-strategy`
- 不默认复制两份大文件
- 不默认全量 strings/xxd/hash
- 先建立 source path、size、mtime、采样、signature hits、offset map
- `large-artifact-strategy` 返回增强后的 triage 证据后，再交给 `forensic-router` 做最终路径决策

## Evidence Requirements

| Field | When to Record |
|-------|---------------|
| `artifact` | 检材本身 |
| `source` | 检材来源路径 |
| `hash` | 检材 hash |
| `command` | file/7z/hash 命令 |
| `finding` | 文件类型、分类结果 |
| `confidence` | 分类置信度 |

## Handoff

**Passes to**: `forensic-router`（传递分类结论）、`large-artifact-strategy`（大文件）
**Data available**: `request.material_info.artifact_refs`, material_type, file_list, hash, triage_notes, `request.payload.candidate_regions`（包括 source/derived Artifact 引用、offset、length、sampling method）、轻量结构候选和 verified negatives

## Stop Conditions

- 检材不存在或无法读取
- 检材严重损坏，无法取得任何可用元数据、采样结果或文件头

> **Note**: Missing objective is not a stop condition for neutral triage. Continue with neutral classification (hash, size, file type, container check, large artifact mode, triage_notes) and record objective as unknown.
> 
> 无法识别常见文件类型时也不停止；应记录 unknown classification，并交给 `forensic-router` 做最终路径判断。当前没有兼容消费者时保留证据并返回 `no-compatible-skill`，不创建到不存在 Skill 的 Handoff。

## Notes

- file-triage 是只读操作，不修改原始检材
- file-triage 不建立 candidate_schema、不解析字段语义、不直接调用 uncommon-media-triage
- 大文件模式下，work/ 只保存采样片段和索引，不代表完整副本
- 详见 `templates/evidence-ledger.md` 记录格式
