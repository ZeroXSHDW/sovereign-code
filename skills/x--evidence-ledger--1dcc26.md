---
name: evidence-ledger
description: 证据记录核心。贯穿全链路，定义 artifact 登记、hash 记录、操作日志、chain of custody 字段。所有取证 skill 写入 evidence-ledger，answer-gate 从 evidence-ledger 读取校验。
disable-model-invocation: false
---

# evidence-ledger

## Purpose

evidence-ledger 是取证工作流的证据记录核心。它不是一个独立的分析 skill，而是一个贯穿全链路的记录规范。所有其他 skill 在执行过程中都向 evidence-ledger 写入证据记录。

## Use When

- 任何 skill 执行分析操作时（自动写入）
- 需要查看已有证据时（读取）
- answer-gate 校验时（读取并验证）
- 生成报告时（读取并引用）

## Inputs

| Input | Required | Description |
|-------|----------|-------------|
| `action` | Yes | 写入/读取/验证 |
| `entry` | Yes (write) | 证据条目 |

## Outputs

| Output | Description |
|--------|-------------|
| `ledger` | 完整的证据记录 |
| `entry_id` | 新写入条目的 ID |
| `validation` | 验证结果（对 validate 动作） |

## Evidence Entry Format

每条证据记录包含以下字段：

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `id` | Yes | auto | 自增 ID |
| `timestamp` | Yes | auto | 记录时间 |
| `artifact` | Yes | string | 被检查的对象（文件路径、服务名、容器 ID） |
| `source` | Yes | string | 来源（磁盘镜像路径、远程主机、容器名） |
| `hash` | Recommended | string | SHA256 hash（如适用） |
| `command` | Yes* | string | 执行的命令或工具调用（*工具操作时必填） |
| `finding` | Yes | string | 发现的内容 |
| `confidence` | Yes | enum | `high` / `medium` / `low` |
| `next_action` | Recommended | string | 下一步计划 |
| `category` | Recommended | enum | `acquisition` / `analysis` / `validation` / `negative` |

## Dual-Format Design

evidence-ledger 采用双格式设计：

| 格式 | 文件 | 用途 |
|------|------|------|
| **Markdown** | `evidence-ledger.md` | 人工审查主视图 — 可读、可打印、可编辑 |
| **JSONL** | `evidence-ledger.jsonl` | 机器校验日志 — 结构化、可查询、append-only |

- 两种格式记录相同的条目，skill 同时写入两者
- `answer-gate` **优先使用 JSONL** 做结构化校验（字段完整性、交叉引用检查）
- `report-writer` **引用 Markdown** 作为报告附录

## Workflow

### Step 1: Initialize

每次新的调查开始时，创建新的 evidence-ledger 文件：
- `evidence-ledger.md` — 人工审查主视图
- `evidence-ledger.jsonl` — 机器校验日志
- 记录调查基本信息（检材、目标、开始时间）

### Step 2: Write Entries

其他 skill 在执行过程中按需写入条目。写入规则：
- 每次工具调用至少一条记录
- 每个 finding 一条记录
- 负面发现也要记录（"未找到 X"）

### Step 3: Query Entries

answer-gate 和 report-writer 读取已有条目：
- 按 artifact 查询
- 按 category 查询
- 按 confidence 查询

### Step 4: Validate Ledger

answer-gate 校验时检查：
- 每个 cited finding 是否有对应的 evidence entry
- evidence entry 是否引用真实存在的 artifact
- hash 值是否匹配
- confidence level 是否合理

## Evidence Requirements

本 skill 自身的证据：
| Field | When to Record |
|-------|---------------|
| `artifact` | 被记录的检材/对象 |
| `finding` | 记录操作本身 |

## Handoff

**Passes to**: 所有其他 skill（通过读写共享的 evidence-ledger 文件）
**Data available**: 完整的证据记录

## Stop Conditions

- 本 skill 不会独立停止，它是被动记录层

## Notes

- evidence-ledger 是文件级共享，不是 API
- 双格式：Markdown（人工审查）+ JSONL（机器校验）
- 每个调查独立的 evidence-ledger.md 和 evidence-ledger.jsonl
- 详见 `templates/evidence-ledger.md` 和 `templates/evidence-ledger.jsonl`
